#!/usr/bin/env bash
# Build LuckyDownloader (PySide6) for Linux with Nuitka -> dist/LuckyDownloader-x86_64.AppImage (+ dist/LuckyDownloader-linux-x86_64.tar.gz)
# Usage: bash build_linux.sh [version]
set -euo pipefail
cd "$(dirname "$0")"

VER="${1:-${GITHUB_REF_NAME:-1.0}}"

echo "Building LuckyDownloader Linux standalone ($VER)..."

PIP_FLAGS=""
if python3 -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
    PIP_FLAGS="--break-system-packages"
fi

python3 -m pip install --upgrade pip $PIP_FLAGS || true
python3 -m pip install -r requirements.txt $PIP_FLAGS

mkdir -p build
printf '%s\n' "$VER" > build/version.txt

rm -rf dist/LuckyDownloader dist/LuckyDownloader.dist

python3 -m nuitka --mode=standalone \
  --enable-plugin=pyside6 \
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

# Nuitka in standalone mode creates dist/LuckyDownloader.dist; normalize to dist/LuckyDownloader
if [ -d "dist/LuckyDownloader.dist" ]; then
    rm -rf dist/LuckyDownloader
    mv dist/LuckyDownloader.dist dist/LuckyDownloader
fi

# Create fallback portable tarball
echo "Creating portable tarball..."
tar -czf "dist/LuckyDownloader-linux-x86_64.tar.gz" -C dist LuckyDownloader

# Build AppImage AppDir structure
echo "Assembling AppDir..."
APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"

cp -r dist/LuckyDownloader/* "$APPDIR/usr/bin/"
cp assets/luckydownloader.desktop "$APPDIR/luckydownloader.desktop"
cp assets/luckydownloader.desktop "$APPDIR/usr/share/applications/luckydownloader.desktop"
cp assets/luckydownloader.png "$APPDIR/luckydownloader.png"
cp assets/luckydownloader.png "$APPDIR/usr/share/icons/hicolor/512x512/apps/luckydownloader.png"

cat << 'EOF' > "$APPDIR/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin${PATH:+:$PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "${HERE}/usr/bin/LuckyDownloader" "$@"
EOF
chmod +x "$APPDIR/AppRun"

if command -v appimagetool >/dev/null 2>&1; then
    echo "Creating AppImage with appimagetool..."
    ARCH=x86_64 appimagetool --no-appstream "$APPDIR" "dist/LuckyDownloader-x86_64.AppImage"
else
    echo "Notice: appimagetool not found on PATH. Tarball created at dist/LuckyDownloader-linux-x86_64.tar.gz."
fi

echo "Linux build completed successfully."
