## v2.13.0

LuckyDownloader **v2.13.0** is the official **Release 2**, bringing full support for importing entire playlists and channels, smart download routing with custom provider folders, and robust browser cookie security scoping.

### What's new in 2.13.0:
- **Playlists & Channels Import (Phase 6):**
  - Paste any playlist or channel URL (YouTube, etc.) to open the new **Playlist Picker Dialog**.
  - Select individual videos, use *Select all* / *Select none*, or specify item ranges (e.g. `1-10, 15, 20-25`).
  - Configure shared download options (Quality, Container format, Audio only, Destination folder, and Duplicate skipping).
  - Fast async thumbnail loading with clean YouTube fallbacks.
  - Large playlist safety confirmation before adding to queue.
- **Provider Folders & Download Routing (Phase 6b):**
  - **Group by provider subfolder (`provider_subfolders`):** Automatically organize downloads by platform under your download directory (e.g. `Downloads/YouTube/`, `Downloads/Twitch/`, `Downloads/TikTok/`).
  - **Custom folder per provider (`provider_out_dirs`):** Override the base download directory for specific platforms in Options (e.g. store Twitch VODs on one drive and YouTube videos on another).
  - **New Template Tokens:** Expose `{site}` and `{provider}` tokens for stream folder templates and file naming.
  - **Smart Folder Pre-population:** The Plan tab and Playlist dialog automatically pre-populate the destination folder with the detected provider's configured directory.
- **Cookie Security Scope & Per-Video Control:**
  - **Safe Domain Scope:** Browser cookies from Options are only shared with platforms that require or benefit from authentication (YouTube, TikTok, Instagram, X/Twitter), never leaking sessions to adult sites or arbitrary URLs.
  - **Per-Video & Playlist Cookie Toggles:** Easily toggle cookies on or off directly on the Plan tab details card (`Cookies (Browser)`) or when importing a playlist.
  - **Options Scope Setting:** Choose between *Only known platforms* (default & recommended) or *All supported sites*.
- **Quality & Error Fixes:**
  - Fixed YouTube age-restricted downloads failing with `HTTP Error 403: Forbidden` by serving HLS streams via Safari Web client extractor arguments.
  - Resolved quality detection allowing full 1080p and 720p downloads.
  - Added *Clear Queue* action with confirmation to quickly empty pending downloads.

## v2.12.1

LuckyDownloader **v2.12.1** is a patch release fixing video thumbnail aspect ratio rendering for vertical videos (YouTube Shorts, TikTok, Instagram Reels) and resolving an async thumbnail loading issue for generic video sources.

### What's new in 2.12.1:
- **Aspect Ratio Preservation for Vertical Videos:** Fixed video thumbnails for TikTok, YouTube Shorts, and Instagram Reels so they are no longer stretched into horizontal boxes. Thumbnails now preserve their natural aspect ratio centered cleanly in the Plan tab details card, the top VOD/video strip, and Queue rows.
- **Generic Video Thumbnail Loading:** Fixed a silent exception in the background thumbnail fetcher that prevented real thumbnails from displaying for YouTube and other non-Twitch video sources.

## v2.12.0

LuckyDownloader **v2.12.0** marks the official project rebranding from LuckyTwitch to **LuckyDownloader**, laying the foundation for broad multi-platform video downloading while maintaining seamless backward compatibility for existing users.

### What's new in 2.12.0:
- **Project Rebrand to LuckyDownloader:** Updated application identity, repository, window title, desktop launchers, and release packages to LuckyDownloader.
- **Zero-Loss Data Migration:** On first launch, existing settings, download history, streamer watch list, recent streamers, UI state, and managed tools are copied seamlessly from `%LOCALAPPDATA%\LuckyTwitch` (or platform equivalent) to `LuckyDownloader` without deleting or overwriting any data.
- **Seamless Upgrade Path:** Inno Setup installer preserves existing AppIds (`{6E2B6B0C-...}`), upgrading previous LuckyTwitch installations in place without leaving duplicate Add/Remove entries.
- **Dual Scheme Support (`luckydownloader://` & `luckytwitch://`):** Registered `luckydownloader://` as the primary URL scheme while retaining full support for legacy `luckytwitch://` links across Windows, macOS, and Linux.
- **Premiere Pro Plugin Compatibility:** The Premiere CEP panel and marker exporter now support both `luckydownloader-markers` and `luckytwitch-markers` formats. Releases provide both `LuckyDownloader-Premiere-Plugin-CEP.*` and legacy aliases.
- **Rebranded Distribution Packages:** Standalone builds, installers, AppImages, and DMG packages are now packaged under the `LuckyDownloader` name.

## v2.11.1

LuckyTwitch Downloader **v2.11.1** is a patch release fixing right-edge layout clipping in the Plan tab on macOS and narrow window sizes.

### What's new in 2.11.1:
- **Adaptive Clips Table Columns:** Table columns dynamically adapt to available card width, preventing card overflow in the Plan tab.
- **Optimized Window Geometry for macOS:** Adjusted launch dimensions (1040×860) and minimum size (950×560) to prevent macOS screen-clamping and preserve visibility of all action buttons and toggle switches.

## v2.11.0

LuckyTwitch Downloader **v2.11.0** introduces a dedicated **Interface** section in the Options tab for interface language and future appearance customizations.

### What's new in 2.11.0:
- **Dedicated Interface Section in Options:** Moved the Language selector from Tools into its own dedicated **Interface** section in the Options sidebar navigation.
- **Foundation for UI Customization:** Prepares the layout for future appearance and theme settings.
- **Full Localization:** Complete English and Spanish localization for the new section and card headings, with instant dynamic retranslation and bilingual settings search.

