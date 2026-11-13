#!/usr/bin/env bash
set -euo pipefail

# Parameterized Google Colab Whisper transcription runner.
# Usage: bash tools/colab/transcribe.sh --source-dir <DIR> [--lang en] [--format txt,srt]

REPO_DIR="${REPO_DIR:-/content/LuckyDownloader}"

if [ ! -d "$REPO_DIR/.git" ]; then
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone -q https://github.com/ImLuckyWiz/LuckyDownloader.git "$REPO_DIR"
fi
cd "$REPO_DIR"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "--> Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi

echo "--> Installing faster-whisper, PyAV, and CUDA 12 runtime libraries..."
pip install -q "faster-whisper" "av<19" "nvidia-cublas-cu12" "nvidia-cudnn-cu12"

NV_LIB_PATHS=$(python3 -c "import site, os; paths = [os.path.join(p, 'nvidia', sub, 'lib') for p in site.getsitepackages() for sub in ['cublas', 'cudnn']]; print(':'.join(x for x in paths if os.path.isdir(x)))" 2>/dev/null || true)
if [ -n "$NV_LIB_PATHS" ]; then
    export LD_LIBRARY_PATH="${NV_LIB_PATHS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

python -u tools/colab/transcribe.py "$@"
