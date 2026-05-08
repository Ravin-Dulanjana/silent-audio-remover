#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Silence Remover"
APP_BUNDLE_ID="com.ravindulanjana.silenceremover"
VERSION="$(tr -d '\n' < "$ROOT_DIR/packaging/version.txt")"
BUILD_DIR="$ROOT_DIR/build/pyinstaller-work"
DIST_DIR="$ROOT_DIR/dist"
CACHE_DIR="$ROOT_DIR/build/pyinstaller-cache"
ASSET_DIR="$ROOT_DIR/build/assets"
ICONSET_DIR="$ASSET_DIR/SilenceRemover.iconset"
ICNS_PATH="$ASSET_DIR/silence_remover.icns"
DMG_STAGE_DIR="$ROOT_DIR/build/dmg-stage"
DMG_PATH="$DIST_DIR/Silence-Remover-macOS-v$VERSION.dmg"
APP_PATH="$DIST_DIR/$APP_NAME.app"

cd "$ROOT_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$CACHE_DIR" "$ASSET_DIR"

python3 packaging/generate_icons.py >/dev/null

plist_set_or_add() {
  local key="$1"
  local type="$2"
  local value="$3"
  if /usr/libexec/PlistBuddy -c "Print :$key" "$PLIST" >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c "Set :$key $value" "$PLIST"
  else
    /usr/libexec/PlistBuddy -c "Add :$key $type $value" "$PLIST"
  fi
}

PYINSTALLER_CONFIG_DIR="$CACHE_DIR" python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --workpath "$BUILD_DIR" \
  --distpath "$DIST_DIR" \
  --name "$APP_NAME" \
  --icon "$ICNS_PATH" \
  --osx-bundle-identifier "$APP_BUNDLE_ID" \
  --add-data "LICENSE:." \
  app.py

PLIST="$APP_PATH/Contents/Info.plist"
plist_set_or_add "CFBundleDisplayName" "string" "$APP_NAME"
plist_set_or_add "CFBundleName" "string" "$APP_NAME"
plist_set_or_add "CFBundleShortVersionString" "string" "$VERSION"
plist_set_or_add "CFBundleVersion" "string" "$VERSION"
plist_set_or_add "NSHighResolutionCapable" "bool" "true"

rm -rf "$DMG_STAGE_DIR"
mkdir -p "$DMG_STAGE_DIR"
cp -R "$APP_PATH" "$DMG_STAGE_DIR/"
ln -sfn /Applications "$DMG_STAGE_DIR/Applications"
rm -f "$DMG_PATH"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_STAGE_DIR" \
  -ov \
  -format UDZO \
  -fs HFS+ \
  "$DMG_PATH" >/dev/null

echo
echo "macOS app built at:"
echo "  $APP_PATH"
echo "macOS DMG built at:"
echo "  $DMG_PATH"
