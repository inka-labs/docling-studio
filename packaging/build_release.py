"""Build the downloads for people who don't use a terminal:

    pixi run release      # builds the UI, then packaging/dist/Docling-Studio-<version>-mac.zip and -windows.zip

Each zip holds an installer to double-click, "Read me first.txt" and app/: Studio's code, its UI
already built, and pixi.toml / pixi.lock (the installer installs exactly the locked packages). The
installer downloads pixi itself (the version this was built with), so the zips stay small.
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "packaging" / "dist"
SKIP_DIRS = {"__pycache__", ".pytest_cache", "tests", "node_modules", ".pixi"}


def studio_version() -> str:
    text = (REPO / "backend" / "pyproject.toml").read_text()
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def pixi_version() -> str:
    if os.environ.get("PIXI_VERSION"):
        return os.environ["PIXI_VERSION"]
    pixi = os.environ.get("PIXI_EXE") or shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    out = subprocess.run([pixi, "--version"], capture_output=True, text=True, check=True).stdout
    return out.split()[-1]


def app_files() -> list[Path]:
    """What goes in app/: the backend (without tests), the built UI, the pixi files, packaging/."""
    files = [REPO / "pixi.toml", REPO / "pixi.lock", REPO / "README.md"]
    files += [p for p in [REPO / "LICENSE"] if p.exists()]
    for top in ("backend", "frontend/dist", "frontend/dist-export", "packaging"):
        for path in sorted((REPO / top).rglob("*")):
            rel = path.relative_to(REPO)
            if path.is_file() and not SKIP_DIRS & set(rel.parts) and OUT not in path.parents \
                    and not any(part.endswith(".egg-info") for part in rel.parts) \
                    and path.suffix != ".pyc" and path.name != ".DS_Store":
                files.append(path)
    return files


def fill(text: str, versions: dict[str, str]) -> str:
    for key, value in versions.items():
        text = text.replace(f"__{key}__", value)
    return text


def add(zf: zipfile.ZipFile, name: str, data: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.create_system = 3  # unix: keep the executable bit (macOS Archive Utility honours it)
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, data)


def read_me(system: str, version: str) -> str:
    if system == "mac":
        text = f"""Docling Studio {version} for Mac
================================

INSTALL
1. Double-click "Install Docling Studio".
   The first time, macOS may say it "can't be opened" or "could not be verified". Then:
     - right-click (or Control-click) "Install Docling Studio" and choose Open, then Open again; or
     - open System Settings > Privacy & Security, scroll down and click "Open Anyway".
   This only happens because the installer isn't registered with Apple; it doesn't need your password.
2. A window shows the progress. The first install downloads about 2 GB and takes a few minutes.
3. Studio opens in your browser. From now on, open "Docling Studio" from Applications
   (or press Cmd+Space and type Docling).

UPDATE
Download the newer Docling Studio and run its installer the same way. Your runs, presets,
settings and services are kept.

GOOD TO KNOW
- Studio runs only on this computer; your documents never leave it (unless you convert on a
  docling-serve service you added). API keys are kept in your Mac's Keychain.
- The first install downloads Docling and PyTorch (about 2 GB). The first conversion also
  downloads Docling's models; Models > Download models fetches them ahead of time.
- Needs macOS 14 Sonoma or later on an Apple silicon Mac (M1 or newer).
- To have it start when you log in: Studio > Settings > "Start Docling Studio when I log in".

UNINSTALL
Studio > Settings > Studio > Quit Studio, then double-click "Uninstall Docling Studio"
(in this folder, or in ~/Library/Application Support/Docling Studio).
"""
    else:
        text = f"""Docling Studio {version} for Windows
====================================

INSTALL
1. Double-click "Install Docling Studio".
   Windows may show "Windows protected your PC": click "More info", then "Run anyway".
   If it asks "Do you want to run this file?", click Run.
   No administrator rights are needed.
2. A window shows the progress. The first install downloads about 2 GB and takes a few minutes.
3. Studio opens in your browser. From now on, open "Docling Studio" from the Start menu or the Desktop.

UPDATE
Download the newer Docling Studio and run its installer the same way. Your runs, presets,
settings and services are kept.

GOOD TO KNOW
- Studio runs only on this computer; your documents never leave it (unless you convert on a
  docling-serve service you added). API keys are kept in your Windows Credential Manager.
- The first install downloads Docling and PyTorch (about 2 GB). The first conversion also
  downloads Docling's models; Models > Download models fetches them ahead of time.
- Needs 64-bit Windows 10 or 11.
- To have it start when you log in: Studio > Settings > "Start Docling Studio when I log in".

UNINSTALL
Windows Settings > Apps > Installed apps > Docling Studio > Uninstall.
"""
    return text.replace("\n", "\r\n") if system == "windows" else text


def build() -> list[Path]:
    if not (REPO / "frontend" / "dist" / "index.html").is_file():
        sys.exit("Build the UI first: pixi run build-ui (pixi run release does this).")
    version = studio_version()
    versions = {"STUDIO_VERSION": version, "PIXI_VERSION": pixi_version()}
    files = app_files()
    OUT.mkdir(parents=True, exist_ok=True)
    top = f"Docling Studio {version}"
    built = []
    for system in ("mac", "windows"):
        target = OUT / f"Docling-Studio-{version}-{system}.zip"
        with zipfile.ZipFile(target, "w") as zf:
            for path in files:
                rel = path.relative_to(REPO).as_posix()
                data = path.read_bytes()
                if rel.startswith(("packaging/mac/", "packaging/windows/")) and path.suffix in (".command", ".ps1", ".cmd"):
                    data = fill(data.decode(), versions).encode()
                add(zf, f"{top}/app/{rel}", data, executable=path.suffix == ".command")
            add(zf, f"{top}/Read me first.txt", read_me(system, version).encode())
            if system == "mac":
                for script, name in (("install", "Install"), ("uninstall", "Uninstall")):
                    text = fill((REPO / "packaging" / "mac" / f"{script}.command").read_text(), versions)
                    add(zf, f"{top}/{name} Docling Studio.command", text.encode(), executable=True)
            else:
                add(zf, f"{top}/Install Docling Studio.cmd", (REPO / "packaging" / "windows" / "install.cmd").read_bytes())
        built.append(target)
    return built


if __name__ == "__main__":
    for path in build():
        print(f"{path.relative_to(REPO)}  ({path.stat().st_size / 1e6:.1f} MB)")
