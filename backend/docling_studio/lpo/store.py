"""Where the LPO lab keeps things, under Studio's home (~/.docling-studio/lpo/):

    source.json             the bucket the test set is sampled from
    listing.tsv             that bucket's files: key, size, last modified (one row each)
    testset.json            the test set: one entry per document (see testset.py)
    files/<doc>.<ext>       the documents themselves
    labels/<doc>.json       ground truth saved from the review screen
    orient/<doc>.json       how each page of a scan has to be turned to stand upright
    pages/<doc>/<n>.png     page pictures for the review screen
    cache/<conv>/<doc>.json Docling's result for a document, per conversion settings (conv)
    experiments/<id>/       one experiment: experiment.json, progress.json, log.txt, results/
"""

import hashlib
import re
import threading
from pathlib import Path

from ..core.store import home, read_json, write_json

__all__ = ["root", "path", "doc_id", "read_json", "write_json", "safe_id", "PDFIUM"]

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# pdfium isn't thread-safe (two threads in it at once crash the process): every use in Studio's
# process (download threads, page pictures for concurrent requests) holds this.
PDFIUM = threading.Lock()


def root() -> Path:
    path = home() / "lpo"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def path(*parts: str) -> Path:
    return root().joinpath(*parts)


def doc_id(key: str) -> str:
    """A document's id: short and stable, from its key in the bucket."""
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def safe_id(value: str) -> str:
    """An id that came over HTTP, checked before it's used in a path."""
    if not SAFE_ID.match(value or ""):
        raise ValueError("Not a valid id.")
    return value
