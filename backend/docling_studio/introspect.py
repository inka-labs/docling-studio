"""Read the Docling CLIs' options, as JSON on stdout. Run in a subprocess (cli_schema.py) so the
server never imports Docling (and torch) itself:

    python -m docling_studio.introspect

Each CLI is a Typer app; this walks its commands and describes every parameter: its flags, type,
choices, default and help. Newer Typer bundles its own copy of click, so commands and types are
recognised by what they have (list_commands, choices), not by their class.
"""

import importlib
import json
import sys
from importlib.metadata import PackageNotFoundError, version

# The CLIs, by the module holding each Typer app (the console scripts' entry points).
APPS = {
    "docling": "docling.cli.main",
    "docling-tools": "docling.cli.tools",
    "docling-serialize": "docling_core.cli.serialize",
    "docling-view": "docling_core.cli.view",
    "doclang": "doclang.cli",
}
PACKAGES = ["docling", "docling-slim", "docling-core", "docling-parse", "docling-ibm-models", "torch", "transformers",
            "easyocr", "rapidocr", "onnxruntime", "ocrmac", "tesserocr", "mlx-vlm", "openai-whisper", "playwright"]


def _type(param) -> dict:
    t = param.type
    name = type(t).__name__.lower()
    out: dict = {}
    if hasattr(t, "choices"):
        out["type"] = "choice"
        out["choices"] = [str(getattr(c, "value", c)) for c in t.choices]
    elif getattr(param, "is_flag", False) or "bool" in name:
        out["type"] = "bool"
    elif "int" in name:
        out["type"] = "int"
    elif "float" in name:
        out["type"] = "float"
    elif "path" in name or "file" in name:
        out["type"] = "path"
    else:
        out["type"] = "string"
    for bound in ("min", "max"):
        if getattr(t, bound, None) is not None:
            out[bound] = getattr(t, bound)
    return out


def _default(param):
    value = param.default
    if callable(value):
        return None
    if isinstance(value, (list, tuple)):
        return [str(getattr(v, "value", v)) for v in value]
    value = getattr(value, "value", value)  # an Enum member
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)  # a Path


def key(param, kind: str) -> str:
    """An option's name as you'd know it: its long flag (--chunks-type -> chunks_type), not the
    Python name behind it (chunker_type). An argument keeps its own name."""
    if kind == "option":
        long = next((o for o in param.opts if o.startswith("--")), None)
        if long:
            return long[2:].replace("-", "_")
    return param.name


def describe(param) -> dict:
    kind = "argument" if type(param).__name__.endswith("Argument") else "option"
    return {
        "name": key(param, kind),
        "dest": param.name,
        "kind": kind,
        "opts": list(param.opts),
        "secondary_opts": list(getattr(param, "secondary_opts", []) or []),
        "is_flag": bool(getattr(param, "is_flag", False)),
        "count": bool(getattr(param, "count", False)),
        "multiple": bool(getattr(param, "multiple", False)) or (kind == "argument" and param.nargs == -1),
        "required": bool(param.required),
        "default": _default(param),
        "help": getattr(param, "help", None) or "",
        "hidden": bool(getattr(param, "hidden", False)),
        "panel": getattr(param, "rich_help_panel", None),
        **_type(param),
    }


def _walk(cmd, path: list[str]) -> list[dict]:
    if hasattr(cmd, "list_commands"):  # a group
        ctx = type(cmd).context_class(cmd)
        found = []
        for name in cmd.list_commands(ctx):
            sub = cmd.get_command(ctx, name)
            if sub is not None and not getattr(sub, "hidden", False):
                found += _walk(sub, path + [name])
        return found
    return [{"path": path, "help": (cmd.help or "").strip(), "params": [describe(p) for p in cmd.params]}]


def collect() -> dict:
    import typer

    commands, errors = {}, {}
    for program, module in APPS.items():
        try:
            app = importlib.import_module(module).app
            for command in _walk(typer.main.get_command(app), []):
                commands[" ".join([program, *command["path"]])] = {"program": program, "module": module, **command}
        except Exception as e:  # noqa: BLE001 - one CLI that won't load mustn't hide the others
            errors[program] = f"{type(e).__name__}: {e}"
    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            pass
    return {"commands": commands, "errors": errors, "versions": versions, "devices": _devices()}


def _devices() -> list[str]:
    """Accelerators torch can use here (what --device auto picks from)."""
    found = ["cpu"]
    try:
        import torch

        if torch.cuda.is_available():
            found.append("cuda")
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            found.append("mps")
        if getattr(torch, "xpu", None) and torch.xpu.is_available():
            found.append("xpu")
    except Exception:  # noqa: BLE001
        pass
    return found


if __name__ == "__main__":
    json.dump(collect(), sys.stdout)
