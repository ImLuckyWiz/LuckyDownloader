#!/usr/bin/env bash
set -euo pipefail

# Parameterized Colab video cutter wrapper.
# Usage: bash tools/colab/cut_colab.sh --source-dir <SRC> --target-dir <DST> --cuts "<CUTS>"

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

python -u tools/colab/cut_colab.py "$@"
