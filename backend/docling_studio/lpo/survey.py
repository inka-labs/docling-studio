"""Surveying the bucket for layouts the test set doesn't cover.

Downloading the whole bucket isn't practical (hundreds of thousands of files), so the survey takes
a sample per client folder, fingerprints each document's first page, keeps a small thumbnail and
the fingerprint, and deletes the download. Documents are then grouped by layout, test-set documents
included, so each group shows how common a layout is in the bucket and how many test-set documents
have it. A layout that's common in the bucket but thin in the test set is worth adding.

Fingerprints:
- digital PDFs: the words in the top third of the first page (the buyer's name and the labels of
  its template: "Purchase order", "Ship To", "P.O. Date"), without numbers;
- every page also gets a visual difference hash of the first page (how dark each spot is compared
  with its neighbour, on a 16 x 24 grid), which is all a scan has.

Two documents have the same layout if their header words mostly match (digital), or else if their
visual hashes are close.
"""

import random
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import store, testset

THUMB_WIDTH = 220
OCR_WIDTH = 1200      # first page rendered this wide: enough to OCR a scan's header
WORDS_SAME = 0.5      # Jaccard of template words
MIN_WORDS = 4         # fewer template words than this: compare pictures instead
PICTURE_SAME = 0.12   # share of visual-hash bits that differ
OCR_LOCK = threading.Lock()


def _path(*parts: str) -> Path:
    return store.path("survey", *parts)


def load() -> dict:
    return store.read_json(_path("survey.json"), {"docs": {}, "updated": None})


def fingerprint(path: Path, did: str) -> dict:
    """Header words, visual hash and a thumbnail (saved to survey/thumbs/<did>.jpg) of page 1."""
    import re

    import numpy as np
    from PIL import Image, ImageOps

    words: list[str] = []
    kind = "image"
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        with store.PDFIUM:
            pdf = pdfium.PdfDocument(path)
            try:
                page = pdf[0]
                w, h = page.get_size()
                text = page.get_textpage()
                chars = len(text.get_text_range().strip())
                kind = "digital" if chars >= 40 else "scan"
                if kind == "digital":
                    head = text.get_text_bounded(left=0, bottom=h * 0.66, right=w, top=h)
                    words = sorted({x.upper() for x in re.findall(r"[A-Za-z]{3,}", head)})
                img = page.render(scale=OCR_WIDTH / max(w, 1)).to_pil()
                pages = len(pdf)
            finally:
                pdf.close()
    else:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
            img.thumbnail((OCR_WIDTH, OCR_WIDTH * 2))
        pages = 1
    if kind != "digital":
        words = _header_words(img)
    gray = img.convert("L")
    thumb = gray.copy()
    thumb.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
    _path("thumbs").mkdir(parents=True, exist_ok=True, mode=0o700)
    thumb.save(_path("thumbs", did + ".jpg"), quality=70)
    a = np.asarray(gray.resize((17, 25)), dtype=np.int16)
    bits = np.concatenate([(a[:, 1:] > a[:, :-1]).ravel(), (a[1:, :] > a[:-1, :]).ravel()])
    return {"kind": kind, "pages": pages, "words": words, "hash": np.packbits(bits).tobytes().hex()}


def _header_words(img) -> list[str]:
    """A scan's header words, by OCR of the top third of its first page."""
    import re

    import numpy as np

    from .orient import _ocr

    top = img.convert("RGB").crop((0, 0, img.width, int(img.height * 0.34)))
    with OCR_LOCK:  # one engine, shared by the download threads
        out = _ocr()(np.asarray(top), use_det=True, use_cls=False, use_rec=True)
    text = " ".join(t for t, s in zip(out.txts or (), out.scores or ()) if s >= 0.6)
    return sorted({x.upper() for x in re.findall(r"[A-Za-z]{3,}", text)})


def _hash_distance(a: str, b: str) -> float:
    x = int(a, 16) ^ int(b, 16)
    return bin(x).count("1") / (len(a) * 4)