## v2.10.0

LuckyTwitch Downloader **v2.10.0** delivers complete, production-ready Spanish (Español) localization across the entire application, with zero untranslated strings, bilingual settings search, localized installer, and full Spanish documentation.

### What's new in 2.10.0:
- **100% Spanish Interface Localization:** Every tab (Plan, Search, Queue & Log, Options), all dialogs (Twitch API, Updates, Download History, First-run Welcome), menus, toasts, and status chips are fully translated into Spanish.
- **Backend & Engine Errors Localized:** All user-facing engine errors (`PlanError`, `EngineError`), worker progress, and output messages are localized into Spanish with zero unwrapped English literals remaining in the codebase.
- **Bilingual Settings Search:** In **Options**, you can now search using either Spanish terms (e.g. *descargas*, *carpeta*, *calidad*, *cortes*) or English keywords (e.g. *downloads*, *folder*, *quality*, *cuts*).
- **Dynamic Instant Language Switching:** Change language anytime in **Options → Interface → Language** (Auto / English / Español) with immediate live retranslation across all open views—no restart needed.
- **Localized Windows Installer & Linux Launcher:** The Inno Setup installer now provides full Spanish language selection and localized shortcut/protocol tasks; the Linux `.desktop` launcher includes Spanish descriptions.
- **Spanish User Documentation:** Added [`README.es.md`](README.es.md) with comprehensive Spanish documentation covering all features, shortcuts, and setup instructions.
- **Pseudo-Localization Mode:** Added `--lang pseudo` CLI flag and `LUCKYTWITCH_LANG=pseudo` environment variable to assist translators and QA in detecting layout clipping or unwrapped text.
- **Architecture & Guard Rails:** GNU gettext (`.po` / `.mo`) catalogs with automated CI hygiene checks ensuring placeholder consistency, accelerator alignment, and zero string drift.

## v2.9.2

LuckyTwitch Downloader **v2.9.2** makes the Spanish interface switch instantly and sets the base for finishing the translation (i18n phases I0 and I1).

### What's new in 2.9.2:
- **Language changes apply at once.** Switching language in **Options → Interface** no longer asks you to restart; the old "restart to apply" notice is gone.
- **Auto (system) language.** New installs follow the system language, and you can choose *Auto* again at any time. Detection now uses Qt's locale, which is reliable on Windows and macOS (the old check missed many Spanish systems).
- **Qt's own texts are translated too:** standard dialog buttons (OK / Cancel / Yes / No), context menus and file dialogs follow the interface language.
- **Numbers and dates follow the language:** file sizes and free disk space show `1,4 GB` in Spanish and `1.4 GB` in English.
- **Fixed:** the "No VOD loaded." line stayed in English after clearing a VOD or opening a link.
- **Translations moved to standard gettext catalogs** (`locale/`, editable with Poedit) with automatic checks for placeholders, punctuation, `&` accelerators and a Spanish glossary. No change for users.
- **Packaging:** every build bundles `locale/`, and the build workflow starts each packaged binary with `--i18n-selftest`, so a build that lost its translations fails instead of shipping in English.

## v2.9.1

LuckyTwitch Downloader **v2.9.1** temporarily disabled Spanish localization to prevent partial translations across the interface while the full gettext/PO translation architecture and coverage were finalized.

### What's changed in 2.9.1:
- Hotfix release locking interface language temporarily to English.

## v2.9.0

LuckyTwitch Downloader **v2.9.0** brings full interface internationalization with official Spanish (Español) localization (Phase F4).

### What's new in 2.9.0:
- **Spanish Interface Localization (Phase F4):**
  - Comprehensive Spanish translation catalog (`core/i18n.py`) covering all navigation rail tabs, command buttons, dialogs, status chips, table headers, and option settings.
  - Automatic first-run system language detection from OS locale (`LANG`/`LC_ALL` and `QLocale`).
  - Dedicated Language picker in **Options → Interface** allowing seamless switching between English and Español.
  - Strict placeholder verification suite ensuring all string format tokens remain identical across languages.

## v2.8.0

LuckyTwitch Downloader **v2.8.0** introduces parallel queue execution and configurable download bandwidth limits (Phase F3).

### What's new in 2.8.0:
- **Parallel Queue Execution (Phase F3):**
  - Multi-job queue concurrency selector (1 to 4 jobs at the same time) in the Queue tab toolbar.
  - Thread-safe coordinator and worker pool dynamically pulling waiting jobs from the queue model.
  - Isolated temporary directories preventing file collisions when downloading multiple streams or parts concurrently.
  - Granular cancellation: selecting an active running job and clicking Cancel stops only that job without cancelling other parallel downloads.
- **Bandwidth Speed Limiting:**
  - Integrated speed limit selector (`Unlimited`, `1 MB/s`, `2 MB/s`, `5 MB/s`, `10 MB/s`, `20 MB/s`) passing `--limit-rate` directly to yt-dlp.
  - Persisted in UI state so your bandwidth preferences are preserved across sessions.

## v2.7.0

LuckyTwitch Downloader **v2.7.0** introduces local download history tracking and a streamer watch list (Phases F1 and F2).

### What's new in 2.7.0:
- **Download History (Phase F1):**
  - Records every finished job locally in `luckytwitch_history.json` with VOD ID, title, streamer, date, parts count, output folder, and quality.
  - Visual `✓ Downloaded` pill badge on VOD cards in the Search tab and the loaded-VOD strip in the Plan tab.
  - Dedicated **Download History** dialog accessible from the command bar with quick actions to open target folders, re-load VODs directly into the Plan tab, and clear history.
  - Completely local and private: no data is sent anywhere.
