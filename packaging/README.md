# Packaging: installers for Mac and Windows

For people who don't use a terminal: download a zip, double-click the installer, then open
**Docling Studio** from Applications or the Start menu. No pixi, git, clone or build step on their side.

## Make a release

macOS needs 14 Sonoma or later on Apple silicon; Windows needs x64 (see `pixi.toml` for why).

    pixi run release

That builds the UI, then writes `packaging/dist/Docling-Studio-<version>-mac.zip` and `-windows.zip` (under 1 MB each).
The version comes from `backend/pyproject.toml`. Bump it there before each release, since the installers
and **Settings** show it. Put both zips where your users can download them without signing in, for example
a public GitHub release.

Each zip contains:

| | |
|---|---|
| `Install Docling Studio.command` / `.cmd` | the installer to double-click |
| `Uninstall Docling Studio.command` | Mac only (on Windows: Settings → Apps) |
| `Read me first.txt` | install steps, including getting past the "unidentified developer" / SmartScreen warning |
| `app/` | Studio: `backend/` (no tests), `frontend/dist/` (built UI), `pixi.toml`, `pixi.lock`, `packaging/` |

## What the installer does

No administrator rights are needed, and only the user's own folders are touched:

1. It downloads pixi, at the version the release was built with, into Studio's folder. It doesn't use or change any pixi the user may already have.
2. If Studio is already installed (an update), it stops it. It refuses while a conversion is running, and says so.
3. It copies `app/`, keeping the existing `.pixi` environment so updates are quick.
4. It runs `pixi install --frozen`, so the user gets exactly the locked packages: Docling with its OCR, VLM and ASR extras, and PyTorch (about 2 GB).
5. It adds the launcher, opens Studio, and leaves the uninstaller behind.

To update, people download the newer zip and run its installer the same way; their runs, presets and services
are kept. (Ecoscope Studio's in-app *Update now* isn't part of Docling Studio yet. The installers already accept
`DOCLING_STUDIO_UNATTENDED=1` for it.)

| | Mac | Windows |
|---|---|---|
| Studio's folder | `~/Library/Application Support/Docling Studio/` | `%LOCALAPPDATA%\Docling Studio\` |
| Launcher | `~/Applications/Docling Studio.app` | Start menu + Desktop shortcut |
| Uninstall | `Uninstall Docling Studio.command` | Settings → Apps → Docling Studio |
| Data (kept across updates) | `~/.docling-studio/` | `%USERPROFILE%\.docling-studio\` |

The launcher runs `python -m docling_studio.launch` from Studio's environment
([launch.py](../backend/docling_studio/launch.py)). If Studio isn't running, it starts it in the background,
logging to `studio.log`. Then it opens the browser at the sign-in link. Opening it again only opens the browser.
**Settings** has *Start Docling Studio when I log in* and *Quit Docling Studio*.

## Files here

- `build_release.py`: builds the zips. It fills `__STUDIO_VERSION__` and `__PIXI_VERSION__` into the scripts below.
- `mac/install.command`, `mac/uninstall.command`, `mac/icon.icns`
- `windows/install.cmd` runs `windows/install.ps1`; also `windows/uninstall.ps1` and `windows/icon.ico`. Keep the
  `.ps1` files ASCII-only, because Windows PowerShell 5.1 misreads UTF-8 without a BOM.
- `icon.svg`: the source of both icons.

## Testing a build without touching your own Studio

    unzip it with:  ditto -x -k packaging/dist/Docling-Studio-<v>-mac.zip /tmp/try
    env HOME=/tmp/try/home DOCLING_STUDIO_PORT=8799 BROWSER=true "/tmp/try/Docling Studio <v>/Install Docling Studio.command"

`DOCLING_STUDIO_PORT` runs it on another port than your own Studio (8766). On Windows, try it on a real machine
or VM: `pwsh` can parse the scripts on a Mac, but can't run them.

## Not signed (yet)

The installers aren't code-signed. The first time, macOS asks users to right-click → Open (or Privacy & Security →
Open Anyway), and Windows shows SmartScreen's "More info → Run anyway". `Read me first.txt` explains both. Signing
needs an Apple Developer account ($99/year, plus notarisation) and a Windows code-signing certificate. Consider it
once the warnings, rather than the install steps, are what's stopping people.
