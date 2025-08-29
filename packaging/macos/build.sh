#!/usr/bin/env bash
set -euo pipefail

# Build WhisperLiveKit.app via PyInstaller

PYTHON_BIN=${PYTHON_BIN:-python3}
WORKDIR=$(cd "$(dirname "$0")/../.." && pwd)
cd "$WORKDIR"

echo "[1/4] Creating venv..."
$PYTHON_BIN -m venv .venv
source .venv/bin/activate

echo "[2/4] Installing dependencies..."
python -m pip install -U pip wheel
# Install the project with GUI extra so pywebview is available
python -m pip install -e .[gui]
# Ensure PyInstaller is present
python -m pip install pyinstaller

echo "[3/4] Building macOS app bundle..."
pyinstaller packaging/macos/whisperlivekit_gui.spec --noconfirm

echo "[4/4] Done. App bundle at dist/WhisperLiveKit.app"
echo "Tip: first run may need ad-hoc codesign for mic permissions:"
echo "  codesign --force --deep --sign - dist/WhisperLiveKit.app"

