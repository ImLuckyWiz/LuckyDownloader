# LuckyDownloader

Download Twitch VODs (or any link yt-dlp supports) and cut them into parts by timestamps, with optional chapters built from the VOD's Twitch clips. Runs on Windows, macOS, and Linux.

*Read this in Spanish: [README.es.md](README.es.md)*

## Download

Get the latest version from the [Releases](../../releases) page:

| System | File |
| --- | --- |
| Windows | `LuckyDownloader-Setup.exe` |
| macOS (Apple Silicon: M1, M2, M3, M4) | `LuckyDownloader-macos-arm64.dmg` |
| Linux (x86_64) | `LuckyDownloader-x86_64.AppImage`, `LuckyDownloader-linux-x86_64.tar.gz` |
| Headless CLI (All OS) | `LuckyDownloader-CLI-windows.zip`, `LuckyDownloader-CLI-macos-arm64.tar.gz`, `LuckyDownloader-CLI-linux-x86_64.tar.gz` |

### Install

- **Windows:** run the installer. It installs for your user only (no admin rights needed) and adds a Start menu entry. Running a newer installer updates an existing install in place. Existing LuckyTwitch installations and settings are preserved and migrated automatically on upgrade.
- **macOS:** open the `.dmg` and drag **LuckyDownloader** onto the **Applications** shortcut. To update, drag the new version over the old one and choose **Replace** (close the app first).
- **Linux:** make the AppImage executable (`chmod +x LuckyDownloader-x86_64.AppImage`) and run it (`./LuckyDownloader-x86_64.AppImage`). On Ubuntu 24.04+, if FUSE is not installed, install `libfuse2t64` (`sudo apt install libfuse2t64`) or extract it (`./LuckyDownloader-x86_64.AppImage --appimage-extract`). A portable directory archive (`LuckyDownloader-linux-x86_64.tar.gz`) is also available.

### First launch

- **macOS:** the app is not notarized by Apple. Right-click it → **Open** → **Open** (only once). If macOS says the app is damaged, run `xattr -cr /Applications/LuckyDownloader.app` in Terminal.
- **Windows:** SmartScreen may warn about an unknown publisher. Click **More info** → **Run anyway**.
- The app needs internet on first run: it downloads **yt-dlp** and **ffmpeg** by itself. yt-dlp is kept up to date automatically.
- **Upgrading from LuckyTwitch:** your existing settings, download history, watch list, recent streamers, UI layout, and tools are copied over automatically without deleting your previous files.

## Using it

1. Paste a VOD URL or ID (or drag and drop a link into the window) and press **Get info**.
2. Write the cut points, for example `0:00 - 30:00 - 1:30:00 - end` (consecutive parts). Use `;` or a new line to skip gaps: `0:00 - 30:00 ; 2:00:00 - end`. Times can be `H:MM:SS`, `MM:SS`, seconds or `1h30m`. Or use the **Timeline** above the text box: click the thumbnails to cut, drag a cut line to move it, right-click it to remove it, click a part to skip it, double-click a game bar to make that game its own part. The mouse wheel zooms, **Undo** takes back the last edit. The text and the timeline always match.
3. Choose the download strategy (**Auto** picks whichever is cheaper: full VOD then split, or only the parts), then start the job.

### Finding a VOD (Search tab) and Watch List

Instead of pasting a link you can search for a streamer: open the **Search** tab, type a name and press Enter (or enter/drop a streamer name directly into the URL bar on the Plan tab to jump straight to search). Pick a channel to see its VODs with thumbnails (past broadcasts, highlights or uploads), then double-click one (or press **Use this VOD**) and it is loaded in the Plan tab. The streamers you open are remembered under **Recent streamers**. Searching needs the Twitch sign-in described below; if you are not signed in, the tab shows a **Sign in…** button.