- **Streamer Watch List (Phase F2):**
  - Pin favorite streamers directly in the Search tab using the pin button on channel headers.
  - Automatic background check for VODs newer than the last seen broadcast.
  - Visual notification badge on the Search navigation rail icon when unwatched VODs are detected.
  - Local watch list persistence (`luckytwitch_watchlist.json`) with safe error suppression.

## v2.6.2

LuckyTwitch Downloader **v2.6.2** fixes window un-maximize when dragging the custom title bar downwards and repairs the standalone 	ools/frameless_spike.py diagnostic tool.

### What's new in 2.6.2:
- **Title Bar Drag-to-Restore Fix:**
  - Resolved client area misalignment when pulling down a maximized window by querying native Win32 IsZoomed state instead of Qt's cached state during WM_NCCALCSIZE.
  - Added pure calculate_client_rect function ensuring client bounds match the window rectangle during native drag transitions and accurately align to the monitor work area when zoomed.
  - Query monitor bounds via MonitorFromRect based on proposed window bounds to support seamless transitions and multi-monitor setups.
  - Native state sync automatically updates the title bar restore/maximize button glyph immediately when Windows unmaximizes the window.
- **Repaired Diagnostic Spike Tool (	ools/frameless_spike.py):**
  - Resolved ModuleNotFoundError by inserting project root into sys.path.
  - Added app theme and application icon styling to faithfully reproduce application behavior.
  - Added --smoke flag for fast automated CI sanity tests and --debug flag for verbose Win32 message logging.
- **Frame Debugging:**
  - Added opt-in diagnostic logging enabled via LUCKYTWITCH_FRAME_DEBUG=1 or --debug.

## v2.6.1

LuckyTwitch Downloader **v2.6.1** fixes window edge and corner resizing, restores native window shadows and rounded corners, enables Windows 11 Snap Layouts, and adds cross-platform resize grips.

### What's new in 2.6.1:
- **Native 8-Way Edge & Corner Resizing:** Full resize capability across all 8 window edges and corners with accurate cursor feedback while preserving the 900x560 minimum size limit.
- **Native Window Shadow & Rounded Corners:** Thin DWM frame extension restores Windows 11 rounded corners and soft window drop shadows.
- **Aero Snap & Windows 11 Snap Layouts:** Native `WM_NCHITTEST` and `HTMAXBUTTON` handling enables edge-drag Aero Snap and the Windows 11 Snap Layouts menu on the maximize button.
- **Cross-Platform Edge Grips:** Fallback edge grip system calling `startSystemResize` ensures smooth window resizing on Linux, macOS, or when running with `--grips-only`.
- **Diagnostic Tool:** Added `tools/frameless_spike.py` for testing frameless window behaviors in isolation.

## v2.6.0

LuckyTwitch Downloader **v2.6.0** introduces a sleek custom window title bar (Phase W) matching the app's dark purple aesthetic with native window controls, maximize toggles, smooth dragging, and on-screen geometry clamp.

### What's new in 2.6.0:
- **Custom Dark Window Bar:** Replaced the OS title bar with a custom in-app bar (`CustomTitleBar`) styled in the dark Twitch theme (`#1e1f22`), featuring the app logo, title label, and custom-styled caption buttons (minimize, maximize/restore, close).
- **Interactive Caption Controls:** Includes responsive hover feedback with soft red (`#c42b1c`) on the close button, seamless double-click maximize/restore toggle, and drag-to-move window interaction.
- **Maximized State & Geometry Persistence:** Stored maximized state in `luckytwitch_ui.json` and added on-screen coordinate clamping to guarantee windows never restore off-screen across multi-monitor setups.
- **Native Frame Override:** Added `--native-frame` CLI argument and `custom_titlebar` setting toggle for users who prefer native OS decoration.
- **Vector Control Glyphs:** Added `window-minimize`, `window-maximize`, and `window-restore` vector icons rendered in code on the 24x24 grid.
- **Premiere Pro CEP Panel v0.15.0:**
  - **Limit to Chapter:** Select any individual game or chapter to restrict markers, cuts, and gap deletes strictly within that segment without deleting or modifying adjacent footage.
  - **Named Recipes:** Choose from built-in recipes ("Default", "Safety (5s)", "Tight Cut & Delete") or apply custom presets for padding, gap merging, and ripple limits.
  - **Preferences from Downloader:** Starting padding and safety values written into `.markers.json` by LuckyTwitch Downloader are automatically adopted by the panel until customized.
  - **Muted Markers Support:** Full validation and planning support for Twitch silenced audio segments (`kind: "muted"`).

## v2.5.0

LuckyTwitch Downloader **v2.5.0** completes the comprehensive engine modularization (Phase E), splitting the monolithic 3,715-line download engine into decoupled, focused core modules under `core/` with a clean DAG dependency structure while preserving 100% backward compatibility.

### What's new in 2.5.0:
- **Modular Core Architecture:** Decomposed `luckytwitch_engine.py` into 14 cohesive, single-responsibility modules in `core/`:
  - `core/errors.py`: Custom error hierarchy (`EngineError`, `PlanError`, `Cancelled`).
  - `core/timeutil.py`: Time parsing, duration conversions, and HMS formatting.
  - `core/planning.py`: Cut point parsing, split strategy selection, and plan generation.
  - `core/timeline.py`: Interactive timeline range and cut manipulations.
  - `core/twitch_api.py`: Device Flow authentication, clip retrieval, and Twitch API client.
  - `core/vod_search.py`: VOD searches, channel discovery, and thumbnail fetching.
  - `core/chapters.py`: Clips-to-chapters mapping, gap filling, and ffmetadata export.
  - `core/premiere_export.py`: Premiere XML marker generation and native `.markers.json` exporter.
  - `core/muted.py`: Muted audio segment parsing and HLS playlist inspection.
  - `core/source_info.py`: Media source metadata, storyboards, and format resolution.
  - `core/job.py`: Job descriptors and download execution options.
  - `core/runtime.py`: Execution context, process tree management, and tool path discovery.
  - `core/tools.py`: Tool lifecycle management for yt-dlp, ffmpeg, and TwitchDownloaderCLI.
  - `core/download.py`: HLS playlist parsing, segment extraction, and stream downloading.
  - `core/chat.py`: Chat downloading and video overlay rendering.
  - `core/finalize.py`: Audio/video part finalization, path templating, and job execution pipeline.
