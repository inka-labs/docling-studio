"""The test set: real LPOs sampled from a bucket, kept on this computer.

The bucket's files sit in one folder per client (the supplier the LPOs are addressed to). Which
bucket is a setting (source.json, or LPO_BUCKET): it's never written into the code. A test set takes documents from every client that's switched on, more from big clients
but not in proportion (square root of their size, so small clients still show up), skipping
copies (same client, same size) and the bucket's own preprocessed page pictures.

Each document is downloaded to files/ and looked at once: page count, and whether its first page
has a text layer ("digital") or not ("scan"; photos are "image").
"""

import math
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import store

S3 = {"s": "http://doc.s3.amazonaws.com/2006-03-01"}
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
# Folders that look like testing, not a client: shown, but off unless switched on.
TESTISH = re.compile(r"(test|demo|train|trial|localdev|^app$|^erp$|^string$|^client_code$|^direct_uploads$|_upgrade$"
                     r"|^[a-z]+\d{3,}$|^\d+$|^[0-9a-f]{8}-[0-9a-f-]{27,}\s*$)", re.I)
DEFAULT_BUCKET = os.environ.get("LPO_BUCKET", "")  # set it in the lab (Test set → Bucket)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source() -> dict:
    return store.read_json(store.path("source.json"), {"bucket": DEFAULT_BUCKET, "listed": None, "clients_off": None})


def save_source(changes: dict) -> dict:
    current = source()
    if "bucket" in changes:
        bucket = str(changes["bucket"]).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", bucket):
            raise ValueError("That isn't a bucket name.")
        if bucket != current["bucket"]:
            current.update(bucket=bucket, listed=None)
    if "clients_off" in changes:
        current["clients_off"] = sorted({str(c) for c in changes["clients_off"] or []})
    store.write_json(store.path("source.json"), current)
    return current


def client_of(key: str) -> str:
    return key.split("/", 1)[0].strip().upper() if "/" in key else "(top level)"


def eligible(key: str) -> bool:
    """An original document, not one of the bucket's derived page pictures."""
    name = key.rsplit("/", 1)[-1].lower()
    return Path(name).suffix in EXTENSIONS and "processed" not in name and not name.startswith("tmp")


def listing() -> list[tuple[str, int, str]]:
    rows = []
    path = store.path("listing.tsv")
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[1].isdigit():
                rows.append((parts[0], int(parts[1]), parts[2]))
    return rows


def clients() -> list[dict]:
    """Every folder in the bucket: how many documents, and whether it's in the test set's draw."""
    off = source().get("clients_off")
    counts: dict[str, dict] = {}
    for key, size, modified in listing():
        if not eligible(key):
            continue
        c = counts.setdefault(client_of(key), {"name": client_of(key), "documents": 0, "newest": ""})
        c["documents"] += 1
        c["newest"] = max(c["newest"], modified)
    for c in counts.values():
        c["on"] = (c["name"] not in off) if off is not None else not TESTISH.search(c["name"])
    return sorted(counts.values(), key=lambda c: -c["documents"])


def load() -> dict:
    return store.read_json(store.path("testset.json"), {"docs": {}, "updated": None})


def save(testset: dict) -> None:
    testset["updated"] = _now()
    store.write_json(store.path("testset.json"), testset)


def split_of(doc_id: str) -> str:
    """Which part of the test set a document is in: "holdout" (a fifth, by its id) or "dev". Rules
    are worked out on dev documents only; holdout scores show whether a gain is real or just fits
    the documents we looked at. Fixed by the id, so it never moves as the set grows."""
    return "holdout" if int(doc_id[:8], 16) % 5 == 0 else "dev"


def active_docs(testset: dict | None = None) -> list[dict]:
    testset = testset or load()
    return [d for d in testset["docs"].values() if not d.get("excluded") and d.get("kind")]


def allocate(sizes: dict[str, int], total: int) -> dict[str, int]:
    """How many documents each client gives: in proportion to the square root of its size, at least
    a few each, never more than it has."""
    weights = {c: math.sqrt(n) for c, n in sizes.items() if n}
    share: dict[str, int] = {c: 0 for c in weights}
    left = total
    while left > 0 and weights:
        open_ = {c: w for c, w in weights.items() if share[c] < sizes[c]}
        if not open_:
            break
        mass = sum(open_.values())
        given = 0
        for c, w in sorted(open_.items(), key=lambda x: -x[1]):
            n = min(sizes[c] - share[c], max(1, round(left * w / mass)), left - given)
            share[c] += n
            given += n
            if given >= left:
                break
        left -= given
        if given == 0:
            break
    return share


