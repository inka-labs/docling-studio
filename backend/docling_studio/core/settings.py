"""Studio's own preferences (settings.json)."""

from .store import home, read_json, write_json

DEFAULTS = {
    # Conversions load large models; two at once on a laptop mostly makes both slow.
    "max_parallel_runs": 1,
    # -v: Docling's info log, so a run's log shows what it's doing (it's silent by default).
    "default_verbosity": 1,
    # Finished runs older than this many days are deleted at start-up (0: keep everything).
    "keep_runs_days": 0,
    # where finished files are saved ("" = ~/Documents/<app name>; simple.py)
    "save_to": "",
}
LIMITS = {"max_parallel_runs": (1, 8), "default_verbosity": (0, 2), "keep_runs_days": (0, 3650)}


def get() -> dict:
    return {**DEFAULTS, **read_json(home() / "settings.json", {})}


def update(changes: dict) -> dict:
    current = get()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown setting: {key}")
        if isinstance(DEFAULTS[key], str):
            if not isinstance(value, str) or "\n" in value:
                raise ValueError(f"{key} must be text.")
            current[key] = value.strip()
            continue
        low, high = LIMITS[key]
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError(f"{key} must be a whole number from {low} to {high}.")
        current[key] = value
    write_json(home() / "settings.json", current)
    return current