- **100% Backward-Compatible Facade:** `luckytwitch_engine.py` now serves as a lightweight ~200-line re-export facade preserving all 176 public symbols and test monkeypatch targets.
- **Safety Net Verification:** Added dedicated test coverage freezing the public engine surface (`tests/test_engine_exports.py`) and unit tests for core modules.
- **Zero Breaking Changes:** Full test suites (1,449 Python pytest tests and 130 Premiere CEP Node tests) pass cleanly without any regression.

## v2.4.0

LuckyTwitch Downloader **v2.4.0** introduces official native Linux packaging with standalone AppImage and portable tarball releases alongside optimized CI build workflows.

### What's new in 2.4.0:
- **Official Standalone Linux AppImage:** Added `LuckyTwitch-x86_64.AppImage` for one-click execution across modern distributions (Ubuntu, Fedora, Arch, openSUSE, SteamOS / Steam Deck) with zero root privileges or complex setup needed.
- **Portable Linux Tarball:** Added `LuckyTwitch-linux-x86_64.tar.gz` providing a self-contained portable directory distribution.
- **Desktop Environment Integration:** Bundled freedesktop `.desktop` entry with icon assets and protocol registration for `luckytwitch://` URLs.
- **Linux Update Discovery:** Update notifications seamlessly identify `.AppImage` and `.tar.gz` release assets and route directly to download links.
- **Optimized CI Pipeline:** Streamlined GitHub Actions build matrix, pruning legacy macOS Intel runners to dramatically accelerate release compilation times while testing across Python 3.12 and 3.14.

## v2.3.2

LuckyTwitch Downloader **v2.3.2** fixes standalone frozen binary detection so update checking and installed version discovery work seamlessly on packaged releases.

### What's new in 2.3.2:
- **Frozen Binary Detection (Nuitka):** Fixed an issue where standalone Nuitka builds did not set `sys.frozen`, causing packaged installations to report as a "Development build" and skip automatic update checks.
- **Robust Bundled Version Fallback:** Added direct fallback reading of `version.txt` alongside `sys.executable` when running in standalone mode.
- **Full Update Functionality:** Packaged installations now correctly display their version tag, perform background update checks, and present the update dialog for 1-click upgrades.

## v2.3.1

LuckyTwitch Downloader **v2.3.1** is a housekeeping and maintenance release preparing the project for upcoming platform builds and modularization.

### What's new in 2.3.1:
- **CI & Build Pipeline Maintenance:** Pruned retired migration branches from CI push triggers and added Python 3.14 to the automated test matrix alongside Python 3.12.
- **Repository Hygiene:** Removed obsolete leftover patch files (`progress-eta.patch`).
- **Documentation & Roadmap Indexing:** Added comprehensive documentation status tracking across all feature plans and established a unified documentation catalog (`docs/README.md`).
- **Backward Compatibility:** Zero user-facing behavior or setting changes; 100% compatible with existing downloads, settings, and Premiere Pro plugins.

## v2.3.0

LuckyTwitch Downloader **v2.3.0** introduces automatic update detection, in-place silent upgrades for Windows, and unified Premiere Pro CEP extension packaging.

### What's new in 2.3.0:
- **Automated GitHub Update Discovery:** Automatically checks GitHub releases in the background (throttled to once every 24 hours). Dev builds stay quiet automatically while allowing manual checks anytime.
- **Status Bar Update Pill & Toasts:** A subtle update pill appears in the bottom status bar when a newer release is detected, paired with a non-intrusive slide-in toast notification. Skipped releases are remembered so you are never pestered twice.
- **Dedicated Update Dialog:** A rich dialog presents the new release tag, currently running version, formatted release notes, and streamlined upgrade actions.
- **1-Click Silent Windows Upgrades:** On Windows installations, click **Update now** to download the setup package directly within the app. After strict SHA-256 integrity verification, LuckyTwitch runs the installer silently (`/SILENT /CLOSEAPPLICATIONS /RELAUNCH=1`) and relaunches seamlessly into the new version with all settings, credentials, and downloaded tools preserved.
- **Privacy & Settings Controls:** Added a dedicated **LuckyTwitch updates** card in **Options → Tools** with an automatic check toggle, version readout, and manual **Check now** button. Update checks are completely private: a single anonymous HTTPS GET without sending any user settings, paths, or identifiers.
- **Unified Premiere Pro CEP Extension:** The Premiere Pro integration has been consolidated into the modern CEP extension (`LuckyTwitch-Premiere-Plugin-CEP.zxp` and `.zip`), featuring 1-click drag-and-drop installation via ZXPInstaller or Anastasiy's Extension Manager alongside offline manual install scripts.

## v2.2.1

LuckyTwitch Downloader **v2.2.1** expands template tokens for both files and stream folders with broadcast date deconstruction, dominant game detection, duration tags, and resolution synonyms.

