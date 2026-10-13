#!/bin/bash
# Removes Docling Studio from this Mac. Your data (~/.docling-studio) is kept unless you say otherwise.
set -uo pipefail

ROOT="$HOME/Library/Application Support/Docling Studio"
APP="$HOME/Applications/Docling Studio.app"
PY="$ROOT/app/.pixi/envs/default/bin/python"
DATA="$HOME/.docling-studio"

clear 2>/dev/null || true
echo "Uninstall Docling Studio"
echo "─────────────────────────"
read -rp "Remove Docling Studio from this Mac? [y/N] " yes
[[ "$yes" =~ ^[Yy] ]] || { echo "Nothing was changed."; exit 0; }

if [ -x "$PY" ]; then
  "$PY" -m docling_studio.launch --stop --force >/dev/null 2>&1 || true  # stops running conversions too
  (cd "$ROOT/app" && "$PY" -m docling_studio.autostart uninstall) >/dev/null 2>&1 || true
fi
pkill -f "$PY -X utf8 -m docling_studio" 2>/dev/null || true  # only this installation's Studio
rm -rf "$APP"
rm -rf "$ROOT"
echo "✓ Removed the app and Studio's files."

if [ -d "$DATA" ]; then
  echo
  echo "Your Studio data is in $DATA (past runs and their outputs, presets, settings)."
  read -rp "Delete it too? [y/N] " wipe
  if [[ "$wipe" =~ ^[Yy] ]]; then
    rm -rf "$DATA"
    echo "✓ Deleted."
  else
    echo "Kept. Installing Studio again picks it up."
  fi
fi
echo
echo "Saved API keys are in your Keychain under \"docling-studio\" (Keychain Access → search docling-studio)."
echo "Your documents and Docling's downloaded models (~/.cache) weren't touched."
echo
read -n1 -rsp "Press any key to close this window."
echo
