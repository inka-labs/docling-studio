"""Start Studio when you log in, in the background, so it is ready when you open it.

Settings → Studio has a switch for this; from a terminal:

    pixi run autostart install     # start at login (and now, if it isn't running)
    pixi run autostart uninstall   # stop doing that
    pixi run autostart status

macOS: a LaunchAgent (~/Library/LaunchAgents/org.docling.studio.plist).
Linux: a systemd user service (~/.config/systemd/user/docling-studio.service).
Windows: a shortcut in the Startup folder.
Studio starts in the background without opening a browser; open it from its app / shortcut, or
http://127.0.0.1:8766. Its output goes to ~/.docling-studio/studio.log. If Studio is already
running, the login copy notices and exits.
"""

import os
import subprocess
import sys
from pathlib import Path

from .core.store import home
from .launch import APP_DIR, server_command

LABEL = "org.docling.studio"


class AutostartError(Exception):
    pass


def _log() -> Path:
    return home() / "studio.log"


def _plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _unit() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "docling-studio.service"


def _startup_shortcut() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Docling Studio.lnk"


def _path() -> Path | None:
    if sys.platform == "darwin":
        return _plist()
    if sys.platform.startswith("linux"):
        return _unit()
    if os.name == "nt":
        return _startup_shortcut()
    return None


def supported() -> bool:
    return _path() is not None


def enabled() -> bool:
    path = _path()
    return bool(path and path.exists())


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ps(text: str) -> str:
    """A PowerShell single-quoted string."""
    return "'" + text.replace("'", "''") + "'"


def install() -> str:
    if not (APP_DIR / "frontend" / "dist" / "index.html").is_file():
        raise AutostartError("Build the UI first: pixi run build-ui")
    cmd = server_command()
    if sys.platform == "darwin":
        args = "\n".join(f"    <string>{_xml(a)}</string>" for a in cmd)
        _plist().parent.mkdir(parents=True, exist_ok=True)
        _plist().write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>WorkingDirectory</key><string>{_xml(str(APP_DIR))}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>{_xml(str(_log()))}</string>
  <key>StandardErrorPath</key><string>{_xml(str(_log()))}</string>
</dict>
</plist>
""")
        subprocess.run(["launchctl", "unload", str(_plist())], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", str(_plist())], capture_output=True)
        return f"Studio now starts when you log in. Settings: {_plist()}"
    if sys.platform.startswith("linux"):
        _unit().parent.mkdir(parents=True, exist_ok=True)
        _unit().write_text(f"""[Unit]
Description=Docling Studio

[Service]
WorkingDirectory={APP_DIR}
ExecStart={" ".join(f'"{a}"' for a in cmd)}
Restart=on-failure
StandardOutput=append:{_log()}
StandardError=append:{_log()}

[Install]
WantedBy=default.target
""")
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
            subprocess.run(["systemctl", "--user", "enable", "--now", "docling-studio.service"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise AutostartError(f"systemd didn't accept the service: {e}")
        return f"Studio now starts when you log in. Service: {_unit()}"
    if os.name == "nt":
        link = _startup_shortcut()
        link.parent.mkdir(parents=True, exist_ok=True)
        script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps(str(link))}); "
                  f"$s.TargetPath = {_ps(cmd[0])}; "
                  f"$s.Arguments = {_ps(subprocess.list2cmdline(cmd[1:]))}; "
                  f"$s.WorkingDirectory = {_ps(str(APP_DIR))}; $s.WindowStyle = 7; $s.Save()")
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True)
        if proc.returncode != 0 or not link.exists():
            raise AutostartError(f"Couldn't create the Startup shortcut: {proc.stderr.strip()[:300]}")
        return f"Studio now starts when you log in. Shortcut: {link}"
    raise AutostartError(f"Starting at login isn't set up for {sys.platform}.")


def uninstall(stop_now: bool = True) -> str:
    """stop_now=False (from Studio's own Settings) leaves a Studio that started at login running."""
    if sys.platform == "darwin" and _plist().exists():
        if stop_now:
            subprocess.run(["launchctl", "unload", "-w", str(_plist())], capture_output=True)
        _plist().unlink()
    elif sys.platform.startswith("linux") and _unit().exists():
        subprocess.run(["systemctl", "--user", "disable", "docling-studio.service"], capture_output=True)
        _unit().unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    elif os.name == "nt" and _startup_shortcut().exists():
        _startup_shortcut().unlink()
    else:
        return "Studio wasn't set to start at login."
    return "Studio no longer starts at login."


def status() -> str:
    return f"Starts at login: {'yes' if enabled() else 'no'} ({_path()})"


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    actions = {"install": install, "uninstall": uninstall, "status": status}
    if action not in actions:
        sys.exit("Usage: pixi run autostart [install | uninstall | status]")
    try:
        print(actions[action]())
    except AutostartError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
