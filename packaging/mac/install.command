#!/bin/bash
# Installs, or updates, Paperlift for this Mac user. Double-click it (first time: right-click → Open).
#
#   ~/Library/Application Support/Paperlift/   app/ (Studio and its environment), bin/pixi
#   ~/Applications/Paperlift.app               opens Studio (starts it if needed, signs you in)
#   ~/.paperlift/                              your runs, presets, settings (kept on update)
#
# No administrator password; nothing outside your home folder is touched. Built by packaging/build_release.py.
#
# Studio's "Update now" runs it with PAPERLIFT_UNATTENDED=1: no prompts, and Studio is started
# again in the background (the browser tab that asked for the update reconnects) rather than opened.
set -euo pipefail

PIXI_VERSION="__PIXI_VERSION__"
STUDIO_VERSION="__STUDIO_VERSION__"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HOME/Library/Application Support/Paperlift"
APP="$HOME/Applications/Paperlift.app"
PY="$ROOT/app/.pixi/envs/default/bin/python"
UNATTENDED="${PAPERLIFT_UNATTENDED:-}"

finish() {
  [ -n "$UNATTENDED" ] && return
  echo
  read -n1 -rsp "Press any key to close this window." || true
  echo
}
fail() {
  echo
  echo "✗ $1"
  echo
  echo "  Nothing you had in Studio (runs, presets, services) was changed."
  if [ -n "$UNATTENDED" ] && [ -x "$PY" ]; then
    # back as it was, if it can be (its output is the sign-in link: not for the log)
    (cd "$ROOT/app" && "$PY" -m docling_studio.launch --no-browser >/dev/null) || true
  fi
  finish
  exit 1
}
trap 'fail "The installation stopped (see the messages above). Check your internet connection and try again."' ERR

[ -n "$UNATTENDED" ] || clear 2>/dev/null || true
echo "Paperlift $STUDIO_VERSION ($(date))"
echo "──────────────────────────────"
[ -f "$HERE/app/pixi.toml" ] || fail "Open this from the unzipped Paperlift folder (its app folder is missing)."

mkdir -p "$ROOT/bin"

# 1. pixi: installs Python and packages, for Studio and Docling.
if [ "$("$ROOT/bin/pixi" --version 2>/dev/null || true)" != "pixi $PIXI_VERSION" ]; then
  case "$(uname -m)" in
    arm64) TARGET=aarch64-apple-darwin ;;
    *) TARGET=x86_64-apple-darwin ;;
  esac
  echo "→ Downloading pixi $PIXI_VERSION (installs Docling and the Python packages Studio uses)…"
  curl -fsSL "https://github.com/prefix-dev/pixi/releases/download/v$PIXI_VERSION/pixi-$TARGET.tar.gz" | tar -xz -C "$ROOT/bin" pixi
  chmod +x "$ROOT/bin/pixi"
fi

# 2. An update: stop the Studio that's running (it refuses while a conversion runs).
if [ -x "$PY" ]; then
  if ! "$PY" -m docling_studio.launch --stop; then
    fail "Studio is busy (see above). Let it finish, or quit it in Studio → Settings → Quit Studio, then open this installer again."
  fi
fi

# 3. Studio's files (its environment, .pixi, is kept so an update is quick).
echo "→ Copying Studio…"
mkdir -p "$ROOT/app"
rsync -a --delete --exclude "/.pixi/" "$HERE/app/" "$ROOT/app/"

# 4. Studio's own Python and packages.
echo "→ Installing Studio's Python and packages (a few minutes the first time)…"
"$ROOT/bin/pixi" install --manifest-path "$ROOT/app/pixi.toml" --frozen

# 5. The app you open it with.
echo "→ Adding Paperlift to your Applications…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/app/packaging/mac/icon.icns" "$APP/Contents/Resources/icon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Paperlift</string>
  <key>CFBundleDisplayName</key><string>Paperlift</string>
  <key>CFBundleIdentifier</key><string>app.paperlift.desktop.launcher</string>
  <key>CFBundleVersion</key><string>$STUDIO_VERSION</string>
  <key>CFBundleShortVersionString</key><string>$STUDIO_VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Paperlift</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST
cat > "$APP/Contents/MacOS/Paperlift" <<LAUNCH
#!/bin/bash
# Opens Paperlift: starts it in the background if needed, then opens it in your browser.
cd "$ROOT/app" && exec "$PY" -m docling_studio.launch
LAUNCH
chmod +x "$APP/Contents/MacOS/Paperlift"
touch "$APP"

# 6. The uninstaller, next to Studio.
cp "$ROOT/app/packaging/mac/uninstall.command" "$ROOT/Uninstall Paperlift.command"
chmod +x "$ROOT/Uninstall Paperlift.command"

trap - ERR
echo
if [ -n "$UNATTENDED" ]; then
  echo "✓ Paperlift $STUDIO_VERSION is installed. Starting it again…"
  cd "$ROOT/app" && "$PY" -m docling_studio.launch --no-browser >/dev/null  # prints the sign-in link: not for the log
  echo "✓ Studio is running again."
  exit 0
fi
echo "✓ Paperlift $STUDIO_VERSION is installed. Opening it in your browser…"
echo "  Next time, open Paperlift from Applications (or Spotlight: ⌘ Space, type Paperlift)."
open "$APP"
sleep 2
finish
