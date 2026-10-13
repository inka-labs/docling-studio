"""Saved docling-serve services, for `docling convert-remote`.

A service is a name and a URL (services.json); its API key, if it has one, is kept in the system
keychain (macOS Keychain, Windows Credential Manager, Secret Service on Linux) under the service
"docling-studio". A run gets them as DOCLING_SERVICE_URL / DOCLING_SERVICE_API_KEY, which the CLI
reads, so the key is never on a command line, in a file or in the browser.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import keyring
import keyring.errors

from .core.store import home, read_json, write_json

KEYCHAIN_SERVICE = "docling-studio"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}")


class ServiceError(Exception):
    pass


def _path():
    return home() / "services.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _account(name: str) -> str:
    return f"service:{name}"


def _key(name: str) -> str | None:
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, _account(name))
    except keyring.errors.KeyringError:
        return None


def list_services() -> list[dict]:
    return [{**s, "has_key": bool(_key(s["name"]))} for s in read_json(_path(), [])]


def get(name: str) -> dict | None:
    return next((s for s in list_services() if s["name"] == name), None)


def _check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ServiceError("The URL must start with http:// or https://, e.g. http://localhost:5001")
    return url


def save(name: str, url: str, api_key: str | None, original: str | None = None) -> dict:
    """Add a service, or change one (original: its current name). api_key None keeps the saved key,
    "" removes it."""
    name = (name or "").strip()
    if not NAME.fullmatch(name):
        raise ServiceError("Name it with letters, numbers, spaces, dots, dashes or underscores (up to 60).")
    url = _check_url(url)
    items = read_json(_path(), [])
    if original and not any(s["name"] == original for s in items):
        raise ServiceError(f"There's no service called {original}.")
    if name != original and any(s["name"] == name for s in items):
        raise ServiceError(f"There's already a service called {name}.")
    old_key = _key(original) if original else None
    try:
        new_key = old_key if api_key is None else api_key.strip()
        if original and original != name and old_key:
            keyring.delete_password(KEYCHAIN_SERVICE, _account(original))
        if new_key:
            keyring.set_password(KEYCHAIN_SERVICE, _account(name), new_key)
        elif _key(name):
            keyring.delete_password(KEYCHAIN_SERVICE, _account(name))
    except keyring.errors.KeyringError as e:
        raise ServiceError(f"The system keychain refused the API key: {e}")
    previous = next((s for s in items if s["name"] == original), None)
    record = {"name": name, "url": url, "created": previous["created"] if previous else _now(), "updated": _now()}
    items = [s for s in items if s["name"] != original] + [record]
    write_json(_path(), sorted(items, key=lambda s: s["name"].lower()))
    return get(name)


def delete(name: str) -> bool:
    items = read_json(_path(), [])
    if not any(s["name"] == name for s in items):
        return False
    try:
        if _key(name):
            keyring.delete_password(KEYCHAIN_SERVICE, _account(name))
    except keyring.errors.KeyringError:
        pass
    write_json(_path(), [s for s in items if s["name"] != name])
    return True


def env_for(name: str) -> tuple[dict, list[str]]:
    """The variables a run against this service gets, and the secrets to blank out of its log."""
    service = get(name)
    if not service:
        raise ServiceError(f"There's no saved service called {name}. Add it under Services.")
    env = {"DOCLING_SERVICE_URL": service["url"]}
    key = _key(name)
    if key:
        env["DOCLING_SERVICE_API_KEY"] = key
    return env, [key] if key else []


def check(name: str) -> dict:
    """Whether the service answers (docling-serve's /health), and with which version."""
    service = get(name)
    if not service:
        raise ServiceError(f"There's no service called {name}.")
    headers = {"X-Api-Key": key} if (key := _key(name)) else {}
    try:
        resp = httpx.get(service["url"] + "/health", headers=headers, timeout=10, follow_redirects=True)
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"No answer from {service['url']}: {e}"}
    if resp.status_code in (401, 403):
        return {"ok": False, "message": "The service refused the API key."}
    if resp.status_code != 200:
        return {"ok": False, "message": f"The service answered {resp.status_code}."}
    version = None
    try:
        version = httpx.get(service["url"] + "/version", headers=headers, timeout=10).json()
    except (httpx.HTTPError, ValueError):
        pass
    return {"ok": True, "message": "The service is up.", "version": version}
