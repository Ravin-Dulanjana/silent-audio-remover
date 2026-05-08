#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Silence Remover"
BUILD_DIR="$ROOT_DIR/build/pyinstaller-work"
DIST_DIR="$ROOT_DIR/dist"
CACHE_DIR="$ROOT_DIR/build/pyinstaller-cache"

cd "$ROOT_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$CACHE_DIR"

PYINSTALLER_CONFIG_DIR="$CACHE_DIR" python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --workpath "$BUILD_DIR" \
  --distpath "$DIST_DIR" \
  --name "$APP_NAME" \
  --add-data "LICENSE:." \
  app.py

echo
echo "macOS app built at:"
echo "  $ROOT_DIR/dist/$APP_NAME.app"
