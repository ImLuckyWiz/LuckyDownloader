#!/usr/bin/env bash
# Build LuckyDownloader (PySide6) for macOS with Nuitka -> dist/LuckyDownloader.app (+ dist/LuckyDownloader-macos-<arch>.dmg)
# Usage: bash build_mac.sh [version]
# The result matches the Mac you build on: Apple Silicon -> arm64, Intel -> x86_64.
set -euo pipefail
cd "$(dirname "$0")"

VER="${1:-${GITHUB_REF_NAME:-1.0}}"
BUNDLE_ID="com.luckydownloader.app"
case "$VER" in
  *-*) BUNDLE_ID="com.luckydownloader.app.beta" ;;
esac

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

mkdir -p build
printf '%s\n' "$VER" > build/version.txt

rm -rf dist/LuckyDownloader.app

python3 -m nuitka --mode=app \
  --enable-plugin=pyside6 \
  --macos-app-icon=assets/icon.icns \
  --macos-app-name=LuckyDownloader \
  --macos-signed-app-name="$BUNDLE_ID" \
  --macos-app-version="$VER" \
  --output-dir=dist \
  --output-folder-name=LuckyDownloader \
  --output-filename=LuckyDownloader \
  --include-data-dir=assets=assets \
  --include-data-dir=locale=locale \
  --include-data-files=build/version.txt=version.txt \
  --include-package=core \
  --include-package=qt_ui \
  --include-package=requests \
  --include-module=luckytwitch_engine \
  --include-module=weblink \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=_tkinter \
  --nofollow-import-to=pytest \
  --assume-yes-for-downloads \
  --update-check=never \
  luckytwitch_qt.py

# Let macOS send luckydownloader:// and luckytwitch:// links to the app. This has to happen before signing.
PLIST="dist/LuckyDownloader.app/Contents/Info.plist"
PB=/usr/libexec/PlistBuddy
"$PB" -c "Delete :CFBundleURLTypes" "$PLIST" 2>/dev/null || true
"$PB" -c "Add :CFBundleURLTypes array" \
      -c "Add :CFBundleURLTypes:0 dict" \
      -c "Add :CFBundleURLTypes:0:CFBundleURLName string com.luckydownloader.app.link" \
      -c "Add :CFBundleURLTypes:0:CFBundleTypeRole string Viewer" \
      -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" \
      -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string luckydownloader" \
      -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:1 string luckytwitch" "$PLIST"

# Ad-hoc signature: required for arm64 binaries to launch at all.
codesign --force --deep --sign - dist/LuckyDownloader.app

ARCH="$(uname -m)"
# DMG: a disk image showing the app next to an "Applications" shortcut (drag to install).
STAGE="$(mktemp -d)"
ditto dist/LuckyDownloader.app "$STAGE/LuckyDownloader.app"
ln -s /Applications "$STAGE/Applications"
rm -f "dist/LuckyDownloader-macos-${ARCH}.dmg"
DMG_OK=0
for attempt in 1 2 3 4 5; do
  if hdiutil create -volname "LuckyDownloader" -srcfolder "$STAGE" -ov -format UDZO "dist/LuckyDownloader-macos-${ARCH}.dmg"; then
    DMG_OK=1
    break
  fi
  echo "hdiutil create failed (attempt $attempt of 5), retrying..."
  hdiutil detach "/Volumes/LuckyDownloader" -force >/dev/null 2>&1 || true
  rm -f "dist/LuckyDownloader-macos-${ARCH}.dmg"
  sleep $((attempt * 5))
done
[ "$DMG_OK" = 1 ] || { echo "Could not create the DMG after 5 attempts."; exit 1; }
rm -rf "$STAGE"

if [ -z "${CI:-}" ]; then
  DEST="/Applications"
  [ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
  rm -rf "$DEST/LuckyDownloader.app"
  ditto dist/LuckyDownloader.app "$DEST/LuckyDownloader.app"
  LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
  [ -x "$LSREG" ] && "$LSREG" -f "$DEST/LuckyDownloader.app" || true
  echo "Installed in $DEST/LuckyDownloader.app"
fi

echo
echo "Done: dist/LuckyDownloader.app  and  dist/LuckyDownloader-macos-${ARCH}.dmg"