- **Streamer watch list:** Click the **Pin streamer** button on any channel header to add them to your watch list. The app periodically checks for broadcasts newer than the last one seen and displays a notification badge on the Search tab. It never downloads automatically.
- **Download history:** Press the **History** button in the top command bar to view your past downloads, complete with date, streamer, title, parts count, quality, and destination folder. You can reopen any folder or reload the VOD into the Plan tab with one click. VOD cards in Search and the Plan strip display a `✓ Downloaded` badge with the date.
- **Editing stream titles:** You can edit the stream title directly on the **Plan tab** before queuing a download. A **Reset** button restores Twitch's original title at any time.
- **Auto-clean titles:** In **Options → Output**, *Auto-clean titles* automatically strips bot commands (`!links`, `!gsupps`), promo hashtags (`#ad`), and emojis so your files have clean names. You can toggle this off if you prefer raw titles.
- **Clean single-part naming:** When a download has only one part, redundant ` - part1` tags are automatically omitted from file names and video metadata.

### Queue, Parallel Downloads & Speed Limit

The **Queue & log** tab manages and runs queued jobs:

- **Parallel downloads:** In the Queue tab, choose how many jobs run concurrently (from **1 job** up to **4 parallel jobs**). Jobs download in parallel with isolated temporary folders to prevent collisions.
- **Granular cancellation:** If multiple jobs are running, selecting a specific row and pressing **Cancel current** stops only that download while leaving other parallel jobs running.
- **Bandwidth limit:** Set an optional speed limit (**Unlimited**, **1 MB/s**, **2 MB/s**, **5 MB/s**, **10 MB/s**, **20 MB/s**) passed directly to yt-dlp (`--limit-rate`) to prevent saturating your internet connection.
- **Retry and reordering:** Easily reorder waiting downloads with Move Up / Move Down, or retry failed and cancelled jobs in one click.

### Interface & Custom Window Bar

- **Language (Español):** LuckyDownloader is fully localized in English and Spanish. On first run, it automatically detects your system language. You can also manually switch languages anytime in **Options → Interface → Language**.
- **Custom dark window bar:** The window uses a custom dark purple title bar matching the app's aesthetic, with responsive minimize, maximize/restore, and soft-red close buttons, smooth window dragging, and geometry recovery. To use your operating system's native window frame instead, launch with `--native-frame` or toggle it in UI settings.

### Quality and Audio only (Twitch VODs)

When you load a Twitch VOD, a **Quality** picker appears on the Plan tab:

