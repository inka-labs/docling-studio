"""The computer's own Open dialogs, shown by the app (it runs on this computer), so people pick
files and folders the usual way and their documents are read where they are, not uploaded.
macOS: AppleScript. Windows: PowerShell with Windows Forms. Elsewhere: not available (the page
falls back to the browser's file picker)."""

import os
import subprocess
import sys

from . import brand

TIMEOUT = 600  # someone may take a while to choose


def available() -> bool:
    return sys.platform == "darwin" or os.name == "nt"


def _osascript(script: str) -> list[str]:
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=TIMEOUT)
    if proc.returncode != 0:  # cancelled
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _powershell(script: str) -> list[str]:
    proc = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True,
                          timeout=TIMEOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [line for line in proc.stdout.splitlines() if line.strip()]


def choose_files() -> list[str]:
    if sys.platform == "darwin":
        return _osascript(f'''
            set picked to choose file with prompt "Choose documents to convert" with multiple selections allowed
            set out to ""
            repeat with f in picked
              set out to out & POSIX path of f & linefeed
            end repeat
            return out''')
    if os.name == "nt":
        return _powershell(f'''
            Add-Type -AssemblyName System.Windows.Forms
            $d = New-Object System.Windows.Forms.OpenFileDialog
            $d.Multiselect = $true; $d.Title = "{brand.NAME}: choose documents to convert"
            if ($d.ShowDialog((New-Object System.Windows.Forms.Form -Property @{{TopMost=$true}})) -eq "OK") {{ $d.FileNames }}''')
    return []


def choose_folder(prompt: str = "Choose a folder") -> str | None:
    if sys.platform == "darwin":
        found = _osascript(f'return POSIX path of (choose folder with prompt "{prompt}")')
    elif os.name == "nt":
        found = _powershell(f'''
            Add-Type -AssemblyName System.Windows.Forms
            $d = New-Object System.Windows.Forms.FolderBrowserDialog
            $d.Description = "{prompt}"
            if ($d.ShowDialog((New-Object System.Windows.Forms.Form -Property @{{TopMost=$true}})) -eq "OK") {{ $d.SelectedPath }}''')
    else:
        found = []
    return found[0].rstrip("/\\\\") if found else None


def open_file(path: str) -> None:
    """Open with the app the computer uses for that kind of file (Word, Excel…)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def reveal(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
