#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-/content/drive/MyDrive/Lucky/Vexoria_The_SunEater}"
DOWNLOAD_DIR="/content/downloads"

echo "=========================================================="
echo " [LuckyDownloader] Google Colab Runner"
echo "=========================================================="

# Ensure we have the latest code
if [ -d "/content/LuckyDownloader/.git" ]; then
    cd /content/LuckyDownloader
    git fetch origin main -q
    git reset --hard origin/main -q
else
    cd /content
    rm -rf /content/LuckyDownloader
    git clone -q https://github.com/ImLuckyWiz/LuckyDownloader.git
    cd /content/LuckyDownloader
fi

# Ensure Google Drive is mounted
if [ ! -d "/content/drive/MyDrive" ]; then
    echo "ERROR: Google Drive is not mounted at /content/drive/MyDrive."
    echo "Please mount Google Drive first or run drive.mount('/content/drive')."
    exit 1
fi

mkdir -p "$TARGET"
mkdir -p "$DOWNLOAD_DIR"

# Ensure dependencies are installed
echo "--> Checking system dependencies..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "--> Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi

echo "--> Installing Python requirements..."
pip install -q -r requirements-cli.txt

# Target VOD configuration (configurable via arguments or defaults to Day 4)
VOD_URL="${1:-https://www.twitch.tv/videos/2924107710}"
VOD_CUT="${2:-0:07:10 - end}"

echo ""
echo "=========================================================="
echo " Processing: $VOD_URL"
echo " Cut: $VOD_CUT"
echo " Destination: $TARGET"
echo "=========================================================="

python -u cli.py "$VOD_URL" \
    -c "$VOD_CUT" \
    --template "{streamer} - {title} - {game} - part{n}" \
    --no-subfolders \
    -o "$DOWNLOAD_DIR"

echo "--> Moving output to Google Drive..."
mv "$DOWNLOAD_DIR"/*.mp4 "$TARGET/"

echo "--> Cleaning temporary files to free VM disk space..."
rm -rf "$DOWNLOAD_DIR"/* /tmp/* /root/.cache/* 2>/dev/null || true
sync

echo ""
echo "=========================================================="
echo " SUCCESS! Video has been processed and saved to Google Drive."
echo " Destination: $TARGET"
echo "=========================================================="
ls -lh "$TARGET"