def sample(target: int, seed: int = 7) -> list[tuple[str, int, str]]:
    """Bucket files to add so the test set holds `target` documents, picked per client."""
    testset = load()
    have_keys = {d["key"] for d in testset["docs"].values()}
    on = {c["name"] for c in clients() if c["on"]}
    pool: dict[str, list] = {}
    for row in listing():
        if eligible(row[0]) and client_of(row[0]) in on:
            pool.setdefault(client_of(row[0]), []).append(row)
    have = {c: sum(1 for d in testset["docs"].values() if d["client"] == c and not d.get("excluded")) for c in pool}
    want = allocate({c: len(rows) for c, rows in pool.items()}, target)
    rng = random.Random(seed)
    picked = []
    for client, rows in sorted(pool.items()):
        need = want.get(client, 0) - have.get(client, 0)
        if need <= 0:
            continue
        sizes = {d["size"] for d in testset["docs"].values() if d["client"] == client}
        rows = rows[:]
        rng.shuffle(rows)
        for key, size, modified in rows:
            if need <= 0:
                break
            if key in have_keys or size in sizes:
                continue
            sizes.add(size)
            picked.append((key, size, modified))
            need -= 1
    return picked


def inspect(path: Path) -> dict:
    """Pages and kind of a downloaded document."""
    if path.suffix.lower() != ".pdf":
        return {"pages": 1, "text_chars": 0, "kind": "image"}
    import pypdfium2 as pdfium

    with store.PDFIUM:
        pdf = pdfium.PdfDocument(path)
        try:
            chars = len(pdf[0].get_textpage().get_text_range().strip()) if len(pdf) else 0
            return {"pages": len(pdf), "text_chars": chars, "kind": "digital" if chars >= 40 else "scan"}
        finally:
            pdf.close()


def object_url(bucket: str, key: str) -> str:
    return f"https://storage.googleapis.com/{bucket}/{urllib.parse.quote(key, safe='/')}"