### What's new in 2.2.1:
- **Date Deconstruction Tokens:** Added `{stream_date}` (broadcast date), `{download_date}` (current download date), `{year}` (4-digit broadcast year), `{month}` (2-digit month), and `{day}` (2-digit day) to easily organize files and folders by air date.
- **Dominant Game / Category Tokens:** Added `{game}` and `{category}` tokens. For part files, it automatically detects the game with the longest duration during that specific part's time span; for stream folders, it detects the dominant game of the entire stream.
- **Duration Token:** Added `{duration}` token, formatting part lengths or total stream durations as standard tags (e.g. `01h30m00s`).
- **Quality & Resolution Tokens in Folders:** Added `{quality}` and `{resolution}` tokens to stream folder templates so different quality versions can be routed to separate subfolders.
- **Options Tab Token Chips & Previews:** Added clickable chips for all new tokens in **Options → Output** for both *File name* and *Stream folder name*, with live previews demonstrating real game segments and duration tags.

## v2.2.0

LuckyTwitch Downloader **v2.2.0** brings full stream quality selection, lossless audio-only extraction (.m4a / .mp3), real-time download size estimation, `{quality}` naming token support, and robust URL/input validation.

### What's new in 2.2.0:
- **Stream Quality Selector:** Choose any stream quality provided by Twitch (such as `1080p60 (Source)`, `720p60`, `480p`, etc.) or **Audio only** directly from the Plan tab's quality picker.
- **Real-Time Download Size Estimates:** The Plan tab preview now calculates and displays the estimated download size (e.g. `Quality: 720p60 · about 1.4 GB`) based on Twitch's declared stream bitrate.
- **Audio-Only Mode:** Extract and download audio directly without downloading the video stream. Audio can be saved as `.m4a` (lossless direct AAC stream copy with zero re-encoding) or converted to `.mp3` (192 kbps with ffmpeg for universal player compatibility). Chapters are preserved in both audio formats.
- **Default Quality & Audio Preferences:** Configure your preferred default quality and audio format in **Options → Output → Quality**. Each loaded VOD adopts your default quality automatically while remaining adjustable per VOD on the Plan tab.
- **`{quality}` File Name Token:** Added `{quality}` to the customizable file naming template chips in Options (e.g. `{streamer} - {date} - {id} - {quality} - part{n}`), making it easy to archive and distinguish different quality downloads of the same stream.
- **Intelligent URL & Drag-and-Drop Validation:** The app now validates pasted and dropped inputs before invoking yt-dlp. Accidental drags of multiline log text or invalid text now trigger a friendly warning instead of a yt-dlp crash dialog, and channel names are seamlessly redirected to the Search tab.

## v2.1.1

LuckyTwitch Downloader **v2.1.1** introduces intelligent title cleaning and manual title editing, smarter single-part file naming, and critical fixes for filename truncation and path previews.

### What's new in 2.1.1:
- **Clean Single-Part Naming:** File names now automatically omit ` - part1`, `_part1`, or `1of1` when a download only has a single part. MP4 video metadata title tags also write the clean title directly without adding redundant `(part 1/1)` tags.
- **Auto-Clean Stream Titles:** Automatically strips noisy Twitch chat bot commands (such as `!gsupps`, `!links`, `!clash`, `!merch`, `!discord`, `!drops`), promotional hashtags (`#ad`, `#sponsored`), and trailing delimiters left behind by streamers. Unicode emojis and pictographs are cleanly separated so words no longer merge together.
- **Auto-Clean Toggle Setting:** Added an **Auto-clean titles** toggle switch in **Options → Output**. Keep it enabled for clean file names, or switch it off anytime if you prefer raw Twitch stream titles verbatim.
- **Manual Title Editing in Plan Tab:** The stream title can now be edited directly from the **Plan tab** before queuing a download. Typing in the title field updates the loaded VOD strip, header info, and destination previews in real time. A **Reset** button allows restoring the original Twitch title in one click.
- **Fixed Filename Truncation on Titles with Periods:** Resolved a Python `pathlib.with_suffix()` bug where periods inside stream titles (e.g. `reactions. BIG ANNOUNCEMENT`) caused the downloader to treat the rest of the title as a file extension and discard it.
- **Fixed Destination Preview Extension:** Fixed a preview bug in the Options tab where container extensions were appended twice, causing `.mp4.mp4` in sample paths.

## v2.1.0

LuckyTwitch Downloader **v2.1.0** introduces a guided **First-Run Welcome & Quick Setup** experience alongside a comprehensive **60 FPS Motion System Upgrade** across the entire Qt 6 interface.

### What's new in 2.1:
- **First-Run Welcome & Quick Setup:** Guided full-bleed onboarding overlay for first launches. Choose your downloads folder, pick your preferred container format (`MP4` for universal video editor compatibility or `MKV` for crash resistance), and check your Twitch sign-in status in 5 seconds. Reopen anytime via the `F2` shortcut or `--welcome` CLI flag.
- **Dynamic Living Canvas:** Custom-painted ambient background with radial glow blending Twitch purple into emerald with an ongoing subtle breathing pulse loop.
- **60 FPS Motion System Core:** Rebuilt motion architecture featuring standardized duration tokens (`DURATION_MICRO`, `DURATION_FAST`, `DURATION_NORMAL`, `DURATION_ENTER`), `OutCubic` easing curves, and reusable motion helpers (`animate_opacity`, `animate_slide_and_fade`, `animate_value`, `animate_height`).
- **Tactile Micro-Interactions:** Modern spring-like knob stretch on toggle switches, subtle 1 px tactile depression padding on buttons, chips, and ghost controls, and smooth slide-and-fade tooltips.
- **Smooth Page & Shell Transitions:** Crossfade transitions between navigation tabs, animated reveal (0 → 48 px) and clear for the VOD strip, and animated onboarding card accordion on the Plan tab.
- **Dynamic Feedback & Visual Polish:** Indeterminate barberpole shimmer on downloading queue rows, breathing alpha pulse on red `LIVE` badges, smooth hover lifts on VOD cards, and smooth value tweening on progress meters.
- **Toast & Dialog Animations:** Slide-and-fade entries and dismissals for notification toasts with smooth vertical stack repositioning, plus animated accordion folds on dialog technical details.
- **Zero-Delay Accessibility Fallback:** Strict adherence to Windows `SPI_GETCLIENTAREAANIMATION` (reduced motion). When animations are disabled, all transitions resolve instantaneously without hanging timers.