MONTHS = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC", "JANUARY",
          "FEBRUARY", "MARCH", "APRIL", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"}


def template_words(items: list[dict]) -> set[str]:
    """Words that recur across documents: a template's labels and its buyer's name, not a store,
    a person or a date, which vary from one document to the next."""
    df: dict[str, int] = {}
    for it in items:
        for w in it["words"]:
            df[w] = df.get(w, 0) + 1
    floor = max(3, int(0.01 * len(items)))
    return {w for w, n in df.items() if n >= floor and w not in MONTHS}


def same_layout(a: dict, b: dict) -> bool:
    """Same template words, mostly; or, when either has too few readable words (a sideways scan),
    pictures that look alike."""
    sa, sb = a["tw"], b["tw"]
    if len(sa) >= MIN_WORDS and len(sb) >= MIN_WORDS:
        return len(sa & sb) / len(sa | sb) >= WORDS_SAME
    if len(sa) >= MIN_WORDS or len(sb) >= MIN_WORDS:
        return False
    return _hash_distance(a["hash"], b["hash"]) <= PICTURE_SAME


def run(jobs: "testset.Jobs", per_client: int, seed: int = 11) -> None:
    """Sample up to per_client documents from each switched-on client folder (not already in the
    test set or surveyed), fingerprint them, and fingerprint test-set documents not done yet."""
    survey = load()
    in_set = testset.load()["docs"]
    known = {d["key"] for d in in_set.values()} | {d["key"] for d in survey["docs"].values()}
    on = {c["name"] for c in testset.clients() if c["on"]}
    pool: dict[str, list] = {}
    for row in testset.listing():
        if testset.eligible(row[0]) and testset.client_of(row[0]) in on and row[0] not in known:
            pool.setdefault(testset.client_of(row[0]), []).append(row)
    rng = random.Random(seed)
    picked = []
    for client, rows in sorted(pool.items()):
        have = sum(1 for d in survey["docs"].values() if d["client"] == client)
        rows = rows[:]
        rng.shuffle(rows)
        sizes = set()
        for key, size, modified in rows:
            if have >= per_client:
                break
            if size in sizes:
                continue
            sizes.add(size)
            picked.append((key, size, modified))
            have += 1
    todo_set = [d for d in testset.active_docs() if d["id"] not in survey.get("testset", {})]
    jobs._set(total=len(picked) + len(todo_set), done=0, message=f"Surveying {len(picked):,} documents from the bucket")
    lock = threading.Lock()
    bucket = testset.source()["bucket"]
    tmp = _path("tmp")
    tmp.mkdir(parents=True, exist_ok=True, mode=0o700)
    failures = []

    def one(row):
        if jobs._stop.is_set():
            return
        key, size, modified = row
        did = store.doc_id(key)
        target = tmp / (did + Path(key).suffix.lower())
        try:
            testset.download(bucket, key, target)
            fp = fingerprint(target, did)
        except Exception as e:
            failures.append(f"{key}: {e}")
            return
        finally:
            target.unlink(missing_ok=True)
        with lock:
            survey["docs"][did] = {"id": did, "key": key, "client": testset.client_of(key), "size": size,
                                   "modified": modified, **fp}
            jobs.state["done"] += 1
            if jobs.state["done"] % 50 == 0:
                _save(survey)

    with ThreadPoolExecutor(max_workers=6) as pool_:
        list(pool_.map(one, picked))
    # the test set's own documents, already on disk
    prints = survey.setdefault("testset", {})
    for d in todo_set:
        if jobs._stop.is_set():
            break
        try:
            prints[d["id"]] = fingerprint(store.path("files", d["file"]), d["id"])
        except Exception as e:
            failures.append(f"{d['key']}: {e}")
        jobs.state["done"] += 1
    _save(survey)
    msg = f"Surveyed {len(survey['docs']):,} bucket documents"
    if failures:
        msg += f" ({len(failures)} couldn't be read)"
    jobs._set(message=msg)


