"""Named settings for a tool ("Scanned contracts: full-page OCR, German"), saved in presets.json.
Secrets are never kept: a preset with a PDF password asks for it again."""

import uuid
from datetime import datetime, timezone

from . import cli_schema
from .core.store import home, read_json, write_json


class PresetError(Exception):
    pass


def _path():
    return home() / "presets.json"


def list_presets(tool: str | None = None) -> list[dict]:
    items = read_json(_path(), [])
    return [p for p in items if tool is None or p["tool"] == tool]


def save(tool: str, name: str, values: dict, pid: str | None = None) -> dict:
    cli_schema.get_tool(tool)
    name = (name or "").strip()[:80]
    if not name:
        raise PresetError("Name the preset.")
    items = read_json(_path(), [])
    if any(p["tool"] == tool and p["name"].lower() == name.lower() and p["id"] != pid for p in items):
        raise PresetError(f"There's already a preset called {name}.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = next((p for p in items if p["id"] == pid), None) if pid else None
    if pid and not existing:
        raise PresetError("No such preset.")
    preset = {"id": pid or uuid.uuid4().hex[:10], "tool": tool, "name": name, "values": cli_schema.without_secrets(values),
              "created": existing["created"] if existing else now, "updated": now}
    items = [p for p in items if p["id"] != preset["id"]] + [preset]
    write_json(_path(), sorted(items, key=lambda p: (p["tool"], p["name"].lower())))
    return preset


def delete(pid: str) -> bool:
    items = read_json(_path(), [])
    kept = [p for p in items if p["id"] != pid]
    write_json(_path(), kept)
    return len(kept) != len(items)