## v2.0.0

LuckyTwitch Downloader now runs on **Qt 6 (PySide6)** with a completely reimagined, modern dark interface, crisp High-DPI vector iconography, and professional-grade workflow enhancements while preserving 100% backward compatibility with your settings, Twitch login, recent streamers, and Premiere Pro plugins.

### What's new in 2.0:
- **Reimagined Modern Dark Interface:** Designed from the ground up on Qt 6 with a full-height collapsible left navigation rail, unified command bar, quick VOD strip, and modern card layouts.
- **Custom Vector Iconography:** 33 bespoke vector icons rendered pin-sharp at any display resolution or High-DPI scaling factor.
- **Streamer Discovery & Rich VOD Views:** Instant streamer list with real Twitch profile avatars and bold red `LIVE` badges. Toggle between compact Table view and visual 16:9 Card Grid view with skeleton loading states, instant client-side title filter, and automatic infinite scrolling. Smart URL input automatically detects streamer handles and routes to Search.
- **Two-Column Responsive Plan Workspace:** Cut points and Clips view arrange side-by-side on wide screens. Interactive visual Part cards with game-colour stripes and smooth auto-looping marquee text for long titles. Instant strategy segmented control (`Auto`, `Full VOD + split`, `Only the parts`) and visual VOD coverage meter. Proportional view bars and one-click quick selection on clips.
- **Advanced Interactive Timeline:** Visual part pills with diagonal hatching for skipped sections, full-VOD overview minimap with draggable lens, interactive game legend chips with duration totals and isolate/highlight modes, green clip flags with hover metadata and auto-clustering, keyboard editing (`S` to split, `Delete`, arrow nudging, `Ctrl+Y` redo), non-blocking right-click context menu, and animated loading shimmer.
- **Rich Queue & Smart Collapsible Log Drawer:** Queue rows feature 16:9 storyboard thumbnails, bold titles, coloured status chips, in-row progress bars, and one-click `Open` buttons. Real-time summary header with grouped actions. Log drawer collapses to a 1-line colour-coded preview, auto-expands on errors, and adds severity filters (`All`, `Warnings`, `Errors`), log search, autoscroll pause, and log export. Thread-safe retry and live drag-and-drop / button reordering.
- **Searchable Options & Live Disk Space Preview:** Instant settings search filtering across all 7 sections with match counter and auto-expanding cards. Visual changed-from-default markers (`●`) with per-row Reset buttons and sidebar change count badges. Live output file path preview and real-time disk space gauge. Dedicated status rows for `yt-dlp` and `ffmpeg` with direct update actions.
- **Themed Modal Dialogs & Screen Reader Accessibility:** Replaced native OS message boxes with sleek dark themed dialogs featuring vector status icons, clean titles, user-friendly summaries, and expandable technical error folds with a one-click `Copy details` button. Full accessibility names and descriptions across all icon controls.
- **Seamless Upgrade from 1.x:** 100% drop-in replacement. Reads your existing `luckytwitch_settings.json`, `config.json`, and `tools/` folder. Backed by 731 automated Qt tests.

## v1.16.0

Draw the chat overlay from a chat file you already have. Nothing was removed and nothing works differently when you do not use it.

### Overlay from a saved chat
- **New button.** Options → Chat → **Draw the overlay from a saved chat** → *Choose chat file…*: pick a `name.chat.json` (saved earlier by this app or by TwitchDownloader) and the app draws `name.chat-overlay.mov` next to it, with the current overlay settings. Nothing is downloaded and neither the chat nor the video is touched. Before it starts you see what it will do: the streamer, the VOD, the stretch of the VOD the file covers, how many messages, the size, frame rate and type, and the name of the result. A file that is not a chat says why and nothing starts.
  - If `name.mp4` (or `.mkv`, `.mov`, `.ts`…) is next to the chat, the overlay takes its size and frame rate (unless you set them in Advanced).
  - If `name.markers.json` is next to it, the overlay is lined up to the fraction of a second, like a normal download. Without it, it is lined up to the whole second (up to 1 s ahead of the video if the part did not start on one). A `.markers.json` that belongs to another part is ignored.
  - It never overwrites an earlier overlay (a new one gets a number), and it runs in the background; **Cancel current** (Queue & log) stops it.
- **It needs internet** while it draws, to fetch emotes and badges from Twitch, BTTV, FFZ and 7TV (unless the chat was saved with the emotes embedded). A long chat can take from minutes to hours depending on the type.
- **Checked:** the real TwitchDownloaderCLI on a real chat file (offline, so without emotes) gave a 400 × 720, 30 fps overlay with an alpha channel, and the 0.4 s trim from a `.markers.json` was applied. **Not checked:** a full render with emotes and badges.
- **Tests:** 37 new tests (reading the chat file, finding the video and the `.markers.json`, the render itself, and the window), and every older test still passes.

## v1.15.0

The chat of each part as a video you can put over the footage in your editor. Nothing was removed and nothing works differently when you do not use it: the new option is off by default.

