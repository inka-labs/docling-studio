"""Experiments: one strategy (extract + conversion settings) run over some of the test set.

They queue and run one at a time, each in its own process (worker.py), since conversions load
large models. Scoring is done here, from the results and the labels as they are now, so labelling
more documents improves every experiment's numbers without running anything again.
"""

import os
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import checks, convert, extract, schema, store, testset

STATUSES = ("queued", "running", "finished", "stopped", "failed", "interrupted")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExperimentError(Exception):
    pass


def labels() -> dict[str, dict]:
    folder = store.path("labels")
    if not folder.exists():
        return {}
    return {p.stem: store.read_json(p, None) for p in folder.glob("*.json")}


SPLITS = ("dev", "holdout", "both")


def choose_docs(subset: str, limit: int | None, split: str = "dev") -> list[str]:
    """The documents an experiment runs on: a subset of one split (testset.split_of). Ids are
    hashes, so their order is a fair shuffle: the first N of a subset are a sample of it, the same
    sample every time."""
    if split not in SPLITS:
        raise ExperimentError(f"Unknown split: {split}")
    docs = sorted((d for d in testset.active_docs() if split == "both" or testset.split_of(d["id"]) == split),
                  key=lambda d: d["id"])
    if subset == "all":
        chosen = docs
    elif subset == "digital":
        chosen = [d for d in docs if d["kind"] == "digital"]
    elif subset == "scans":
        chosen = [d for d in docs if d["kind"] in ("scan", "image")]
    elif subset == "labelled":
        have = set(labels())
        chosen = [d for d in docs if d["id"] in have]
    elif subset.startswith("client:"):
        chosen = [d for d in docs if d["client"] == subset[7:]]
    elif subset.startswith("failing:"):
        eid = store.safe_id(subset[8:])
        failing = set()
        for p in store.path("experiments", eid, "results").glob("*.json"):
            r = store.read_json(p, {})
            if r.get("error") or not (r.get("checks") or {}).get("ok"):
                failing.add(p.stem)
        chosen = [d for d in docs if d["id"] in failing]
    else:
        raise ExperimentError(f"Unknown subset: {subset}")
    if limit:
        chosen = chosen[:limit]
    return [d["id"] for d in chosen]


