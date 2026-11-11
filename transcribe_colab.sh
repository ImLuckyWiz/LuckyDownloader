#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo " [LuckyDownloader] Google Colab AI Transcriber"
echo "=========================================================="

# Check GPU availability
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "WARNING: No Nvidia GPU detected!"
    echo "Please switch your Colab runtime to T4 GPU:"
    echo "Runtime -> Change runtime type -> Hardware accelerator -> T4 GPU"
    echo ""
    echo "Attempting to continue anyway, but it will be much slower on CPU."
fi

# Ensure Google Drive is mounted
if [ ! -d "/content/drive/MyDrive" ]; then
    echo "ERROR: Google Drive is not mounted at /content/drive/MyDrive."
    echo "Please run: from google.colab import drive; drive.mount('/content/drive')"
    exit 1
fi

# Ensure we have the latest LuckyDownloader code
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

# Install dependencies
echo "--> Checking system dependencies..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "--> Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi

echo "--> Installing faster-whisper..."
pip install -q faster-whisper

echo "--> Starting transcription..."
python -u transcribe_colab.py