### Chat as a video (overlay)
- **New switch: Options → Chat → Chat as a video (overlay).** After each part is done, the app draws the chat of that stretch as a video next to it, called `name.chat-overlay.mov` (or `.mp4`). It works even if the stream had no chat on screen. In the editor, put it on the track above the video, at the start of the part, and place it where you want it. It is off by default.
- **How it is made.** With TwitchDownloaderCLI's `chatrender` (the same tool as the chat download). If the chat you save is a `.json`, that file is reused. If you save `.html` / `.txt`, or no chat at all, a temporary `.json` is downloaded and deleted when the overlay is finished.
- **Three types** (Options → Chat → Advanced → Overlay type). Sizes are for a very busy chat (3 messages a second, 400 × 1080), measured on a synthetic chat:
  - **Transparent · Animation, `.mov` (the default):** lossless, about **3.4 GB per hour**, about 7 times faster than real time in the test. Read by Premiere Pro and After Effects.
  - **Transparent · ProRes 4444, `.mov`:** the codec almost every editor knows, but about **28 GB per hour** and slower than real time. Use it if your editor does not read Animation.
  - **Black background · H.264, `.mp4`:** about **0.4 GB per hour**, not see-through. Set the clip's blend mode to **Screen** in the editor and the black disappears.
- **Advanced settings:** how it looks (outlined text with nothing behind it, or a dark semi-transparent panel), size (width × height; height 0 = the video's), text size, frame rate (like the video, 30 or 60) and smooth scrolling (redraws on every frame instead of 5 times a second; slower). Size and frame rate follow the real video by default.
- **Lined up with the part.** The overlay starts together with the part. The tool only trims in whole seconds, so the fractional part is corrected with ffmpeg (`-ss`); with the chat updating every 0.2 s, expect a tolerance of about 0.2 s. It can end up to a second after the part (ffmpeg's `-t` crashes the tool, so it is not used).
- **If it fails,** the video is still downloaded and the log says why. An unfinished overlay file is never left behind.

## v1.14.0

Links that open the app: any web page, document or program can now offer a link that opens LuckyTwitch Downloader with a VOD and its cut points already filled in. Nothing was removed and nothing works differently when you do not use it.

### Open a VOD from a link
- **New `luckytwitch://` links.** Clicking one opens the app (or brings the open window to the front; a second window never appears), goes to the **Plan** tab, fills in the VOD and the cut points, and presses **Get info** for you. For example: `luckytwitch://open?url=<VOD link>&cuts=0:20:00 to 3:30:00&label=My job` (values URL-encoded).
- **A link only fills in the form.** It never adds anything to the queue and never starts a download: you check the cut points and press the button. It cannot change settings, choose folders or file names, or run anything else.
- **Safe by design.** Only `http` and `https` addresses are accepted, never ones that point to your own computer or a private network, never with a user name or password, and every value is length-limited and stripped of control characters. A link the app cannot use shows a message saying why and changes nothing.
- **No mix-ups.** The VOD that was loaded is cleared first, so if the new one cannot be read, its cut points are never applied to the old one. If the app is still preparing yt-dlp and ffmpeg, or reading another VOD, the link waits and opens when it is free.
- **Windows:** the installer has a new option, ticked by default, that sets the links up for your user (no administrator rights). With the portable folder, or from source, press **Options → Tools → Links from web pages → Set up links**. The same card tells you when the links currently open another copy of the app and lets you take them over.
- **macOS:** the app bundle now declares the scheme, so links work once the app is in Applications. If a link does nothing, open the app once from Applications and try again.
- **For people who build pages:** the format is in `docs/link-format.md` (parameters, limits, what is refused, examples in HTML and JavaScript). Links have a version (`v=1`); parameters the app does not know are ignored, and a link made for a newer version asks the person to update.
- **How a second launch finds the open window:** it leaves the link as a small file in a `links` folder inside the data folder, which the open window checks twice a second. Nothing listens on the network.
- **Tests:** 48 new tests for the link format, the hand-off and the registration (with a stand-in for the Windows registry), and 17 more that drive the real window.

## v1.13.0

Muted audio (the parts Twitch silenced), feedback while «Get info» works, and a second Premiere Pro panel that does the whole edit in one button. Nothing was removed; the new option is off by default and the existing Premiere plugin is unchanged.

### Get info
- While «Get info» works the button reads **Loading...** (the dots move), the line under it says **Reading VOD info...**, and the bar at the bottom runs. Everything goes back when it finishes or fails. If a download is running, its progress bar is left alone.

### Muted audio
- «Get info» now also reads which stretches Twitch silenced (copyrighted audio) from the VOD's playlist. It is one extra small request; if it fails you simply see nothing.
- **Timeline:** a thin red line along the bottom of the game bars, a summary next to the zoom buttons (for example `25 stretches · 1:54:00 silenced by Twitch`), a note when you hover a muted stretch, and a **Show muted** switch to hide it. Cuts snap to the edges of muted stretches while it is on.
- **Parts list:** each part says how much of it is muted (`... · 0:09:00 muted`) and the line at the bottom adds up the total.
- **Premiere Pro:** new switch **Options → Premiere Pro → Muted audio**. With it (and the plugin `.markers.json` on) every `.markers.json` also lists the muted stretches of that part as `kind: "muted"` markers, in part time, cut at the part's edges. The file `version` is still 1, so the current plugin still opens these files and skips the markers it does not know; the plugin team can add the color later (see `docs/markers-format.md`).
- Single-clip downloads never get muted markers, like they never get the other extras.

### Premiere Pro: a second panel (CEP), the whole edit in one button
- **New panel: LuckyTwitch Markers (CEP)**, next to the existing UXP plugin, which is unchanged. Both read the same `.markers.json` and share the same planning code, so they plan exactly the same markers and cuts. Use the one you like, or install both. It lives in `premiere-plugin-cep/` and is on the release page as **`LuckyTwitch-Premiere-Plugin-CEP.zip`**.
- **Do it all.** One button, one confirm: it **adds the markers** to the video, **cuts** the timeline around every clip with the real razor (with the padding you choose, merging clips that are close), **deletes the gaps** with a ripple delete so the clips end up back to back, and **links video and audio** again. At the end it reads the whole result back from Premiere (pieces, audio in sync, no holes, length, links, markers) and only says *Done* if everything matches the plan. Measured on a real VOD plan (110 markers, 199 cuts, 100 deletes, 100 links): about 50 seconds.
- **Safe by design.** Before each step it reads the timeline again and refuses, saying why, if anything is off (other tracks in use, more than one clip on V1/A1, a trimmed or sped-up clip, drop-frame timecode, a markers file for another video, or a delete that would remove too much). After every chunk of work it checks the result, and the first failed check stops everything without retrying. **Stop** halts after the current chunk; pressing the button again **continues where it stopped**.
- **A panel that shows its plan.** Before you press anything it shows the markers file it found, what will happen (markers, cuts, deletes and links, with counts) and a rough time. While it runs there is a progress bar with one row per step, the time left, and a clear message at the end (done, stopped, cancelled or refused, with the reason). The log is there when you need it, with a **Copy log** button.
- **Single steps.** Markers only, cut only, delete only or link only, each with its own confirm and its own checks; a **Detailed check** that prints every safety check without touching anything; and **Remove the plan's markers**.
- **Settings:** keep N seconds before and after each clip, merge clips closer than N seconds, also cut at game changes, also add the markers, and the delete limits. They are remembered.
- **Install.** CEP panels are folders, not a single file like the `.ccx`: unzip and run `install.bat` (Windows) or `install-mac.command` (macOS), restart Premiere, and open **Window > Extensions > LuckyTwitch Markers**. The installer switches on Adobe's "allow unsigned panels" flag for you. See `premiere-plugin-cep/README.md`.
- **Which one?** The CEP panel needs a fresh sequence with the video alone on V1/A1 and does not make a backup copy (save the project first); in return it needs no empty tracks above and does everything in one go. The UXP plugin accepts any timeline, also one you already trimmed, and installs with a double-click. The comparison is in the CEP README.
- **Checked on:** Premiere Pro 26.5 on Windows. The macOS installer follows the same rules but has not been tried on a Mac yet.
- **Build:** the release workflow tests and packages the CEP panel in its own job (`plugin-cep`), and fails if its `markers-core.js` ever differs from the UXP plugin's.

## v1.12.0

This release updates the Premiere Pro plugin (0.5.0). The downloader itself is unchanged; existing downloads, settings and marker exports continue to work as before.

### Premiere Pro plugin

- **Cut at clips** and **Cut at chapters** add timeline cuts at clip markers or game/category changes from a `.markers.json` file.
- Cuts are mapped from the video's source time onto the timeline, so they work with footage that has already been trimmed or cut. The plugin targets the matching video, ignores points outside the played source range, and avoids adding cuts where one already exists.
- Choose how much footage to keep before and after clips, merge nearby clips, and make a backup sequence before cutting. The dry-run cut plan now matches the actual cut plan.
- A more compact panel shows the loaded marker file and the portion of the video present on the timeline, with live counts for the available cuts.
- Existing marker import and `.markers.xml` export remain available.

**Before cutting:** leave an empty video track and an empty audio track above the footage. Cutting uses multiple Premiere edits and has not yet been verified on a real Premiere project with multiple clips in one run. Keep the backup enabled and try it on a copy of your project first.

## v1.11.0

A redesign of the rest of the app, to match the new Options tab from v1.10. Nothing was removed and nothing works differently: saved settings, the queue and the files the app writes are the same as before.

### Search tab
- When you are not signed in, a purple banner says so and has a **Sign in...** button. Searching is switched off until you sign in.
- Every list explains itself while it is empty: what to do first, "nothing found for ..." after a search with no results, "this streamer has no VODs" with the reason, and "loading..." while a page is being fetched.
- The VOD header counts the videos (and says when there are more to load). "Double-click a VOD to use it" now sits next to the **Use this VOD** button.
- Results and Recent streamers are cards. Column headings line up with their columns.
- At the smallest window size the title above the VOD list wraps instead of squeezing the video-type drop-down.

### Plan tab
- The page is three cards: **Timeline**, **Cut points** and **Clips -> chapters**.
- The chapters option is a switch, like the ones in Options (the last checkbox in the app is gone).
- The **Add to queue** buttons and the one-line summary of your cuts stay visible at the bottom while you scroll. The summary turns red only while the cuts are wrong.
- Hints wrap to the width of their card, and the chapter column is wide enough for its title.
- The timeline's help line wraps instead of being cut off at the smallest window size.
- Keyboard: Tab now goes through the Plan tab from top to bottom and ends on **Add to queue**, then **Add & start** (before, the bottom bar came first).

### Queue & log tab
- Each job is coloured by its status, with a small icon in front: grey `○ queued`, purple `▶ running...`, green `✓ done (3 files)`, red `✕ failed`, amber `■ cancelled`.
- A one-line count sits above the list, for example "1 running · 2 queued · 1 done · 1 failed".
- An empty queue says "Nothing in the queue yet" and has a **Go to the Plan tab** button.
- The log is coloured: errors red, warnings amber, successes green, timestamps and "Queued:" lines muted.
- New **Copy log** and **Clear log** buttons under the log, handy for bug reports.
