"""Reading a Docling JSON result for the run page: what's in it (pages, text by kind, tables,
pictures), its tables as rows, its pictures with what the enrichment models said about them, and
the same page `docling-view` would open (made with docling-serialize, kept in output/.studio/).

Only the JSON is read here, so the server never imports Docling itself.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .runs import STUDIO_DIR

MAX_JSON_BYTES = 400 * 1024 * 1024


class DocError(Exception):
    pass


def load(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise DocError("This document is too large to look inside here; download it instead.")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise DocError(f"{path.name} isn't valid JSON: {e}")
    if not isinstance(doc, dict) or doc.get("schema_name") != "DoclingDocument":
        raise DocError(f"{path.name} isn't a Docling document.")
    return doc


def _resolve(ref: str, doc: dict):
    """'#/texts/5' -> that item."""
    node = doc
    for part in ref.lstrip("#/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node.get(part)
        if node is None:
            return None
    return node


def _caption(item: dict, doc: dict) -> str:
    texts = []
    for cap in item.get("captions") or []:
        target = _resolve(cap.get("$ref", ""), doc) if isinstance(cap, dict) else None
        if target and target.get("text"):
            texts.append(target["text"])
    return " ".join(texts)


def _pages(item: dict) -> list[int]:
    return sorted({p.get("page_no") for p in item.get("prov") or [] if p.get("page_no")})


def summary(path: Path) -> dict:
    doc = load(path)
    labels = Counter(t.get("label", "text") for t in doc.get("texts", []))
    layers = Counter(t.get("content_layer", "body") for t in doc.get("texts", []))
    return {
        "name": doc.get("name"), "version": doc.get("version"), "origin": doc.get("origin") or {},
        "pages": len(doc.get("pages") or {}),
        "texts": len(doc.get("texts", [])), "labels": dict(labels.most_common()),
        "furniture": layers.get("furniture", 0),
        "tables": len(doc.get("tables", [])), "pictures": len(doc.get("pictures", [])),
        "key_value_items": len(doc.get("key_value_items", [])), "form_items": len(doc.get("form_items", [])),
        "groups": len(doc.get("groups", [])),
    }


def tables(path: Path) -> list[dict]:
    """Each table as rows of cell text (spanning cells repeated, as Docling's grid has them), with
    which rows and columns are headers."""
    doc = load(path)
    out = []
    for i, table in enumerate(doc.get("tables", [])):
        grid = (table.get("data") or {}).get("grid") or []
        rows = [[(cell or {}).get("text", "") for cell in row] for row in grid]
        header_rows = [r for r, row in enumerate(grid) if row and all((c or {}).get("column_header") for c in row)]
        out.append({"index": i, "ref": table.get("self_ref"), "label": table.get("label"), "pages": _pages(table),
                    "caption": _caption(table, doc), "rows": rows, "header_rows": header_rows,
                    "num_rows": (table.get("data") or {}).get("num_rows"), "num_cols": (table.get("data") or {}).get("num_cols")})
    return out


def _annotations(picture: dict) -> dict:
    """What the enrichment models said about a picture: its classes, a description, chart data…
    Older documents keep them in `annotations`, newer ones in `meta`."""
    found: dict = {"classes": [], "description": None, "other": []}
    for ann in picture.get("annotations") or []:
        kind = ann.get("kind")
        if kind == "classification":
            found["classes"] += [{"name": c.get("class_name"), "confidence": c.get("confidence")} for c in ann.get("predicted_classes", [])]
        elif kind == "description":
            found["description"] = ann.get("text")
        else:
            found["other"].append(ann)
    meta = picture.get("meta") or {}
    if isinstance(meta, dict):
        cls = meta.get("classification") or {}
        for c in cls.get("predictions", []) if isinstance(cls, dict) else []:
            found["classes"].append({"name": c.get("class_name"), "confidence": c.get("confidence")})
        desc = meta.get("description")
        if isinstance(desc, dict) and desc.get("text"):
            found["description"] = desc["text"]
        for key, value in meta.items():
            if key not in ("classification", "description") and value:
                found["other"].append({"kind": key, "value": value})
    return found


def pictures(path: Path, file_url) -> list[dict]:
    """Each picture with its image (file_url(path) -> a URL Studio serves, or None), caption and
    annotations."""
    doc = load(path)
    out = []
    for i, picture in enumerate(doc.get("pictures", [])):
        uri = ((picture.get("image") or {}).get("uri")) or ""
        src = uri if uri.startswith("data:") else None
        if uri and not src:
            for base in (path.parent, path.parent.parent):
                candidate = Path(uri) if Path(uri).is_absolute() else base / uri
                if candidate.is_file():
                    src = file_url(candidate)
                    break
        out.append({"index": i, "ref": picture.get("self_ref"), "label": picture.get("label"), "pages": _pages(picture),
                    "caption": _caption(picture, doc), "src": src, **_annotations(picture)})
    return out


def view(path: Path, output: Path, split: bool) -> Path:
    """The page `docling-view` would open for this document: HTML with each page's image next to
    its text when split. Made once and kept."""
    load(path)  # a clear message if it isn't a Docling document
    target = output / STUDIO_DIR / f"{path.stem}.{'split' if split else 'plain'}.html"
    if target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-X", "utf8", "-m", "docling_studio.runcli", "docling_core.cli.serialize",
            str(path), "--to", "html", "--output", str(target)]
    if split:
        args.append("--split-page-view")
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not target.is_file():
        raise DocError("docling-serialize couldn't make the page:\n" + (proc.stderr or proc.stdout)[-1500:])
    return target
