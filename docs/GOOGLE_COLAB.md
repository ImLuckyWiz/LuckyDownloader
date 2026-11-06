# Running LuckyDownloader on Google Colab

LuckyDownloader includes a dedicated headless CLI (`cli.py`) that runs without any GUI or display server. This makes it ideal for running inside **Google Colab** to download high-resolution streams or trim long Twitch VODs using high-speed cloud bandwidth and saving the output directly to **Google Drive**.

---

## Step 1: Mount Google Drive (Optional)

If you want downloaded videos to be saved permanently to your Google Drive account, run this in a Colab notebook cell:

```python
from google.colab import drive
drive.mount('/content/drive')
```

---

## Step 2: Clone & Install (Headless / Fast)

Colab already comes with Python and system utilities. You only need to clone the repository and install the lightweight CLI requirements (`requirements-cli.txt`), which skips the large PySide6 GUI packages:

```bash
# Clone the repository
!git clone https://github.com/ImLuckyWiz/LuckyDownloader.git
%cd LuckyDownloader

# Install lightweight dependencies (takes < 10 seconds)
!pip install -r requirements-cli.txt

# Ensure ffmpeg is available
!apt-get update -qq && apt-get install -y -qq ffmpeg
```

---

## Step 3: Run the CLI

> [!TIP]
> **Performance Tip (Local SSD vs Google Drive FUSE):**  
> While you *can* download directly into `/content/drive/MyDrive/...`, Google Drive FUSE operates over a network layer. Multi-threaded HLS downloads generate thousands of temporary fragment files; assembling them directly on Google Drive introduces network I/O latency.  
>  
> For **maximum speed**, download to Colab's local NVMe disk (`./downloads`) first, and copy only the final finished files to Google Drive at the end:
> ```bash
> # 1. Download & cut at lightning NVMe speed
> !python cli.py "https://www.twitch.tv/videos/123456789" \
>     --cuts "0:00:00 - 1:18:55 - end" \
>     --out "./downloads" \
>     --format mp4
> 
> # 2. Copy the final video files to Google Drive in seconds
> !mkdir -p "/content/drive/MyDrive/LuckyDownloader"
> !cp -r ./downloads/* "/content/drive/MyDrive/LuckyDownloader/"
> ```

### Example 1: Trim VOD into sections using cut points

Cut points follow the exact syntax as the desktop app:
- Consecutive parts: `"0:00:00 - 1:18:55 - end"` (splits into Part 1 from start to 1:18:55, and Part 2 from 1:18:55 to the end).
- Skip sections: `"0:10:00 - 0:40:00 ; 1:20:00 - 2:00:00"` (downloads only those two ranges, skipping the rest).

```bash
!python cli.py "https://www.twitch.tv/videos/123456789" \
    --cuts "0:00:00 - 1:18:55 - end" \
    --out "/content/drive/MyDrive/LuckyDownloader" \
    --quality best
```

### Example 2: Download only a single segment

```bash
!python cli.py "https://www.twitch.tv/videos/123456789" \
    --cuts "0:30:00 - 1:00:00" \
    --out "/content/drive/MyDrive/LuckyDownloader" \
    --strategy sections
```

### Example 3: Custom Filename Template

Customize the generated filenames using metadata variables like `{streamer}`, `{title}`, `{game}`, and `{n}`:

```bash
!python cli.py "https://www.twitch.tv/videos/123456789" \
    --cuts "0:00:00 - 1:18:55 - end" \
    --template "{streamer} - {title} - {game} - part{n}" \
    --out "/content/drive/MyDrive/LuckyDownloader"
```

### Example 4: Preview with Dry Run (no files downloaded)

Use `--dry-run` to inspect stream title, duration, coverage percentage, and the calculated cut parts before starting the download:

```bash
!python cli.py "https://www.twitch.tv/videos/123456789" \
    --cuts "0:00:00 - 1:18:55 - end" \
    --dry-run
```

### Example 5: Audio-Only Extraction

```bash
!python cli.py "https://www.twitch.tv/videos/123456789" \
    --quality audio \
    --audio-format mp3 \
    --out "/content/drive/MyDrive/LuckyDownloader"
```

---

## CLI Options Reference

| Option | Shorthand | Description | Default |
|---|---|---|---|
| `url` | | VOD or video URL (Twitch, YouTube, etc.) | Required |
| `--cuts` | `-c` | Cut points string (e.g. `"0:00:00 - 1:18:55 - end"`) | Entire video |
| `--template` | | Filename template (e.g. `"{streamer} - {title} - {game} - part{n}"`) | `"{streamer} - {date} - {id} - part{n}"` |
| `--out` | `-o` | Target directory | `./downloads` |
| `--quality` | `-q` | Quality selector (`best`, `1080p60`, `720p60`, `audio`) | `best` |
| `--strategy` | `-s` | `auto`, `sections` (download only parts), `full` (download all, then cut) | `auto` |
| `--exact` | | Re-encode cut points for frame-exact cuts with ffmpeg | Disabled |
| `--format` | | Output container (`mp4`, `mkv`) | `mp4` |
| `--dry-run` | | Inspect metadata and print the cut plan without downloading | Disabled |
| `--chat` | | Download Twitch chat JSON | Disabled |
| `--chapters` | | Embed Twitch stream markers/chapters into video | Disabled |
| `--threads` | | Parallel segment download worker count | `8` |
| `--rate-limit` | | Bandwidth speed limit for yt-dlp (e.g. `5M`) | Unlimited |
| `--quiet` | | Suppress non-essential progress info | Disabled |