def _save(survey: dict) -> None:
    survey["updated"] = testset._now()
    store.write_json(_path("survey.json"), survey)


def layouts() -> dict:
    """Groups of documents with the same layout, biggest first: how many surveyed, how many in the
    test set, from which clients, a few examples."""
    survey = load()
    ts = {d["id"]: d for d in testset.active_docs()}
    items = []
    for d in survey["docs"].values():
        if d["id"] not in ts:
            items.append({**d, "in_set": False})
    for did, fp in (survey.get("testset") or {}).items():
        if did in ts:
            items.append({**fp, "id": did, "key": ts[did]["key"], "client": ts[did]["client"], "in_set": True})
    items.sort(key=lambda x: x["id"])
    common = template_words(items)
    for it in items:
        it["tw"] = set(it["words"]) & common
    groups: list[dict] = []
    for item in items:
        for g in groups:
            if same_layout(g["leader"], item):
                g["members"].append(item)
                break
        else:
            groups.append({"leader": item, "members": [item]})
    out = []
    for g in groups:
        members = g["members"]
        surveyed = [m for m in members if not m["in_set"]]
        in_set = [m for m in members if m["in_set"]]
        clients: dict[str, int] = {}
        for m in members:
            clients[m["client"]] = clients.get(m["client"], 0) + 1
        examples = (in_set[:2] + surveyed[:4])[:5]
        kinds: dict[str, int] = {}
        for m in members:
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
        out.append({
            "id": g["leader"]["id"], "kind": g["leader"]["kind"], "kinds": kinds, "words": sorted(g["leader"]["tw"])[:16],
            "surveyed": len(surveyed), "in_set": len(in_set),
            "clients": dict(sorted(clients.items(), key=lambda kv: -kv[1])),
            "examples": [{"id": m["id"], "in_set": m["in_set"], "key": m["key"]} for m in examples],
            "addable": [m["id"] for m in surveyed],
        })
    n_survey = sum(g["surveyed"] for g in out) or 1
    n_set = sum(g["in_set"] for g in out) or 1
    for g in out:
        # a layout is under-covered when its share of the test set is well below its share of the survey
        g["gap"] = g["surveyed"] >= 3 and g["in_set"] / n_set < 0.5 * g["surveyed"] / n_survey
    out.sort(key=lambda g: (-g["gap"], -g["surveyed"], -g["in_set"]))
    return {"layouts": out, "surveyed": len(survey["docs"]), "fingerprinted": len(survey.get("testset") or {}),
            "updated": survey.get("updated")}


def add_to_testset(layout_id: str, count: int) -> list[str]:
    """Download `count` surveyed documents of one layout (spread over its clients) into the test set."""
    group = next((g for g in layouts()["layouts"] if g["id"] == layout_id), None)
    if not group:
        raise ValueError("No such layout (the survey may have changed): reload.")
    survey = load()
    candidates = [survey["docs"][i] for i in group["addable"] if i in survey["docs"]]
    by_client: dict[str, list] = {}
    for c in candidates:
        by_client.setdefault(c["client"], []).append(c)
    chosen = []
    while len(chosen) < count and any(by_client.values()):
        for rows in by_client.values():
            if rows and len(chosen) < count:
                chosen.append(rows.pop(0))
    bucket = testset.source()["bucket"]
    ts = testset.load()
    added = []
    for c in chosen:
        ext = Path(c["key"]).suffix.lower()
        target = store.path("files", c["id"] + ext)
        if not target.exists():
            testset.download(bucket, c["key"], target)
        entry = {"id": c["id"], "key": c["key"], "client": c["client"], "size": c["size"], "modified": c["modified"],
                 "file": c["id"] + ext, "added": testset._now(), "excluded": False, "from_layout": layout_id,
                 **testset.inspect(target)}
        ts["docs"][c["id"]] = entry
        survey.setdefault("testset", {})[c["id"]] = {k: c[k] for k in ("kind", "pages", "words", "hash")}
        added.append(c["id"])
    testset.save(ts)
    _save(survey)
    return added
