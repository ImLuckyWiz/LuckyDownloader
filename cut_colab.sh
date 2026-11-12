#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo " [LuckyDownloader] Google Colab Video Cutter Runner"
echo "=========================================================="

# Ensure Google Drive is mounted
if [ ! -d "/content/drive/MyDrive" ]; then
    echo "ERROR: Google Drive is not mounted at /content/drive/MyDrive."
    echo "Please mount Google Drive first or run drive.mount('/content/drive')."
    exit 1
fi

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

# Check ffmpeg
echo "--> Checking system dependencies..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "--> Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi

echo "--> Starting automated lossless chapter cutting..."
python -u cut_colab.py
