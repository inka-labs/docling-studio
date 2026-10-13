"""Where Studio keeps its state: ~/.docling-studio (override with DOCLING_STUDIO_HOME).

Nothing in here is secret: docling-serve API keys live in the OS keychain (services.py), and PDF
passwords and request headers are never written down. Files are still written owner-only, since
document names and paths are private to the user.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def home() -> Path:
    path = Path(os.environ.get("DOCLING_STUDIO_HOME") or Path.home() / ".docling-studio")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