def download(bucket: str, key: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    part = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(object_url(bucket, key), timeout=120) as resp, open(part, "wb") as f:
        while chunk := resp.read(1 << 16):
            f.write(chunk)
    part.replace(target)


class Jobs:
    """The test set's background jobs (listing the bucket, building the set): one at a time, with
    progress the UI polls."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state: dict = {"job": None, "status": "idle", "done": 0, "total": 0, "message": "", "error": None}
        self._stop = threading.Event()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)

    def _set(self, **changes):
        with self._lock:
            self.state.update(changes)

    def busy(self) -> bool:
        return self.state["status"] == "running"

    def stop(self) -> None:
        self._stop.set()

    def _start(self, job: str, fn, *args) -> dict:
        with self._lock:
            if self.state["status"] == "running":
                raise RuntimeError(f"Wait for the {self.state['job']} to finish first.")
            self.state = {"job": job, "status": "running", "done": 0, "total": 0, "message": "Starting…", "error": None,
                          "started": _now()}
        self._stop.clear()

        def run():
            try:
                fn(*args)
                self._set(status="idle" if not self._stop.is_set() else "stopped", ended=_now())
            except Exception as e:  # shown to the user as the job's error
                self._set(status="failed", error=f"{type(e).__name__}: {e}", ended=_now())

        threading.Thread(target=run, name=f"lpo-{job}", daemon=True).start()
        return self.snapshot()

    # Listing the bucket -------------------------------------------------------------------------

    def refresh_listing(self) -> dict:
        bucket = source()["bucket"]
        if not bucket:
            raise RuntimeError("Set the bucket to sample LPOs from first.")
        return self._start("listing", self._list, bucket)

    def _list(self, bucket: str) -> None:
        part = store.path("listing.tsv.part")
        marker, pages, count = "", 0, 0
        with open(part, "w") as f:
            while not self._stop.is_set():
                url = f"https://storage.googleapis.com/{bucket}?marker={urllib.parse.quote(marker)}"
                try:
                    with urllib.request.urlopen(url, timeout=60) as resp:
                        root = ET.fromstring(resp.read())
                except urllib.error.HTTPError as e:
                    raise RuntimeError(f"The bucket refused the listing ({e.code}). If it's private now, "
                                       "listing it needs credentials, which the lab doesn't do yet.") from None
                for c in root.findall("s:Contents", S3):
                    f.write(f"{c.findtext('s:Key', namespaces=S3)}\t{c.findtext('s:Size', namespaces=S3)}\t"
                            f"{c.findtext('s:LastModified', namespaces=S3)}\n")
                    count += 1
                pages += 1
                self._set(done=count, message=f"{count:,} files listed")
                if root.findtext("s:IsTruncated", namespaces=S3) != "true":
                    break
                marker = root.findtext("s:NextMarker", namespaces=S3) or ""
        if self._stop.is_set():
            part.unlink(missing_ok=True)
            return
        part.replace(store.path("listing.tsv"))
        src = source()
        src["listed"] = _now()
        store.write_json(store.path("source.json"), src)
        self._set(message=f"{count:,} files in the bucket")

    # Surveying the bucket's layouts (survey.py) --------------------------------------------------

    def survey(self, per_client: int) -> dict:
        from . import survey

        if not listing():
            raise RuntimeError("List the bucket first.")
        if not 1 <= per_client <= 5000:
            raise ValueError("Survey 1 to 5,000 documents per folder.")
        return self._start("survey", survey.run, self, per_client)

    # Building the test set ----------------------------------------------------------------------

    def build(self, target: int, seed: int = 7) -> dict:
        if not listing():
            raise RuntimeError("List the bucket first.")
        if not 1 <= target <= 20000:
            raise ValueError("The test set can hold 1 to 20,000 documents.")
        return self._start("build", self._build, target, seed)

    def _build(self, target: int, seed: int) -> None:
        bucket = source()["bucket"]
        picked = sample(target, seed)
        self._set(total=len(picked), message=f"Downloading {len(picked)} documents")
        testset = load()
        lock = threading.Lock()
        failures: list[str] = []

        def fetch(row):
            if self._stop.is_set():
                return
            key, size, modified = row
            did = store.doc_id(key)
            ext = Path(key).suffix.lower()
            target_path = store.path("files", did + ext)
            entry = {"id": did, "key": key, "client": client_of(key), "size": size, "modified": modified,
                     "file": did + ext, "added": _now(), "excluded": False}
            try:
                if not target_path.exists():
                    download(bucket, key, target_path)
                entry.update(inspect(target_path))
            except Exception as e:
                failures.append(f"{key}: {e}")
                target_path.unlink(missing_ok=True)
                return
            with lock:
                testset["docs"][did] = entry
                self.state["done"] += 1
                if self.state["done"] % 25 == 0:
                    save(testset)

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(fetch, picked))
        save(testset)
        n = len(active_docs(testset))
        msg = f"Test set: {n:,} documents"
        if failures:
            msg += f" ({len(failures)} couldn't be downloaded: {failures[0]})"
        self._set(message=msg)


def summary(testset: dict | None = None) -> dict:
    testset = testset or load()
    docs = active_docs(testset)
    by_client: dict[str, dict] = {}
    for d in docs:
        c = by_client.setdefault(d["client"], {"name": d["client"], "documents": 0, "digital": 0, "scan": 0, "image": 0})
        c["documents"] += 1
        c[d["kind"]] = c.get(d["kind"], 0) + 1
    labelled = {p.stem for p in store.path("labels").glob("*.json")} if store.path("labels").exists() else set()
    return {
        "documents": len(docs),
        "holdout": sum(1 for d in docs if split_of(d["id"]) == "holdout"),
        "labelled_holdout": sum(1 for d in docs if d["id"] in labelled and split_of(d["id"]) == "holdout"),
        "excluded": sum(1 for d in testset["docs"].values() if d.get("excluded")),
        "kinds": {k: sum(1 for d in docs if d["kind"] == k) for k in ("digital", "scan", "image")},
        "pages": sum(d.get("pages") or 0 for d in docs),
        "labelled": sum(1 for d in docs if d["id"] in labelled),
        "clients": sorted(by_client.values(), key=lambda c: -c["documents"]),
        "updated": testset.get("updated"),
    }


def wait(jobs: Jobs, timeout: float = 30) -> dict:
    """For tests: the job's state once it has finished."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and jobs.busy():
        time.sleep(0.05)
    return jobs.snapshot()
