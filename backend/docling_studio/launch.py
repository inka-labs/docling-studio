"""Open Studio without a terminal: start it in the background if it isn't running, then open it in
the browser, signed in. This is what the Docling Studio app (macOS) and the Start-menu shortcut
(Windows) run; see packaging/.

    python -m docling_studio.launch           # open Studio (starting it if needed)
    python -m docling_studio.launch --stop    # ask a running Studio to quit (the installers do, before updating)

Installed by the installers, Studio lives in one folder: app/ (this code and its pixi environment)
next to bin/ (the pixi that installed it).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .core.store import home

PORT = int(os.environ.get("DOCLING_STUDIO_PORT") or 8766)  # Ecoscope Studio has 8765; another port if 8766 is taken
COOKIE = "docling_studio_session"  # app.COOKIE (not imported: that would load the whole server)
APP_DIR = Path(__file__).resolve().parents[2]
BUNDLED_BIN = APP_DIR.parent / "bin"  # where the installers put pixi


def bundled() -> bool:
    """Installed with the installers (rather than run from a clone with `pixi run start`)."""
    return (BUNDLED_BIN / ("pixi.exe" if os.name == "nt" else "pixi")).is_file()


def prepare_path() -> None:
    """Put the installers' pixi and Studio's own environment on PATH, for a Studio that wasn't
    started from a pixi shell (the app, a shortcut, start at login)."""
    prefix = Path(sys.prefix)
    own = [prefix, prefix / "Library" / "bin", prefix / "Library" / "cmd", prefix / "Scripts"] if os.name == "nt" else [prefix / "bin"]
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    add = [str(p) for p in [BUNDLED_BIN, *own] if p.is_dir() and str(p) not in current]
    if add:
        os.environ["PATH"] = os.pathsep.join(add + current)


def _token() -> str:
    try:
        return (home() / "session_token").read_text().strip()
    except OSError:
        return ""


def _call(path: str, method: str = "GET", port: int = PORT, timeout: float = 2) -> tuple[int, dict] | None:
    """(status, JSON body) from whatever answers on the port, or None when nothing does."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 headers={"Cookie": f"{COOKIE}={_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (OSError, ValueError):
        return None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def running(port: int = PORT) -> str | None:
    """"studio" when this computer's Studio answers on the port, "other" when another program
    does, None when nothing does."""
    answer = _call("/api/version", port=port)
    if answer is None:
        return None
    status, body = answer
    signed_out = status == 401 and str(body.get("detail", "")).startswith("Not signed in")  # a Studio, another token
    return "studio" if (status == 200 and "version" in body) or signed_out else "other"


def _python(background: bool) -> str:
    """This environment's Python; pythonw on Windows for a process without a console window."""
    if background and os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return sys.executable


def server_command(port: int = PORT) -> list[str]:
    # -X utf8: read and write text as UTF-8 on Windows too, as on macOS and Linux
    return [_python(background=True), "-X", "utf8", "-m", "docling_studio", "--no-browser", "--port", str(port)]


def start(port: int = PORT, wait: float = 90) -> None:
    """Start Studio as a background process (its output goes to studio.log) and wait until it answers."""
    log = home() / "studio.log"
    out = open(log, "ab")
    kwargs: dict = {"cwd": APP_DIR, "stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(server_command(port), **kwargs)
    out.close()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if running(port) == "studio":
            return
        if proc.poll() is not None and running(port) != "studio":
            raise RuntimeError("Studio stopped while starting.\n\n" + _tail(log))
        time.sleep(0.3)
    raise RuntimeError(f"Studio didn't start within {int(wait)} seconds.\n\n" + _tail(log))


def stop(port: int = PORT, wait: float = 20, force: bool = False) -> str:
    """Ask a running Studio to quit. Refused while a run is in progress (the message says so),
    unless force: then its runs are stopped."""
    if running(port) != "studio":
        return ""
    answer = _call("/api/quit" + ("?force=true" if force else ""), method="POST", port=port)
    if answer and answer[0] != 200:
        raise RuntimeError(answer[1].get("detail") or "Studio refused to quit.")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and running(port) == "studio":
        time.sleep(0.3)
    return "Studio has stopped."


def _tail(log: Path, lines: int = 12) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def alert(message: str) -> None:
    """Show a message without a terminal: a dialog on macOS and Windows, else printed."""
    print(message, file=sys.stderr)
    try:
        if sys.platform == "darwin":
            script = 'on run argv\n display alert "Docling Studio" message (item 1 of argv) as critical\nend run'
            subprocess.run(["osascript", "-e", script, message], capture_output=True, timeout=600)
        elif os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Docling Studio", 0x10)  # type: ignore[attr-defined]
    except Exception:
        pass


def open_studio(port: int = PORT, browser: bool = True) -> str:
    state = running(port)
    if state == "other":
        raise RuntimeError(f"Another program is using port {port}, which Studio needs. Close it and open Studio again.")
    if state is None:
        start(port)
    url = f"http://127.0.0.1:{port}/auth?token={_token()}"
    if browser:
        webbrowser.open(url)
    return url


def main() -> None:
    parser = argparse.ArgumentParser(prog="docling-studio-launch", description="Open Docling Studio, starting it if needed.")
    parser.add_argument("--stop", action="store_true", help="Ask a running Studio to quit.")
    parser.add_argument("--force", action="store_true", help="With --stop: quit even if conversions are running (stops them).")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    prepare_path()
    try:
        if args.stop:
            print(stop(args.port, force=args.force) or "Studio isn't running.")
        else:
            print(open_studio(args.port, browser=not args.no_browser))
    except RuntimeError as e:
        if args.stop:
            sys.exit(str(e))
        alert(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
