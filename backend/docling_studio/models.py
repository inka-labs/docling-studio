"""The models on this computer: what Docling has downloaded (its models folder, and the Hugging
Face cache, where most models go on first use), their sizes, and removing one to free space.
Downloading is a run of `docling-tools models download` (cli_schema.py).
"""

import os
import shutil
from pathlib import Path

DOCLING_HINTS = ("docling", "granite", "smoldocling", "smolvlm", "tableformer", "layout", "minilm", "whisper",
                 "easyocr", "rapidocr", "ocr")


class ModelError(Exception):
    pass


def docling_models_dir() -> Path:
    """Where `docling-tools models download` puts models by default (and --artifacts-path reads):
    the default of its --output-dir, as Docling reports it."""
    from . import cli_schema

    try:
        params = cli_schema.command_params(cli_schema.get_tool("models"))
        if params.get("output_dir", {}).get("default"):
            return Path(params["output_dir"]["default"])
    except cli_schema.SchemaError:
        pass
    return Path.home() / ".cache" / "docling" / "models"


def hf_hub_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    hf_home = os.environ.get("HF_HOME") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huggingface"
    return Path(hf_home) / "hub"


def _size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def roots() -> dict[str, Path]:
    return {"docling": docling_models_dir(), "huggingface": hf_hub_dir()}


def list_models() -> dict:
    found = []
    for where, root in roots().items():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if where == "huggingface":
                if not entry.name.startswith(("models--", "datasets--")):
                    continue
                name = entry.name.split("--", 1)[1].replace("--", "/")
            else:
                name = entry.name
            found.append({"where": where, "name": name, "folder": entry.name, "path": str(entry),
                          "size": _size(entry), "docling": where == "docling" or any(h in name.lower() for h in DOCLING_HINTS)})
    return {"models": found, "roots": {k: str(v) for k, v in roots().items()},
            "total": sum(m["size"] for m in found)}


def delete(where: str, folder: str) -> None:
    root = roots().get(where)
    if not root:
        raise ModelError("Unknown models folder.")
    target = (root / folder).resolve()
    if target.parent != root.resolve() or not target.is_dir() or folder.startswith("."):
        raise ModelError("That isn't a model folder.")
    shutil.rmtree(target)
