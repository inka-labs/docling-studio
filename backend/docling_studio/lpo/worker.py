"""One experiment, run as its own process: python -m docling_studio.lpo.worker <experiment folder>.

It goes through the experiment's documents in order, converting (or taking Docling's result from
the cache), mapping fields and running the checks, and writes results/<doc>.json for each, plus
progress.json. A document that already has a result from the same settings and mapper is skipped,
so an interrupted experiment picks up where it stopped.
"""

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import checks, convert, extract, store, testset


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def result_for(doc: dict, config: dict, conv: str, tools: dict) -> dict:
    """Convert, map and check one document."""
    t0 = time.monotonic()
    if config["extractor"] == "vlm":
        data, cached = convert.vlm_extract(doc, config, conv, tools["extractor"])
        t1 = time.monotonic()
        mapped = extract.from_vlm(data)
    else:
        document, cells, cached = convert.convert(doc, config, conv, tools["converter"])
        t1 = time.monotonic()
        mapped = extract.extract(document, cells)
    t2 = time.monotonic()
    return {
        "doc": doc["id"], "conv": conv, **mapped, "checks": checks.run(mapped["record"]),
        "cached": cached, "seconds": {"convert": None if cached else round(t1 - t0, 2), "map": round(t2 - t1, 3)},
        "error": None, "finished": _now(),
    }


# Docling's threaded page pipeline now and then deadlocks (every thread waiting on a lock, no CPU)
# on a document that converts fine on a second try. A stuck document is given up after this long:
# its result records the timeout and the worker restarts itself in place (same process id, so the
# dispatcher keeps waiting on it), skipping finished documents. After MAX_TIMEOUTS it counts as failed.
TIMEOUT = float(os.environ.get("LPO_DOC_TIMEOUT", 300))
MAX_TIMEOUTS = 2


def watchdog(folder: Path, out: Path, did: str, conv: str, attempts: int) -> threading.Timer:
    def fire():
        store.write_json(out, {"doc": did, "conv": conv, "timeouts": attempts + 1, "finished": _now(),
                               "error": f"Timed out after {TIMEOUT:.0f} s: Docling stopped responding."})
        print(f"{did} timed out after {TIMEOUT:.0f} s (attempt {attempts + 1}); restarting the worker.", flush=True)
        os.execv(sys.executable, [sys.executable, "-X", "utf8", "-m", "docling_studio.lpo.worker", str(folder)])

    timer = threading.Timer(TIMEOUT, fire)
    timer.daemon = True
    timer.start()
    return timer


def lazy(make):
    holder = {}

    def get():
        if "v" not in holder:
            holder["v"] = make()
        return holder["v"]

    return get


def main(folder: Path) -> int:
    exp = store.read_json(folder / "experiment.json", None)
    if not exp:
        print("No experiment.json here.", flush=True)
        return 2
    config, conv = exp["config"], exp["conv"]
    results = folder / "results"
    results.mkdir(exist_ok=True)
    tools = {"converter": lazy(lambda: convert.converter(config)), "extractor": lazy(lambda: convert.extractor(config))}
    total = len(exp["docs"])
    progress = {"done": 0, "failed": 0, "total": total, "current": None, "updated": _now()}
    print(f"{exp['name']}: {total} documents, settings {json.dumps(config)}", flush=True)
    for i, did in enumerate(exp["docs"], 1):
        out = results / f"{did}.json"
        previous = store.read_json(out, None)
        if previous and not previous.get("error") and previous.get("conv") == conv and previous.get("mapper") == extract.MAPPER_VERSION:
            progress["done"] += 1
            continue
        timeouts = previous.get("timeouts", 0) if previous and previous.get("conv") == conv else 0
        if timeouts >= MAX_TIMEOUTS:
            progress["done"] += 1
            progress["failed"] += 1
            continue
        doc = testset.load()["docs"].get(did)  # read each time: documents can be taken out meanwhile
        progress.update(current=did, updated=_now())
        store.write_json(folder / "progress.json", progress)
        if not doc or doc.get("excluded"):
            # taken out after the experiment was queued: skipped, and not counted (experiments.score)
            result = {"doc": did, "error": "Taken out of the test set.", "finished": _now()}
        else:
            timer = watchdog(folder, out, did, conv, timeouts)
            try:
                result = result_for(doc, config, conv, tools)
            except Exception as e:
                result = {"doc": did, "conv": conv, "error": f"{type(e).__name__}: {e}", "finished": _now(),
                          "trace": traceback.format_exc()[-4000:]}
            finally:
                timer.cancel()
        store.write_json(out, result)
        progress["done"] += 1
        if result.get("error"):
            progress["failed"] += 1
            print(f"[{i}/{total}] {did} ({doc and doc['client']}) failed: {result['error']}", flush=True)
        else:
            s = result["seconds"]
            took = "cached" if result["cached"] else f"{s['convert']:.1f}s"
            ok = "ok" if result["checks"]["ok"] else "checks: " + ", ".join(k for k, v in result["checks"].items() if not v)
            print(f"[{i}/{total}] {did} ({doc['client']}, {doc['kind']}) {took}, {len(result['record']['lines'])} lines, {ok}", flush=True)
    progress.update(current=None, updated=_now())
    store.write_json(folder / "progress.json", progress)
    print(f"Finished: {progress['done'] - progress['failed']} read, {progress['failed']} failed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
