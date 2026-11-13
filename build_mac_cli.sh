#!/usr/bin/env bash
# Build LuckyDownloader CLI for macOS with Nuitka -> dist/LuckyDownloader-CLI-macos-<arch>.tar.gz
# Usage: bash build_mac_cli.sh [version]
set -euo pipefail
cd "$(dirname "$0")"

VER="${1:-${GITHUB_REF_NAME:-1.0}}"
ARCH="$(uname -m)"

echo "Building LuckyDownloader CLI macOS standalone ($VER, $ARCH)..."

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-cli.txt -r requirements-build.txt

mkdir -p build
printf '%s\n' "$VER" > build/version.txt

rm -rf dist/LuckyDownloader-CLI dist/LuckyDownloader-CLI.dist

python3 -m nuitka --mode=standalone \
  --output-dir=dist \
  --output-folder-name=LuckyDownloader-CLI \
  --output-filename=LuckyDownloader-CLI \
  --include-data-dir=locale=locale \
  --include-data-files=build/version.txt=version.txt \
  --include-package=core \
  --include-package=requests \
  --nofollow-import-to=PySide6 \
  --nofollow-import-to=qt_ui \
  --nofollow-import-to=PIL \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=_tkinter \
  --nofollow-import-to=pytest \
  --assume-yes-for-downloads \
  --update-check=never \
  cli.py

if [ -d "dist/LuckyDownloader-CLI.dist" ]; then
    rm -rf dist/LuckyDownloader-CLI
    mv dist/LuckyDownloader-CLI.dist dist/LuckyDownloader-CLI
fi

echo "Creating CLI portable tarball..."
tar -czf "dist/LuckyDownloader-CLI-macos-${ARCH}.tar.gz" -C dist LuckyDownloader-CLI

echo "Done! Output in dist/LuckyDownloader-CLI-macos-${ARCH}.tar.gz"
