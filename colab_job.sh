#!/usr/bin/env bash
set -euo pipefail

TARGET="/content/drive/MyDrive/Lucky/Vexoria_The_SunEater"
DOWNLOAD_DIR="/content/downloads"

echo "=========================================================="
echo " [LuckyDownloader] Google Colab Batch Runner"
echo "=========================================================="

# Ensure we are in /content/LuckyDownloader with the latest code
if [ ! -f "cli.py" ]; then
    cd /content
    rm -rf /content/LuckyDownloader
    git clone https://github.com/ImLuckyWiz/LuckyDownloader.git
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

# --- VOD 1: Day 1 ---
echo ""
echo "=========================================================="
echo " [1/2] Processing Day 1 (https://www.twitch.tv/videos/2921207042)"
echo " Cut: 0:09:20 - end"
echo "=========================================================="
python -u cli.py "https://www.twitch.tv/videos/2921207042" \
    -c "0:09:20 - end" \
    --template "{streamer} - {title} - {game} - part{n}" \
    --no-subfolders \
    -o "$DOWNLOAD_DIR"

echo "--> Moving Day 1 output to Google Drive..."
mv "$DOWNLOAD_DIR"/*.mp4 "$TARGET/"

echo "--> Cleaning temporary files to free VM disk space..."
rm -rf "$DOWNLOAD_DIR"/* /tmp/* /root/.cache/* 2>/dev/null || true
sync
echo "--> Day 1 complete and saved."

# --- VOD 2: Day 3 ---
echo ""
echo "=========================================================="
echo " [2/2] Processing Day 3 (https://www.twitch.tv/videos/2922207633)"
echo " Cut: 0:08:30 - end"
echo "=========================================================="
python -u cli.py "https://www.twitch.tv/videos/2922207633" \
    -c "0:08:30 - end" \
    --template "{streamer} - {title} - {game} - part{n}" \
    --no-subfolders \
    -o "$DOWNLOAD_DIR"

echo "--> Moving Day 3 output to Google Drive..."
mv "$DOWNLOAD_DIR"/*.mp4 "$TARGET/"

echo "--> Cleaning temporary files..."
rm -rf "$DOWNLOAD_DIR"/* /tmp/* /root/.cache/* 2>/dev/null || true
sync
echo "--> Day 3 complete and saved."

echo ""
echo "=========================================================="
echo " SUCCESS! Both videos have been processed and saved."
echo " Destination: $TARGET"
echo "=========================================================="
ls -lh "$TARGET"
