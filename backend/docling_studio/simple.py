"""The everyday converter: a few plain choices instead of Docling's 59 options, and finished files
(Word, Excel, Markdown, text, a web page) saved in the user's folder.

A job is a `docling convert` run (runs.py) with a "finish" step: when Docling is done, deliver()
makes the files the user asked for from its results and saves them in the save-to folder (Settings;
~/Documents/<app name> at first), named after each document. The run keeps a list of them, which is
what Open and Show in folder may open.
"""

import re
import shutil
from pathlib import Path

from . import brand, entitlements, exporters
from .core import settings

FORMATS = {
    "word": {"label": "Word document", "ext": ".docx", "docling": "json"},
    "excel": {"label": "Excel (tables)", "ext": ".xlsx", "docling": "json"},
    "markdown": {"label": "Markdown", "ext": ".md", "docling": "md"},
    "text": {"label": "Plain text", "ext": ".txt", "docling": "text"},
    "html": {"label": "Web page", "ext": ".html", "docling": "html"},
}
# OCR languages people pick most, as the BCP-47 tags Docling takes with "iso:".
LANGUAGES = {
    "": "Detect automatically", "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
    "tr": "Turkish", "ar": "Arabic", "hi": "Hindi", "zh-Hans": "Chinese (Simplified)", "zh-Hant": "Chinese (Traditional)",
    "ja": "Japanese", "ko": "Korean", "sw": "Swahili",
}
SCAN = {"auto": "Automatic", "always": "Always read the page images (for scans and photos)", "off": "Never (text-based PDFs only)"}
PAGES = re.compile(r"^\s*\d+\s*(-\s*\d+\s*)?$")


class JobError(Exception):
    pass


def default_folder() -> Path:
    return Path.home() / "Documents" / brand.NAME


def save_folder() -> Path:
    chosen = settings.get().get("save_to") or ""
    return Path(chosen).expanduser() if chosen else default_folder()


def options() -> dict:
    folder = save_folder()
    try:
        label = "~/" + folder.relative_to(Path.home()).as_posix()
    except ValueError:
        label = str(folder)
    return {"formats": {k: v["label"] for k, v in FORMATS.items()}, "languages": LANGUAGES, "scan": SCAN,
            "save_to": str(folder), "save_to_label": label, "plan": entitlements.plan()}


def build(request: dict) -> dict:
    """The run request for a job: {inputs, formats, scan, language, pages, pictures}."""
    items = request.get("inputs") or []
    formats = [f for f in request.get("formats") or [] if f in FORMATS]
    if not items:
        raise JobError("Add a document to convert.")
    if not formats:
        raise JobError("Choose what to save it as.")
    try:
        if len(items) > 1:
            entitlements.require("batch")
        if any(i.get("kind") == "path" and Path(str(i.get("path", ""))).expanduser().is_dir() for i in items):
            entitlements.require("folders")
        for f in formats:
            if f in entitlements.FEATURES:
                entitlements.require(f)
        if request.get("pictures") == "describe":
            entitlements.require("describe_pictures")
    except entitlements.NotAllowed as e:
        raise JobError(str(e))

    values: dict = {
        # always JSON too: Word and Excel are made from it, and the app previews it
        "to": sorted({FORMATS[f]["docling"] for f in formats} | {"json"}),
        "verbose": "1",
        "image_export_mode": "placeholder" if request.get("pictures") == "drop" else "embedded",
    }
    scan = request.get("scan") or "auto"
    if scan == "always":
        values["ocr_mode"] = "full_page"
    elif scan == "off":
        values["ocr"] = False
    elif scan != "auto":
        raise JobError("Unknown scan setting.")
    language = request.get("language") or ""
    if language:
        if language not in LANGUAGES:
            raise JobError("Unknown language.")
        values["ocr_lang"] = f"iso:{language}"
    pages = (request.get("pages") or "").strip()
    if pages:
        if not PAGES.match(pages):
            raise JobError("Pages are a number or a range, like 3 or 2-10.")
        values["page_range"] = pages.replace(" ", "") if "-" in pages else f"{pages.strip()}-{pages.strip()}"
    if request.get("pictures") == "describe":
        values["enrich_picture_description"] = True
    return {"tool": "convert", "values": values, "inputs": {"source": items},
            "finish": {"kind": "simple", "formats": formats, "folder": str(save_folder())}}


def _free(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise JobError(f"Too many files called {path.name} in {path.parent}.")


def deliver(finish: dict, output: Path, log) -> list[dict]:
    """Make the files a job asked for from Docling's results in output/, in the save-to folder.
    log(text) adds a line to the run's log."""
    folder = Path(finish["folder"])
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise JobError(f"Couldn't create {folder}: {e}")
    delivered = []
    for doc_json in sorted(output.glob("*.json")):
        if "-timings-" in doc_json.name:
            continue
        stem = doc_json.stem
        for fmt in finish["formats"]:
            spec = FORMATS[fmt]
            target = _free(folder / f"{stem}{spec['ext']}")
            try:
                if fmt == "word":
                    exporters.to_word(doc_json, target)
                elif fmt == "excel":
                    exporters.to_excel(doc_json, target)
                else:
                    source = output / f"{stem}{spec['ext']}"
                    if not source.is_file():
                        raise exporters.ExportError(f"Docling didn't make {source.name}.")
                    shutil.copy2(source, target)
            except exporters.ExportError as e:
                delivered.append({"document": stem, "format": fmt, "path": None, "note": str(e)})
                log(f"{brand.NAME}: {stem} as {spec['label']}: {e}")
                continue
            delivered.append({"document": stem, "format": fmt, "path": str(target), "size": target.stat().st_size, "note": None})
            log(f"{brand.NAME}: saved {target}")
    if not delivered:
        raise JobError("Docling didn't produce a document to save.")
    return delivered