- **Quality choices:** Choose any quality Twitch provides (e.g. `1080p60 (Source)`, `720p60`, `480p`, etc.) or **Audio only**. The preview displays the estimated download size based on declared bitrate.
- **Default quality:** Configured in **Options → Output → Quality** (`Best available` by default). Each loaded VOD uses this default unless changed on the Plan tab.
- **Audio-only format:** In Options, choose between `.m4a` (copies Twitch's native AAC audio directly without re-encoding, fast and lossless) or `.mp3` (re-encoded to 192 kbps via ffmpeg for universal playback).
- **Video-only extras skipped:** When downloading audio only, video-dependent extras (frame-exact cuts, Premiere XML/JSON markers, game markers, and chat video overlays) are automatically skipped.
- **File naming:** You can add the `{quality}` token to your file name template in Options (e.g. `{streamer} - {date} - {id} - {quality} - part{n}`) to distinguish quality variants.

### Clip chapters (optional)

The Search tab and clip chapters need a Twitch session. The app can build chapters from a VOD's Twitch clips, filtered by views, duration or top N. To sign in:

1. Press **Twitch API…** → **Sign in with Twitch**.
2. A code appears and `twitch.tv/activate` opens in your browser. Enter the code and authorize.

This uses Twitch's Device Code Flow with a public app, so there is no client secret and you do **not** need a Twitch developer account. Advanced users can still enter their own Client ID / Secret in the same window.

### Game markers for Premiere Pro (optional)

In **Options → Chapter details**, tick *Also mark the game / category changes*. Each part (or the full VOD) then gets a `.markers.xml` next to it with one marker per game, named `GAME: <game>` and spanning the whole stretch (for example `GAME: Just Chatting` from 0:00:00 to 1:00:00, then `GAME: Resident Evil 2`). Import it in Premiere with **File → Import**. The game list comes from Twitch through yt-dlp, the same data the Timeline shows as colored bars. It works with or without the clip markers (they share the same file when both are ticked). Premiere's XML import has no marker color, so the `GAME:` prefix is what tells them apart from the clip markers.

### Premiere Pro panel: colored markers and automated timeline edits (optional)

The `.markers.xml` above is limited by what Premiere's XML import understands: no marker colors, and it brings in a separate sequence. For more, tick **Options → Chapter details → Also export a .markers.json for the Premiere plugin**. Each part (or the full VOD) then gets a `.markers.json` next to it, and the Premiere Pro CEP panel imports it as colored markers: game changes in one color, clips colored by their views, with the creator and link in the comment. It is independent of the XML option, so you can use either or both. The game markers option applies to both files.

The panel lives in [`premiere-plugin-cep/`](premiere-plugin-cep) and is available on the release page in two packages:
- **`LuckyDownloader-Premiere-Plugin-CEP.zxp`**: 1-click install using ZXPInstaller, Anastasiy's Extension Manager, or aescripts manager.
- **`LuckyDownloader-Premiere-Plugin-CEP.zip`**: Manual install with `install.bat` (Windows) or `install-mac.command` (macOS), which configures Adobe's unsigned panels flag automatically.
*(Legacy `LuckyTwitch-Premiere-Plugin-CEP.*` file names continue to be provided for backward compatibility).*

The CEP panel offers the whole edit in one button with the real razor: it adds the markers, cuts around every clip (with padding), deletes the gaps, links video and audio again, and checks the whole result against the plan. See [`premiere-plugin-cep/README.md`](premiere-plugin-cep/README.md) and [`docs/markers-format.md`](docs/markers-format.md).

- **Limit to chapter:** Pick any individual game or chapter to restrict markers, cuts, and gap deletes strictly inside that segment without touching the rest of the timeline.
- **Named recipes:** Choose from built-in presets (*Default*, *Safety (5s)*, *Tight Cut & Delete*) or apply custom recipes for padding and ripple limits.
- **Preferences inheritance:** Default padding and safety limits configured in LuckyDownloader are automatically adopted by the panel.
- **Muted audio markers:** Silenced audio stretches are mapped directly as colored markers on the timeline.

### Muted audio (Twitch VODs)

Twitch silences copyrighted audio in a VOD. When you press **Get info** the app reads which stretches were silenced (from the VOD's playlist; it is one extra small request, and if it fails you just see nothing) and shows them:

- **Plan tab → Timeline:** a thin red line along the bottom of the game bars, a line under the buttons saying how many stretches and how much time (`25 stretches · 1:54:00 silenced by Twitch`), and a hover note on the red parts. The **Show muted** switch hides the red line; cuts also snap to the edges of muted stretches while it is on. Zoom in to see the shorter ones clearly.
- **Plan tab → part list:** each part says how much of it is muted (`Part 2: 1:30:00 → 2:30:00 (1:00:00) · 0:24:00 muted`), and the line at the bottom adds up the total.
- **Premiere Pro:** tick **Options → Premiere Pro → Muted audio** (with the plugin `.markers.json` option on) and each `.markers.json` also lists the muted stretches of that part as `muted` markers. The plugin chooses their color. See [`docs/markers-format.md`](docs/markers-format.md).

Twitch silences whole segments, so a red stretch can be a little longer than the song itself; it is exactly what is silent in the downloaded file.

### Chat download (optional, Twitch VODs only)

In **Options → Chat**, tick *Also download the chat of each part*. The first time, the app downloads [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) (MIT license, pinned to one tested version) into the tools folder. Each part then gets a chat file next to it, `name.chat.json` (or `.txt` / `.html`), covering exactly the stretch of the VOD that the part covers. Notes:

- Inside the `.json`, message times count from the **start of the VOD**, not from the start of the part. The file's `start` and `end` say which stretch it covers.
- Chat times are whole seconds, so expect up to a second of difference against the video.
- If the chat cannot be downloaded (deleted VOD, no internet...), the video is still downloaded and the log says why.
- *Embed emotes and badges* makes the file bigger but lets it render offline.

### Chat as a video (overlay, optional, Twitch VODs only)

In **Options → Chat**, tick *Chat as a video (overlay)*. After each part, the app draws its chat as a video next to it: `name.chat-overlay.mov` (or `.mp4`). It works even if the stream had no chat on screen. In your editor, put it on the track above the video, at the start of the part, and place it where you want it. It uses the same TwitchDownloaderCLI (`chatrender`). If the saved chat is a `.json` it is reused; otherwise a temporary one is downloaded and deleted at the end.

Choose the type in **Advanced → Overlay type** (sizes for a very busy chat, 3 messages a second at 400 × 1080):

| Type | Size per hour | Notes |
|---|---|---|
| Transparent · Animation `.mov` (default) | ~3.4 GB | Lossless, fast. Read by Premiere Pro and After Effects. |
| Transparent · ProRes 4444 `.mov` | ~28 GB | Most compatible, but huge and slower than real time. |
| Black background · H.264 `.mp4` | ~0.4 GB | Not see-through: set the clip's blend mode to *Screen* and the black disappears. |

Also in Advanced: the look (outlined text, or a dark semi-transparent panel), size, text size, frame rate and smooth scrolling. Size and frame rate follow the video by default. Notes:

- The overlay starts together with the part (about 0.2 s tolerance) and can end up to a second after it.
- **Already have the chat?** In **Options → Chat**, press *Choose chat file…* next to *Draw the overlay from a saved chat* and pick a `name.chat.json`. The overlay is drawn next to it with your current overlay settings, with no download. If `name.mp4` is next to the chat it gives the size and frame rate, and if `name.markers.json` is there the overlay is lined up to the fraction of a second. This is the way to try another size or text size on a part you already downloaded.
- It needs internet while it draws, to fetch emotes and badges (Twitch, BTTV, FFZ, 7TV), and a long part can take from minutes to hours.
- If it fails, the video is still downloaded and the log says why.
- Not yet verified: opening it in Premiere Pro, and speed and size on a multi-hour VOD (the figures above come from a synthetic chat).

### Open a VOD from a link (web pages and other programs)

A web page, a document or another program can offer a `luckydownloader://` (or legacy `luckytwitch://`) link. Clicking it opens the app (or brings the open window to the front) with the VOD and the cut points already filled in on the **Plan** tab, and reads the VOD for you. A link only fills in the form: it never adds to the queue and never starts a download, so you still check the cut points and press the button yourself.

- **Windows:** the installer registers both `luckydownloader://` and `luckytwitch://` schemes. If you use the portable folder, or run from source, press **Options → Tools → Links from web pages → Set up links**.
- **macOS:** it works once the app is in Applications. If a link does nothing, open LuckyDownloader from Applications once and try again.
- Your browser may ask whether to open LuckyDownloader the first time.

Making a page that offers such a link? The format is in [`docs/link-format.md`](docs/link-format.md).

## Where things are stored

| What | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Settings, Twitch login, history, watch list | `%LOCALAPPDATA%\LuckyDownloader` | `~/Library/Application Support/LuckyDownloader` | `~/.local/share/LuckyDownloader` |
| yt-dlp and ffmpeg | `...\LuckyDownloader\tools` | `.../LuckyDownloader/tools` | `~/.local/share/LuckyDownloader/tools` |
| Downloads (default) | `Videos\LuckyDownloader` | `~/Videos/LuckyDownloader` | `~/Videos/LuckyDownloader` |

The data folder also holds a small `links` folder and a `running.beat` file: they are how a second launch (a clicked link) hands its link to the window that is already open.

Uninstalling the app leaves this data folder in place; delete it for a clean removal. To reinstall ffmpeg, delete `ffmpeg` and `ffprobe` from the `tools` folder and restart the app.

## Headless CLI & Google Colab

LuckyDownloader includes a headless command-line interface (`cli.py`) with zero GUI dependencies, ideal for servers, scripts, and **Google Colab**:

```bash
# Install lightweight CLI requirements (no PySide6 needed)
pip install -r requirements-cli.txt

# Download specific parts using cut points syntax
python cli.py "https://www.twitch.tv/videos/123456789" \
    --cuts "0:00:00 - 1:18:55 - end" \
    --out "./downloads" \
    --quality best
```

See [docs/GOOGLE_COLAB.md](docs/GOOGLE_COLAB.md) for a ready-to-use Google Colab notebook workflow with Google Drive mounting.

## Run from source

```
pip install -r requirements.txt
python luckytwitch_qt.py
```

Python 3.10+ is required. When run from source, settings and downloads stay next to the scripts.

## Build it yourself

Nuitka compiles native standalone binaries, so build each system on that system.

- **Windows:** run `build_windows.bat [version]` → `dist\LuckyDownloader\LuckyDownloader.exe`, plus `dist\LuckyDownloader-Setup.exe` if [Inno Setup 6](https://jrsoftware.org/isdl.php) is installed. To build the headless CLI only, run `build_windows_cli.bat [version]`.
- **macOS:** run `./build_mac.sh` → `dist/LuckyDownloader.app` and `dist/LuckyDownloader-macos-<arch>.dmg`. It also installs the app into Applications on that Mac. The result matches the Mac's chip (Apple Silicon or Intel). To build the headless CLI only, run `./build_mac_cli.sh [version]`.
- **Linux:** run `./build_linux.sh [version]` → `dist/LuckyDownloader-x86_64.AppImage` and `dist/LuckyDownloader-linux-x86_64.tar.gz`. To build the headless CLI only, run `./build_linux_cli.sh [version]`.

## Development

```
core/                       modular core engines (download, finalize, runtime, planning, chapters, history, i18n, etc.)
luckytwitch_engine.py       lightweight backward-compatible facade re-exporting core modules
luckytwitch_qt.py           the Qt 6 app entry point
qt_ui/                      Qt 6 UI components (main_window, shell, tabs, timeline, widgets, icons)
weblink.py                  luckydownloader:// links: reading them, handing them to the open window, registering the scheme
tests/                      pytest suite
premiere-plugin-cep/        the Premiere Pro panel (CEP): reads .markers.json and edits the whole timeline (JavaScript, own tests)
docs/                       file format notes (markers-format.md, link-format.md)
```

Run the tests:

```
pip install -r requirements-dev.txt
python -m pytest
```

The Premiere panel has its own tests (`cd premiere-plugin-cep && npm test`, Node 20+, no dependencies). The engine tests need nothing else. The Qt GUI tests run automatically offscreen on both desktop and headless CI environments.

## Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) downloads the videos (Unlicense).
- [FFmpeg](https://ffmpeg.org) cuts them (builds from [yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds) on Windows, static builds on macOS).
- [TwitchDownloader](https://github.com/lay295/TwitchDownloader) by lay295 and contributors downloads the chat (MIT). It is downloaded on demand, not bundled.

LuckyDownloader is not affiliated with Twitch Interactive, Inc., TwitchDownloader or yt-dlp.

## Notes

- The ffmpeg builds the app downloads are GPL. That is fine for personal use; follow the GPL terms if you redistribute them.
- yt-dlp breaks now and then when Twitch changes things. The app updates it on launch, so restarting it is usually enough.
- **Update check:** LuckyDownloader checks GitHub releases once per day to notify you of new versions. The request is anonymous (a single HTTPS GET with no settings, paths, or identifiers sent). You can toggle this off at any time under **Options > Tools > Updates**. On Windows installs, updates can be downloaded and installed in place seamlessly with verified SHA-256 integrity.
- **Intel macOS (`x86_64`):** Prebuilt macOS releases target Apple Silicon (`arm64`); Intel Mac users can run from source or build locally with `bash build_mac.sh`.

## License

LuckyDownloader is distributed under the terms of the [MIT License](LICENSE).
