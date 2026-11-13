#!/usr/bin/env bash
set -euo pipefail

# Generic Google Colab runner for LuckyDownloader CLI.
# Usage:
#   bash tools/colab/colab_job.sh --url <URL> --target <DRIVE_DIR> [--cuts "<CUTS>"] [--template "<TPL>"] [--update]

REPO_DIR="${REPO_DIR:-/content/LuckyDownloader}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/content/downloads}"
TARGET="${TARGET:-/content/drive/MyDrive/LuckyDownloader}"
VOD_URL="${VOD_URL:-}"
VOD_CUT="${VOD_CUT:-}"
TEMPLATE="${TEMPLATE:-}"
DO_UPDATE=0
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)       VOD_URL="$2"; shift 2 ;;
        --cuts|-c)   VOD_CUT="$2"; shift 2 ;;
        --target|-o) TARGET="$2"; shift 2 ;;
        --template)  TEMPLATE="$2"; shift 2 ;;
        --update)    DO_UPDATE=1; shift ;;
        *)           EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if [ -z "$VOD_URL" ]; then
    echo "Usage: $0 --url <URL> [--target <DIR>] [--cuts <CUTS>] [--template <TPL>] [--update] [extra cli.py flags]"
    exit 1
fi

echo "=========================================================="
echo " [LuckyDownloader] Google Colab Runner"
echo "=========================================================="

if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    if [ "$DO_UPDATE" -eq 1 ]; then
        git pull --ff-only -q
    fi
else
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone -q https://github.com/ImLuckyWiz/LuckyDownloader.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

if [[ "$TARGET" == /content/drive/* ]] && [ ! -d "/content/drive/MyDrive" ]; then
    echo "ERROR: Google Drive is not mounted at /content/drive/MyDrive."
    echo "Please mount Google Drive first: from google.colab import drive; drive.mount('/content/drive')"
    exit 1
fi

mkdir -p "$TARGET"
mkdir -p "$DOWNLOAD_DIR"

echo "--> Checking system dependencies..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "--> Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi

echo "--> Installing Python requirements..."
pip install -q -r requirements-cli.txt

CLI_ARGS=("$VOD_URL" "-o" "$DOWNLOAD_DIR")
if [ -n "$VOD_CUT" ]; then
    CLI_ARGS+=("-c" "$VOD_CUT")
fi
if [ -n "$TEMPLATE" ]; then
    CLI_ARGS+=("--template" "$TEMPLATE")
fi
if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
    CLI_ARGS+=("${EXTRA_ARGS[@]}")
fi

echo "--> Processing: $VOD_URL"
python -u cli.py "${CLI_ARGS[@]}"

echo "--> Moving finished outputs to $TARGET..."
find "$DOWNLOAD_DIR" -mindepth 1 -maxdepth 1 ! -name '.l*' -exec mv -t "$TARGET/" {} +

echo "--> Cleaning temporary download directory..."
rm -rf "$DOWNLOAD_DIR"
sync

echo "--> Done! Files saved in $TARGET"
ls -lh "$TARGET"