class Experiments:
    def __init__(self):
        self.root = store.path("experiments")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._procs: dict[str, subprocess.Popen] = {}
        self._stopping: set[str] = set()
        self._summaries: dict[str, tuple[tuple, dict]] = {}
        for path in self.root.glob("*/experiment.json"):
            exp = store.read_json(path, None)
            if exp and exp.get("status") in ("queued", "running"):
                exp.update(status="interrupted", ended=exp.get("ended") or _now())
                store.write_json(path, exp)
        threading.Thread(target=self._dispatch, name="lpo-experiments", daemon=True).start()

    # Reading ------------------------------------------------------------------------------------

    def _load(self, eid: str) -> dict:
        exp = store.read_json(self.root / store.safe_id(eid) / "experiment.json", None)
        if not exp:
            raise ExperimentError("No such experiment.")
        return exp

    def _save(self, exp: dict) -> None:
        store.write_json(self.root / exp["id"] / "experiment.json", exp)

    def progress(self, eid: str) -> dict:
        return store.read_json(self.root / eid / "progress.json", {"done": 0, "failed": 0, "total": 0})

    def all(self) -> list[dict]:
        out = []
        for path in self.root.glob("*/experiment.json"):
            exp = store.read_json(path, None)
            if exp:
                out.append({**exp, "docs": len(exp["docs"]), "progress": self.progress(exp["id"]),
                            "summary": self.summary(exp["id"], brief=True)})
        return sorted(out, key=lambda e: e["created"], reverse=True)

    def get(self, eid: str) -> dict:
        exp = self._load(eid)
        return {**exp, "docs": len(exp["docs"]), "progress": self.progress(eid), "summary": self.summary(eid),
                "stale_mapper": self._stale(eid)}

    def result(self, eid: str, did: str) -> dict | None:
        return store.read_json(self.root / store.safe_id(eid) / "results" / f"{store.safe_id(did)}.json", None)

    def results(self, eid: str) -> list[dict]:
        folder = self.root / store.safe_id(eid) / "results"
        return [r for p in sorted(folder.glob("*.json")) if (r := store.read_json(p, None))]

    def log(self, eid: str, offset: int = 0) -> dict:
        path = self.root / store.safe_id(eid) / "log.txt"
        size = path.stat().st_size if path.exists() else 0
        offset = max(0, min(offset, size))
        if offset == 0 and size > 256 * 1024:
            offset = size - 256 * 1024
        data = b""
        if path.exists():
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read()
        return {"text": data.decode("utf-8", errors="replace"), "offset": offset + len(data), "size": size}

    def _stale(self, eid: str) -> bool:
        return any(r.get("mapper") not in (None, extract.MAPPER_VERSION) for r in self.results(eid) if not r.get("error"))

    # Scoring ------------------------------------------------------------------------------------

    def summary(self, eid: str, brief: bool = False) -> dict:
        folder = self.root / eid / "results"
        label_dir = store.path("labels")
        stamp = (max((p.stat().st_mtime for p in folder.glob("*.json")), default=0) if folder.exists() else 0,
                 len(list(folder.glob("*.json"))) if folder.exists() else 0,
                 max((p.stat().st_mtime for p in label_dir.glob("*.json")), default=0) if label_dir.exists() else 0,
                 len(list(label_dir.glob("*.json"))) if label_dir.exists() else 0)
        cached = self._summaries.get(eid)
        if not cached or cached[0] != stamp:
            cached = (stamp, score(self.results(eid), testset.load()["docs"], labels()))
            self._summaries[eid] = cached
        s = cached[1]
        if brief:
            return {k: s[k] for k in ("documents", "errors", "ok_rate", "checks", "fill", "lines_found", "seconds",
                                      "labelled", "accuracy", "perfect_rate", "by_kind")}
        return s

    # Changing -----------------------------------------------------------------------------------

    def create(self, request: dict) -> dict:
        try:
            config = convert.check_config(request.get("config") or {})
        except ValueError as e:
            raise ExperimentError(str(e))
        subset = str(request.get("subset") or "all")
        limit = request.get("limit")
        if limit in ("", None, 0):
            limit = None
        elif not isinstance(limit, int) or limit < 1:
            raise ExperimentError("The number of documents must be a whole number.")
        split = str(request.get("split") or "dev")
        docs = choose_docs(subset, limit, split)
        if not docs:
            raise ExperimentError("No documents match. Build the test set (or label some documents) first.")
        eid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        name = str(request.get("name") or "").strip()[:80] or describe(config)
        exp = {"id": eid, "name": name, "config": config, "conv": convert.conversion_key(config), "subset": subset,
               "limit": limit, "split": split, "docs": docs, "status": "queued", "created": _now(), "started": None, "ended": None,
               "exit_code": None, "notes": str(request.get("notes") or "")[:2000]}
        (self.root / eid).mkdir(mode=0o700)
        with self._lock:
            self._save(exp)
            self._wake.notify_all()
        return self.get(eid)

    def update(self, eid: str, changes: dict) -> dict:
        with self._lock:
            exp = self._load(eid)
            if "name" in changes:
                exp["name"] = str(changes["name"]).strip()[:80] or exp["name"]
            if "notes" in changes:
                exp["notes"] = str(changes["notes"])[:2000]
            self._save(exp)
        return self.get(eid)

    def resume(self, eid: str) -> dict:
        """Run again: documents that already have a result are skipped."""
        with self._lock:
            exp = self._load(eid)
            if exp["status"] in ("queued", "running"):
                raise ExperimentError("It's already running.")
            exp.update(status="queued", ended=None, exit_code=None)
            self._save(exp)
            self._wake.notify_all()
        return self.get(eid)

    def stop(self, eid: str) -> dict:
        with self._lock:
            exp = self._load(eid)
            if exp["status"] == "queued":
                exp.update(status="stopped", ended=_now())
                self._save(exp)
            elif exp["status"] == "running":
                self._stopping.add(eid)
                proc = self._procs.get(eid)
                if proc:
                    threading.Thread(target=_kill, args=(proc,), daemon=True).start()
        return self.get(eid)

    def delete(self, eid: str) -> None:
        with self._lock:
            exp = self._load(eid)
            if exp["status"] in ("queued", "running"):
                raise ExperimentError("Stop it before deleting it.")
            shutil.rmtree(self.root / eid, ignore_errors=True)
            self._summaries.pop(eid, None)

    def remap(self, eid: str) -> dict:
        """Map fields again from the cached conversions (after a mapper change): seconds, not hours."""
        exp = self._load(eid)
        if exp["status"] in ("queued", "running"):
            raise ExperimentError("Wait for it to finish first.")
        if exp["config"]["extractor"] != "rules":
            raise ExperimentError("Only rule-based experiments have a mapping to redo.")
        done = 0
        for r in self.results(eid):
            cached = None if r.get("error") else convert.load_cached(exp["conv"], r["doc"])
            if not cached:
                continue
            mapped = extract.extract(*cached)
            r.update(mapped, checks=checks.run(mapped["record"]))
            store.write_json(self.root / eid / "results" / f"{r['doc']}.json", r)
            done += 1
        return {"remapped": done, **self.get(eid)}

    def stop_all(self) -> None:
        for exp in self.all():
            if exp["status"] in ("queued", "running"):
                self.stop(exp["id"])

    # Running ------------------------------------------------------------------------------------

    def _dispatch(self) -> None:
        while True:
            with self._lock:
                while True:
                    exps = [e for p in self.root.glob("*/experiment.json") if (e := store.read_json(p, None))]
                    if not any(e["status"] == "running" for e in exps):
                        queued = sorted((e for e in exps if e["status"] == "queued"), key=lambda e: e["created"])
                        if queued:
                            exp = queued[0]
                            break
                    self._wake.wait(timeout=2)
                exp.update(status="running", started=_now())
                self._save(exp)
            threading.Thread(target=self._run, args=(exp["id"],), name=f"lpo-exp-{exp['id']}", daemon=True).start()

    def _run(self, eid: str) -> None:
        folder = self.root / eid
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        kwargs: dict = {"cwd": folder, "env": env, "stdin": subprocess.DEVNULL, "stdout": open(folder / "log.txt", "ab"),
                        "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "docling_studio.lpo.worker", str(folder)], **kwargs)
        except OSError as e:
            with self._lock:
                exp = self._load(eid)
                exp.update(status="failed", ended=_now(), error=f"Couldn't start: {e}")
                self._save(exp)
            return
        finally:
            kwargs["stdout"].close()
        with self._lock:
            self._procs[eid] = proc
        code = proc.wait()
        with self._lock:
            self._procs.pop(eid, None)
            stopped = eid in self._stopping
            self._stopping.discard(eid)
            exp = self._load(eid)
            exp.update(status="stopped" if stopped else "finished" if code == 0 else "failed", ended=_now(), exit_code=code)
            self._save(exp)
            self._wake.notify_all()


def _kill(proc: subprocess.Popen, grace: float = 5) -> None:
    from ..runs import RunManager

    RunManager._kill(proc, grace)


def describe(config: dict) -> str:
    if config["extractor"] == "vlm":
        return f"VLM: {config['vlm_model']}" + (", straightened" if config["straighten"] else "")
    parts = [f"OCR {config['ocr']}" + (f" ({config['ocr_engine']})" if config["ocr"] != "off" and config["ocr_engine"] != "auto" else ""),
             f"tables {config['table_mode']}"]
    if config["straighten"]:
        parts.append("straightened")
    return "Rules: " + ", ".join(parts)


def score(results: list[dict], docs: dict, truth: dict[str, dict]) -> dict:
    """Everything the leaderboard and the experiment page show. Documents labelled "not an LPO"
    (CVs, emails: the bucket has them) and documents taken out of the test set don't count."""
    results = [r for r in results if not (truth.get(r["doc"]) or {}).get("not_lpo")
               and not (docs.get(r["doc"]) or {}).get("excluded")]
    good = [r for r in results if not r.get("error") and r.get("record")]
    n = len(good)

    def rate(xs):
        xs = list(xs)
        return round(sum(xs) / len(xs), 4) if xs else None

    check_names = [k for k in checks.CHECK_LABELS]
    check_rates = {k: rate(r["checks"][k] for r in good if k in r["checks"]) for k in check_names}
    check_counts = {k: sum(1 for r in good if k in r["checks"]) for k in check_names}
    fill = {name: rate(r["record"]["fields"].get(name) is not None for r in good) for name, *_ in schema.FIELDS}
    converts = [r["seconds"]["convert"] for r in good if r.get("seconds", {}).get("convert") is not None]

    def group(key):
        groups: dict[str, list] = {}
        for r in good:
            d = docs.get(r["doc"]) or {}
            value = testset.split_of(r["doc"]) if key == "split" else d.get(key)
            groups.setdefault(value or "?", []).append(r)
        return {g: {"documents": len(rs), "ok_rate": rate(x["checks"]["ok"] for x in rs),
                    "lines_found": rate(bool(x["record"]["lines"]) for x in rs),
                    "lpo_number": rate(x["record"]["fields"]["lpo_number"] is not None for x in rs)}
                for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1]))}

    # against ground truth
    compared = []
    for r in good:
        t = truth.get(r["doc"])
        if t and not t.get("not_lpo"):
            compared.append(schema.compare(r["record"], t))
    field_acc = {}
    for name, *_ in schema.FIELDS:
        xs = [c["fields"][name] for c in compared if name in c["fields"]]
        field_acc[name] = {"right": sum(xs), "of": len(xs), "rate": rate(xs)}
    all_fields = [v for c in compared for v in c["fields"].values()]
    lines_true = sum(c["lines"]["true"] for c in compared)
    lines_pred = sum(c["lines"]["predicted"] for c in compared)
    lines_matched = sum(c["lines"]["matched"] for c in compared)
    nums_total = sum(c["lines"]["numbers_total"] for c in compared)
    accuracy = None
    if compared:
        accuracy = {
            "fields": rate(all_fields), "by_field": field_acc,
            "line_recall": round(lines_matched / lines_true, 4) if lines_true else None,
            "line_precision": round(lines_matched / lines_pred, 4) if lines_pred else None,
            "line_numbers": round(sum(c["lines"]["numbers_right"] for c in compared) / nums_total, 4) if nums_total else None,
        }
    return {
        "documents": len(results), "errors": len(results) - n,
        "ok_rate": check_rates["ok"], "checks": check_rates, "check_counts": check_counts,
        "fill": fill, "lines_found": rate(bool(r["record"]["lines"]) for r in good),
        "lines_from": {k: sum(1 for r in good if r.get("lines_from") == k) for k in ("tables", "text", "vlm", "none")},
        "seconds": {"convert_mean": round(sum(converts) / len(converts), 2) if converts else None, "converted": len(converts)},
        "labelled": len(compared), "accuracy": accuracy,
        "perfect_rate": rate(c["perfect"] for c in compared),
        "by_kind": group("kind"), "by_client": group("client"), "by_split": group("split"),
    }
