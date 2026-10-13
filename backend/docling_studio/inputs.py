"""What a run reads: files you upload, files and folders on this computer, web addresses, and files
an earlier run made or read.

An input is a small dict, saved with the run so it can be run again:

    {"kind": "upload", "id": "<upload id>", "name": "paper.pdf"}   added in the browser
    {"kind": "path", "path": "/Users/me/Reports"}                   a file or folder on this computer
    {"kind": "url", "url": "https://arxiv.org/pdf/2206.01062"}      fetched by Docling
    {"kind": "run", "run": "<run id>", "file": "output/paper.json"} a file of an earlier run

Uploads wait in ~/.docling-studio/uploads/<id>/ until a run takes them into its input/ folder;
ones no run took are deleted after a day.
"""

import re
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from .core.store import home

UPLOAD_MAX_AGE = 24 * 3600


class InputError(Exception):
    pass


def uploads_dir() -> Path:
    return home() / "uploads"


def runs_dir() -> Path:
    return home() / "runs"


def safe_name(name: str) -> str:
    """A file name that's safe on every system: no folders, no control or reserved characters."""
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip(" .")
    return name[:180] or "document"


async def save_upload(name: str, stream) -> dict:
    uid = secrets.token_hex(8)
    folder = uploads_dir() / uid
    folder.mkdir(parents=True, mode=0o700)
    path = folder / safe_name(name)
    size = 0
    with open(path, "wb") as f:
        async for chunk in stream:
            f.write(chunk)
            size += len(chunk)
    return {"kind": "upload", "id": uid, "name": path.name, "size": size}


def _upload_path(item: dict) -> Path:
    uid = str(item.get("id", ""))
    if not re.fullmatch(r"[0-9a-f]{16}", uid):
        raise InputError("That upload isn't valid.")
    folder = uploads_dir() / uid
    files = [p for p in folder.iterdir()] if folder.is_dir() else []
    if len(files) != 1:
        raise InputError(f"The uploaded file {item.get('name', '')} is gone. Add it again.")
    return files[0]


def discard_upload(uid: str) -> None:
    if re.fullmatch(r"[0-9a-f]{16}", uid):
        shutil.rmtree(uploads_dir() / uid, ignore_errors=True)


def sweep_uploads() -> None:
    now = time.time()
    for folder in uploads_dir().glob("*") if uploads_dir().is_dir() else []:
        try:
            if now - folder.stat().st_mtime > UPLOAD_MAX_AGE:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def run_file(run_id: str, rel: str) -> Path:
    """A file inside a run's folder, refusing anything that would step outside it."""
    if not re.fullmatch(r"[0-9a-z-]{6,40}", run_id or ""):
        raise InputError("That run isn't valid.")
    root = (runs_dir() / run_id).resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise InputError(f"{rel} isn't a file of that run.")
    return path


def check(item: dict, allow: set[str]) -> dict:
    """An input as it will be saved: known kind, allowed for this field, and pointing at something."""
    kind = item.get("kind")
    if kind not in allow:
        raise InputError({"url": "A web address can't be used here.", "path": "A path can't be used here."}.get(kind, "That input isn't valid here."))
    if kind == "upload":
        path = _upload_path(item)
        return {"kind": "upload", "id": item["id"], "name": path.name, "size": path.stat().st_size}
    if kind == "path":
        raw = str(item.get("path", "")).strip()
        if not raw:
            raise InputError("Type the path of a file or folder.")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise InputError(f"{raw}: use the full path (starting with / or a drive letter).")
        if not path.exists():
            raise InputError(f"{raw} doesn't exist on this computer.")
        return {"kind": "path", "path": str(path.resolve()), "name": path.name, "folder": path.is_dir()}
    if kind == "url":
        url = str(item.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or any(c in url for c in "\n\r "):
            raise InputError(f"{url or 'That'} isn't a web address (http:// or https://).")
        return {"kind": "url", "url": url, "name": Path(parsed.path).name or parsed.netloc}
    path = run_file(str(item.get("run", "")), str(item.get("file", "")))
    return {"kind": "run", "run": item["run"], "file": item["file"], "name": path.name}


def materialize(item: dict, input_dir: Path) -> str:
    """What to give the CLI for a checked input, bringing uploads and earlier runs' files into the
    run's input/ folder (so it can be run again later, and the original can be deleted)."""
    if item["kind"] == "path":
        return item["path"]
    if item["kind"] == "url":
        return item["url"]
    input_dir.mkdir(parents=True, exist_ok=True)
    if item["kind"] == "upload":
        source = _upload_path(item)
        target = _free(input_dir / source.name)
        shutil.move(str(source), target)
        shutil.rmtree(source.parent, ignore_errors=True)
    else:
        source = run_file(item["run"], item["file"])
        target = _free(input_dir / source.name)
        shutil.copy2(source, target)
    return str(target)


def _free(path: Path) -> Path:
    """path, or path with " (2)" etc. when two inputs share a name."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise InputError(f"Too many inputs named {path.name}.")
