# LuckyDownloader — Upgrades & Quality-of-Life Plan (2026-11)

> Status: **COMPLETE** (2026-11-13). Baseline HEAD `4fb1877`.
> Scope: meaningful UX, feature and architecture upgrades only. Bugs, security issues and regressions live in
> [`REVIEW_2026_11_V2.md`](REVIEW_2026_11_V2.md); where an upgrade depends on a bug fix, the finding ID is cited.

## Progress

Legend: `[ ]` not started, `[~]` in progress, `[x]` done. Proposal IDs: `U-<THEME>-NN`.
Template per proposal: ID / Title / Impact (`High`/`Medium`/`Low`) / Effort (`S`/`M`/`L`) / Current limitation
(`file:line`) / Proposed upgrade / Files affected / Acceptance criteria.

- [x] **1. Download & Queue Engine** (`U-DL-*`) — `core/` pipeline, workdirs, resume, formats, providers (`U-DL-01..06`).
- [x] **2. Persistence, Privacy, Updates & Diagnostics** (`U-DATA-*`) (`U-DATA-01..05`).
- [x] **3. Desktop UI, Queue UX & Timeline Editing Workflow** (`U-UI-*`) — `qt_ui/` (`U-UI-01..07`).
- [x] **4. Premiere CEP Integration** (`U-CEP-*`) — `premiere-plugin-cep/` (`U-CEP-01..06`).
- [x] **5. Developer Workflow, CI & Release** (`U-DEV-*`) (`U-DEV-01..03`).
- [x] **6. Headless CLI & Automation** (`U-CLI-*`) (`U-CLI-01..03`).
- [x] **7. Recommended Implementation Order** — quick wins vs. larger high-impact upgrades.

---

## Recommended Implementation Order

The 30 upgrade proposals below are sequenced into three delivery waves balancing `(Impact / Effort)`, unblocking prerequisites first (especially dependency hygiene and Premiere safety).

### Wave 1 — High-ROI Quick Wins (`Effort: S`, ~1–2 days total)

| Order | Proposal ID | Title | Impact | Effort | Why Do It First |
|---|---|---|---|---|---|
| 1 | `U-CEP-01` | Automatic sequence backup (`seq.clone()`) before destructive phases | High | S | 50 ms clone protects editors against destructive multi-hundred-cut timeline operations; directly activates the `backup: true` default in `markers-core.js`. |
| 2 | `U-DEV-01` | Atomic GitHub Release pipeline & parallel `build` / `build-cli` CI matrix | High | S | Eliminates half-published releases without `SHA256SUMS.txt` (`I-01`) and speeds up every future release build by ~35–40%. |
| 3 | `U-DEV-02` | Clean dependency split (`requirements-build.txt`) & slim CLI archives | Medium | S | Unblocks fast Colab installs (`pip install -r requirements-cli.txt`) and keeps `yt-dlp` present in dev/test CI runs (`I-02`, `J-02`). |
| 4 | `U-DEV-03` | Complete AST i18n scanner, `.po` mojibake guard & `t(..., **kwargs)` enforcement | Medium | S | Prevents silent encoding corruption (`H-01`) and missing `core/` stage translations (`H-02`) permanently in CI. |
| 5 | `U-DATA-04` | Privacy-hardened diagnostics bundle with scrubbing & preview | Medium | S | Makes `AboutDialog -> Export Diagnostics…` (once surfaced) safe for public GitHub issues and routes `Ctx.log()` into `luckydownloader.log` (`A-07`). |
| 6 | `U-DATA-03` | Privacy & data management controls («Save History» + «Clear Private Data») | Medium | S | Wires up the unused `enabled=` parameter on `history.record_download()` and respects privacy preferences across history/recent stores. |
| 7 | `U-UI-03` | Multi-select batch queue operations & URL drag-and-drop enqueue | Medium | S | Immediate queue ergonomics boost with zero architectural risk. |

### Wave 2 — Core Workflow & Reliability Multipliers (`Effort: M`, ~1–2 weeks)

| Order | Proposal ID | Title | Impact | Effort | Why Now |
|---|---|---|---|---|---|
| 8 | `U-DL-01` | Hardware-accelerated video encoding (`NVENC` / `QSV` / `AMF` / `VideoToolbox`) | High | M | 5–10× faster `cut_exact()` re-encoding with automatic `libx264` fallback. |
| 9 | `U-DL-02` | Smart Cut (keyframe-aligned GOP boundary splice) | High | M | Turns multi-minute exact VOD trims into multi-second boundary splices without quality loss in interior footage. |
| 10 | `U-CLI-02` | Full engine parity in `cli.py` (Twitch `--chapters`, playlists, archives) | High | M | Unlocks automated CLI/headless pipelines with full feature parity (`M-05`). |
| 11 | `U-CLI-01` | Unified parameterized `cli.py` (`cut-local`, `batch`) replacing root Colab scripts | High | M | Retires hardcoded `Vexoria` scripts (`M-01`) while bringing single-pass `split_copy` to local files. |
| 12 | `U-DATA-01` | OS Keyring / Windows DPAPI protection for Twitch OAuth & secrets | High | M | Removes plaintext OAuth tokens from `config.json` on disk (`C-06` follow-up). |
| 13 | `U-DATA-02` | Unified `JsonStore` with schema migrations, locks & rotated `.corrupt` backups | High | M | Eliminates per-module JSON boilerplate bugs (`G-01`..`G-04`). |
| 14 | `U-UI-01` | Per-row live speed, ETA & byte counters + aggregate status bar telemetry | High | M | Makes 2–4 concurrent downloads transparent and easy to monitor. |
| 15 | `U-UI-02` | Per-item log filtering & «Edit / Inspect Job» drawer in `QueueTab` | High | M | Stops interleaved parallel logs and lets users adjust failed jobs in place. |
| 16 | `U-UI-07` | Global Command Palette (`Ctrl+K`) & accessible About/Diagnostics entry point | Medium | M | Exposes `AboutDialog` / `export_diagnostics_bundle` (`D-04`) and speeds up power-user navigation. |
| 17 | `U-CEP-02` | Multi-track / linked overlay support (`V2` Chat Overlay & `A2..AN` Audio) | High | M | Unblocks Premiere auto-cutting for multi-track OBS recordings and rendered chat overlays. |

### Wave 3 — Flagship Editing, Capture & Polish Upgrades (`Effort: M–L`)

| Order | Proposal ID | Title | Impact | Effort | Notes |
|---|---|---|---|---|---|
| 18 | `U-DL-03` | Subtitle / CC downloading & SponsorBlock chapter integration | High | M | Richer non-Twitch workflows (captions + automatic chapter/segment markers). |
| 19 | `U-UI-06` | Unified bounded `QThreadPool` thumbnail & avatar loader | Medium | M | Eliminates per-widget thread explosions and duplicate thumbnail fetches. |
| 20 | `U-DL-04` | Polymorphic `Provider` contract & unified `detect_source` / `detect_provider` | Medium | M | Cleans up `source_info.py`/`download.py`/`finalize.py` platform branching (`B-02`, `B-04`). |
| 21 | `U-DL-05` | Intra-job parallel section downloading (`ThreadPoolExecutor` + multi-proc `Ctx`) | Medium | M | Cuts wall-clock time on 5–20 highlight section jobs from the same VOD. |
| 22 | `U-CEP-03` | Sequence Timeline marker placement & Highlight Subclip bin generator | Medium | M | Brings non-destructive subclip workflows and ruler markers to Premiere editors. |
| 23 | `U-CEP-04` | Interactive Clip & Chapter inspector with click-to-seek playhead | Medium | M | Lets editors inspect and cherry-pick `.markers.json` clips inside Premiere. |
| 24 | `U-CEP-05` | One-click «Import VOD & Build Sequence» bootstrap button | Medium | M | Cuts Premiere manual onboarding down to 1 click. |
| 25 | `U-DATA-05` | Signed & resumable app updater with cached installer reuse | Medium | M | Adds cryptographic update verification and resumes partial/already-staged updates. |
| 26 | `U-DL-06` | Live-stream capture mode (`--live-from-start` with graceful `finish_live()`) | Medium | M | Enables recording in-progress Twitch/YouTube streams safely. |
| 27 | `U-UI-05` | Multi-category selection & one-click «Split by Game Chapter» export | Medium | M | Ideal for variety-streamer VOD archiving into per-game uploads. |
| 28 | `U-CLI-03` | Crash-resumable Whisper transcription tool (`tools/colab/transcribe.py`) | Medium | M | Hardens and generalizes GPU transcription (`M-03`). |
| 29 | `U-CEP-06` | J/L audio crossfade / Constant Power transition at cut seams | Low | M | Eliminates audio click artifacts between hard stream cuts. |
| 30 | `U-UI-04` | Timeline playhead cursor, `I`/`O` hotkeys & 5s stream snippet preview | High | L | Flagship NLE-style auditioning right inside LuckyDownloader before downloading. |

---

## Proposals by theme


## Theme 1 — Download & Queue Engine (`U-DL-*`)

### [U-DL-01] Hardware-Accelerated Video Encoding (`NVENC` / `QSV` / `AMF` / `VideoToolbox`) for Frame-Exact Cuts
- **Impact:** High | **Effort:** M
- **Current Limitation:** `cut_exact()` (`core/finalize.py:568-578`) hardcodes CPU software encoding (`-c:v libx264 -preset veryfast -crf 18`). On 1080p60 or 1440p60 VODs, frame-exact cutting of long parts is CPU-bound, saturates all cores, and can take tens of minutes.
- **Proposed Upgrade:**
  1. Add a `detect_hw_encoder(ffmpeg_path: str) -> str` probe helper in `core/tools.py` (cached in `TOOLS_DIR / "versions.json"` keyed by `ffmpeg` binary mtime) that tests `h264_nvenc`, `h264_qsv`, `h264_amf`, and `h264_videotoolbox` against a 1-frame `nullsrc` encode (`ffmpeg -hide_banner -f lavfi -i nullsrc=s=128x128:d=0.04 -frames:v 1 -c:v <enc> -f null -`).
  2. Add `video_encoder: str = "auto"` (`"auto" | "cpu" | "nvenc" | "qsv" | "amf" | "videotoolbox"`) to `JobOptions` (`core/job.py`) and `DEFAULTS` (`core/settings.py`), with an Options selector under encoding settings.
  3. In `cut_exact()` (`core/finalize.py:552-581`), map the chosen encoder to quality-equivalent flags (e.g., `["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20"]` on NVIDIA, `["-c:v", "h264_videotoolbox", "-q:v", "65"]` on macOS) and fall back cleanly to `libx264` if the hardware encoder fails at runtime.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/tools.py`, `core/finalize.py`, `core/job.py`, `core/options.py`, `core/settings.py`, `qt_ui/tabs/options.py`.
  - **Acceptance Criteria:** `cut_exact()` selects the detected GPU encoder when `video_encoder="auto"`, logs the active encoder to `ctx.log()`, falls back automatically to `libx264` on hardware encoder failure, and passes unit tests mocking encoder probe and fallback.

---

### [U-DL-02] Smart Cut (Keyframe-Aligned GOP Boundary Splice) for Near-Instant Frame-Exact Trimming
- **Impact:** High | **Effort:** M
- **Current Limitation:** `compute_job_workdir()` (`core/finalize.py:129`) already references `keyframe_align`, yet the pipeline only offers coarse stream-copy (`split_copy` / `download_section_aligned`, which snaps to GOP/HLS boundaries up to 2–10 s away) or full re-encoding of 100% of frames (`cut_exact`).
- **Proposed Upgrade:**
  1. Add `probe_keyframes(path: Path, around_times: list[float]) -> list[float]` using `ffprobe -select_streams v:0 -skip_frame nokey -read_intervals <t-15>%+<30> -show_entries frame=pkt_pts_time -of csv=p=0`.
  2. When `opts.exact` is enabled on a downloaded `full` or `aligned` file (`core/finalize.py:843-847, 883-886`) and part duration exceeds 20 s, re-encode **only** the short leading stub `[part.start, first_keyframe]` and trailing stub `[last_keyframe, part.end]` with matching codec/profile/timebase, stream-copy `[first_keyframe, last_keyframe]`, and stitch them with `ffmpeg -f concat -safe 0 -c copy -movie_timescale 1000`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/finalize.py`, `core/download.py`, `core/premiere_export.py`.
  - **Acceptance Criteria:** Frame-exact cutting of a 1-hour part re-encodes only the boundary GOP stubs (< 15 s of footage), completes in seconds rather than minutes, preserves A/V sync and `MP4_MOVIE_TIMESCALE = 1000`, and falls back to `cut_exact` on short (< 20 s) parts or mismatched streams.

---

### [U-DL-03] Subtitle / Closed-Caption Downloading & SponsorBlock Chapter Integration
- **Impact:** High | **Effort:** M
- **Current Limitation:** `run_ytdlp()` (`core/download.py:352-410`) and `finalize_part()` (`core/finalize.py:393-431`) ignore subtitle tracks and SponsorBlock segments, preventing editors from grabbing `.srt` captions or marking sponsored/intro/outro segments on non-Twitch sources.
- **Proposed Upgrade:**
  1. Add `subtitles: bool = False`, `subtitle_langs: str = "en,es"`, and `sponsorblock_markers: bool = False` to `JobOptions` (`core/job.py`), `DEFAULTS` (`core/settings.py`), `build_options()` (`core/options.py`), and `OptionsTab`.
  2. Pass `--write-subs --write-auto-subs --sub-langs <subtitle_langs> --convert-subs srt` in `run_ytdlp()` when `subtitles=True` and move generated `.srt` sidecars alongside finalized output files in `finalize_part()`.
  3. Map `yt-dlp` chapters and SponsorBlock segments (`--sponsorblock-mark all`) in `_load_chapters()` / `parse_generic_source_info()` into `Chapter` objects so they are embedded into MP4/MKV containers and exported into `.markers.json` and Premiere XML.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/download.py`, `core/finalize.py`, `core/source_info.py`, `core/chapters.py`, `core/job.py`, `core/options.py`, `core/settings.py`, `qt_ui/tabs/options.py`.
  - **Acceptance Criteria:** Enabling subtitles writes `.srt` sidecars next to each finalized output part, and YouTube/generic sources with chapters or SponsorBlock segments emit matching MP4 chapters and `.markers.json` entries.

---

### [U-DL-04] Polymorphic Provider Pipeline Contract & First-Class Kick / TikTok / X Providers
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** `Provider` (`core/providers/base.py:22-50`) exposes only `name` and `capabilities`. Platform-specific checks (`_is_youtube_url`, `twitch_vod_id`, `use_aligned`) are scattered across `core/source_info.py`, `core/download.py`, and `core/finalize.py`, `detect_source()` (`core/providers/detect.py:124-130`) returns `GENERIC_PROVIDER` for all non-Twitch URLs (creating V2 bug `B-02`), and `GenericProvider.build_download_args` is dead code.
- **Proposed Upgrade:**
  1. Extend `Provider` (`core/providers/base.py`) with `extra_ytdlp_args(...)`, `supports_aligned_hls(src)`, and `normalize_site_id(raw_extractor)`.
  2. Move `youtube_extra_args()` into `YouTubeProvider`, move aligned HLS eligibility into `TwitchProvider`, and unify `detect_source()` / `detect_provider()` in `core/providers/detect.py` to return dedicated provider instances (`YOUTUBE_PROVIDER`, `TWITCH_PROVIDER`, `TIKTOK_PROVIDER`, `INSTAGRAM_PROVIDER`, `X_PROVIDER`, `KICK_PROVIDER`) with clean `site` routing.
  3. Retire unused `build_generic_download_args()` / `GenericProvider.build_download_args()` in favor of the shared `run_ytdlp()` pipeline.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/providers/base.py`, `core/providers/detect.py`, `core/providers/generic.py`, `core/providers/youtube.py`, `core/providers/twitch.py`, `core/source_info.py`, `core/download.py`, `core/finalize.py`.
  - **Acceptance Criteria:** Zero `_is_youtube_url` or hardcoded provider-name branches remain in `core/download.py` or `core/finalize.py`; `detect_source()` and `detect_provider()` return identical `Provider` instances for YouTube, Twitch, TikTok, Instagram, X, and Kick URLs.

---

### [U-DL-05] Intra-Job Parallel Section Downloading for Multi-Part `"sections"` Jobs
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** When cutting multiple highlight parts from a long VOD (`plan.strategy == "sections"`), `run_job()` (`core/finalize.py:865-895`) downloads and finalizes every part sequentially (`for i, p in enumerate(plan.parts):`), even though each part already writes into its own `workdir / f"part{part.index}"` directory (`core/download.py:546, 780`).
- **Proposed Upgrade:**
  1. Extend `Ctx` (`core/runtime.py:139, 185-202`) with `self._procs: set[subprocess.Popen]` guarded by `self._lock` so multiple child processes inside one job can register simultaneously and `ctx.cancel()` terminates all of them.
  2. In `run_job()` (`core/finalize.py:864-895`), when `len(plan.parts) > 1` and `opts.threads >= 2`, process up to `min(len(plan.parts), 3)` parts concurrently via `ThreadPoolExecutor`, dividing per-part threads/rate-limit cleanly and aggregating monotonic progress.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/runtime.py`, `core/finalize.py`, `core/download.py`.
  - **Acceptance Criteria:** Multi-part section jobs download up to 3 parts in parallel, `ctx.cancel()` terminates every active subprocess cleanly, and `run_job()` returns finalized paths ordered by `part.index`.

---

### [U-DL-06] Live-Stream & Growing-VOD Capture Mode (`--live-from-start` with Graceful Stop)
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** `parse_source_info()` (`core/source_info.py:383`) rejects streams without a positive duration, and `parse_hls_playlist()` (`core/download.py:673`) rejects playlists lacking `#EXT-X-ENDLIST`. Users cannot capture an ongoing Twitch or YouTube stream or cleanly stop and remux a live recording.
- **Proposed Upgrade:**
  1. Add `is_live: bool = False` to `SourceInfo` (`core/source_info.py`), allowing `duration == 0.0` when `info.get("is_live")` is true.
  2. Pass `--live-from-start --hls-use-mpegts` in `run_ytdlp()` when `is_live=True`.
  3. Add `Ctx.finish_live()` in `core/runtime.py` that sends `SIGINT` / `CTRL_BREAK_EVENT` and waits up to 10 s for clean container finalization before falling back to `kill_process_tree()`, enabling `finalize_part()` to remux captured footage into a Premiere-ready `.mp4` (`MP4_MOVIE_TIMESCALE = 1000`).
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/source_info.py`, `core/download.py`, `core/finalize.py`, `core/runtime.py`, `qt_ui/tabs/queue.py`.
  - **Acceptance Criteria:** `get_source_info()` accepts `is_live=True` metadata without raising `EngineError`, live capture runs `--live-from-start`, and calling `ctx.finish_live()` produces a playable `.mp4` output without raising `Cancelled`.

---

## Theme 2 — Persistence, Privacy, Updates & Diagnostics (`U-DATA-*`)

### [U-DATA-01] Store Twitch OAuth Tokens and `client_secret` in OS Keyring / Windows DPAPI with Automatic Migration
- **Impact:** High | **Effort:** M
- **Current Limitation:** `core/config.py:25-34` stores `access_token`, `refresh_token`, and `client_secret` in plaintext inside `config.json`. On Windows (`core/files.py:33`), `chmod_mode=0o600` is a no-op, and `migrate_from_legacy()` (`core/paths.py:114`) copies `config.json` without `0o600` on POSIX (V2 `G-02`).
- **Proposed Upgrade:**
  1. Encrypt Twitch secrets (`access_token`, `refresh_token`, `client_secret`) on Windows via `CryptProtectData` / `CryptUnprotectData` (`ctypes.windll.crypt32`, zero extra dependencies) and store/read them via `keyring` on macOS/Linux (falling back cleanly to `0o600` JSON when a keyring service is unavailable in headless environments).
  2. Keep non-secret fields (`client_id`, `user_login`) in `config.json`, transparently migrating any legacy plaintext tokens on first `load_config()`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/config.py`, `core/twitch_api.py`, `core/paths.py`, `tests/test_core_helpers.py`.
  - **Acceptance Criteria:** Newly saved Twitch tokens are not stored in plaintext in `config.json` on Windows/keyring-enabled hosts, legacy plaintext `config.json` migrates transparently on load, and existing mocked Twitch auth tests continue passing.

---

### [U-DATA-02] Unified `JsonStore` Abstraction with `schema_version` Migrations, Locks & Timestamped `.corrupt` Rotation
- **Impact:** High | **Effort:** M
- **Current Limitation:** Nine modules hand-roll JSON load/save logic (`settings.py`, `config.py`, `history.py`, `watchlist.py`, `recent.py`, `ui_state.py`, `updates.py`, `tools.py`, `queue_model.py`). Three omit `backup_corrupt_json()` (`G-03`), `backup_corrupt_json()` overwrites one static `.corrupt` file (`core/files.py:55`), `history.record_download()` has an unlocked read-modify-write race (`G-04`), and `_save_ui_state()` drops fields (`G-01`).
- **Proposed Upgrade:**
  1. Build a small, typed `JsonStore[T]` helper in `core/files.py` wrapping a per-path `threading.RLock()`, `atomic_write_json()`, an atomic `update(fn)` read-modify-write helper, and `backup_corrupt_json()`.
  2. Upgrade `backup_corrupt_json()` to write timestamped backups (`<name>.corrupt.<YYYYMMDD-HHMMSS>`) retaining the 3 newest copies.
  3. Support optional `schema_version` envelopes with registered migration hooks while staying backward-compatible with existing bare-list and unversioned dict files.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/files.py`, `core/history.py`, `core/watchlist.py`, `core/recent.py`, `core/settings.py`, `core/ui_state.py`, `core/updates.py`, `qt_ui/queue_model.py`.
  - **Acceptance Criteria:** All JSON stores back up corrupted files with rotation up to 3 copies, concurrent `history.record_download()` calls from 4 threads lose zero entries, and existing on-disk JSON files migrate without data loss.

---

### [U-DATA-03] Privacy & Data Management Controls («Save History» Toggle + One-Click «Clear Private Data»)
- **Impact:** Medium | **Effort:** S
- **Current Limitation:** `history.record_download(..., enabled=...)` (`core/history.py:86`) already exposes an `enabled` parameter that nothing ever sets, while `core/recent.py`, `settings["last_clip_url"]`, and `queue_state.json` unconditionally write visited URLs, search queries, and finished job metadata (V2 `G-05`) to disk.
- **Proposed Upgrade:**
  1. Add `save_history: bool = True` to `DEFAULTS` (`core/settings.py`) and expose it under a **Privacy & Data** card in `OptionsTab`.
  2. When `save_history` is `False`, skip recording entries in `luckytwitch_history.json`, `luckytwitch_recent.json`, `recent_searches.json`, and `last_clip_url`.
  3. Add a **Clear Private Data…** action in `OptionsTab` that clears download history, recent URLs, recent channel searches, and finished items in `queue_state.json` after user confirmation.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/settings.py`, `core/history.py`, `core/recent.py`, `core/finalize.py`, `qt_ui/tabs/options.py`, `qt_ui/queue_model.py`.
  - **Acceptance Criteria:** Toggling `save_history` off prevents new URLs/searches/downloads from being persisted across `finalize.py` and `MainWindow`; clicking «Clear Private Data…» leaves all four stores empty.

---

### [U-DATA-04] Privacy-Hardened Diagnostics Bundle (`export_diagnostics_zip`) with Scrubbing & Pre-Export Preview
- **Impact:** Medium | **Effort:** S
- **Current Limitation:** `setup_file_logging()` (`core/diagnostics.py:21-44`) captures raw `urllib3` debug URLs without capturing `Ctx.log()` lines (V2 `A-07`), and `export_diagnostics_zip()` (`core/diagnostics.py:82-113`) exports `luckydownloader.log` and `out_dir` / `provider_out_dirs` containing the user's real OS username and query-string tokens (V2 `C-05`).
- **Proposed Upgrade:**
  1. Route `Ctx.log()` into a dedicated `"luckydownloader"` logger while throttling `urllib3`/`PIL` loggers to `WARNING`.
  2. Add a text scrubber `_redact_text()` in `core/diagnostics.py` replacing `Path.home()` / `%USERNAME%` with `<USER_HOME>` and stripping sensitive URL query parameters (`token`, `sig`, `key`, `Policy`, `X-Amz-Signature`) in `luckydownloader.log`, `settings_redacted.json`, and `environment.json`.
  3. Add `persistence_health.json` (item counts + `.corrupt` backup file names without URLs/titles) and show the list of included zip entries before saving.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/diagnostics.py`, `core/runtime.py`, `qt_ui/dialogs.py`.
  - **Acceptance Criteria:** Exported `.zip` bundles include redacted `Ctx.log()` job traces, contain zero raw OS home paths or query tokens/signatures, and list `persistence_health.json`.

---

### [U-DATA-05] Signed & Resumable App Updater with Mandatory Hash Enforcement and Cache Reuse
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** `UpdateDialog._install_and_restart()` (`qt_ui/update_dialog.py:234`) omits `expected_sha256` when calling `updates.launch_installer()` (V2 `C-05`), falls back to launching unhashed assets when `SHA256SUMS.txt` has no digest, and re-downloads the entire installer even if an already-verified file exists in `DATA_DIR / "updates"`.
- **Proposed Upgrade:**
  1. Pass `expected_sha256=self.info.sha256, expected_size=self.info.asset_size` from `UpdateDialog._install_and_restart()` to `updates.launch_installer()` and require an explicit warning confirmation if `sha256` is unavailable.
  2. Optionally verify a detached signature (`SHA256SUMS.txt.minisig` / Ed25519) or Windows Authenticode signature before `subprocess.Popen`.
  3. On `UpdateDialog` open (`qt_ui/update_dialog.py:159-165`), check whether `DATA_DIR / "updates" / safe_tag / asset_name` already matches `verify_download(...)` and immediately switch the button to **Install and restart** without re-downloading.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/updates.py`, `qt_ui/update_dialog.py`, `tests/test_updates.py`, `tests/test_qt_update_dialog.py`.
  - **Acceptance Criteria:** `launch_installer()` always verifies `expected_sha256` when present, previously downloaded valid installers skip redundant transfers on reopen, and tampered cached files trigger a clean re-download.

---

## Theme 3 — Desktop UI, Queue UX & Timeline Editing Workflow (`U-UI-*`)

### [U-UI-01] Per-Row Live Speed, ETA & Byte Counters + Aggregate Status Bar Telemetry
- **Impact:** High | **Effort:** M
- **Current Limitation:** `QueueRunner.start` (`qt_ui/queue_runner.py:105-119`) only forwards a 0..1 progress float and short status string (`"42%"`), while a single shared `StatusBar` label flickers between parallel workers (`2–4` concurrent downloads). Users cannot see per-job transfer speed, ETA, or aggregate throughput.
- **Proposed Upgrade:**
  1. Parse download speed (`MiB/s`), ETA (`MM:SS`), and byte counts (`downloaded / total`) from `yt-dlp` and `ffmpeg` progress lines into structured fields on `QueueItem` (`qt_ui/queue_model.py`), delivered via Qt signals on `Bridge` (`qt_ui/bridge.py`).
  2. Render compact, tabular-numeral status pills (`14.2 MB/s · ETA 01:15`) inside `QueueRowDelegate.paint()` (`qt_ui/tabs/queue.py`) for active rows.
  3. Sum active worker speeds in `StatusBar` (`2 running · 28.4 MB/s`).
- **Files Affected & Acceptance Criteria:**
  - **Files:** `core/download.py`, `qt_ui/bridge.py`, `qt_ui/queue_model.py`, `qt_ui/queue_runner.py`, `qt_ui/tabs/queue.py`, `qt_ui/shell.py`.
  - **Acceptance Criteria:** Parallel queue rows show independent speed/ETA pills without GUI-thread model violations (`D-02`), and `StatusBar` displays stable summed throughput without flickering between workers.

---

### [U-UI-02] Per-Item Log Filtering & «Edit / Inspect Job» Drawer in `QueueTab`
- **Impact:** High | **Effort:** M
- **Current Limitation:** All concurrent jobs write into one shared `log_view` in `QueueTab`, interleaving lines across workers, and failed/waiting items cannot have their output folder, container, or cut points inspected or adjusted without re-fetching metadata and re-queuing.
- **Proposed Upgrade:**
  1. Attach a bounded `deque[str]` log buffer per `QueueItem` populated by `QueueRunner` / `Bridge`, and add a **Selected item** vs. **All jobs** filter chip above `log_view` (`qt_ui/tabs/queue.py`).
  2. Add context-menu actions (**Change Output Folder…**, **Load into Cut & Plan**) on waiting/failed/cancelled items so users can modify destination folders or cut ranges without re-running `get_source_info()`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `qt_ui/queue_model.py`, `qt_ui/queue_runner.py`, `qt_ui/tabs/queue.py`, `qt_ui/main_window.py`.
  - **Acceptance Criteria:** Selecting any queue row in «Selected item» mode filters `log_view` to that job's messages, and «Load into Cut & Plan» restores the job's `SourceInfo` and parts for editing.

---

### [U-UI-03] Multi-Select Batch Queue Operations & Direct URL Drag-and-Drop Enqueue
- **Impact:** Medium | **Effort:** S
- **Current Limitation:** `QueueTab.table` (`qt_ui/tabs/queue.py:422-463`) uses `SingleSelection`, forcing users with 20+ clips or playlists to retry, remove, or reorder queue items one by one, and dragging URLs from a browser requires going through Plan Tab individually.
- **Proposed Upgrade:**
  1. Switch `QueueTab.table` to `QAbstractItemView.SelectionMode.ExtendedSelection` (`Ctrl+Click`, `Shift+Click`, `Ctrl+A`) and update **Remove**, **Retry**, **Cancel**, and **Move Up/Down** handlers to act on all selected rows.
  2. Accept `text/uri-list` / `text/plain` drops (single or newline-separated URLs) directly on `QueueTab` to fetch metadata and batch-enqueue with current default options.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `qt_ui/tabs/queue.py`, `qt_ui/tabs/queue.py` tests (`tests/test_qt_queue_tab.py`).
  - **Acceptance Criteria:** Multi-selecting 5 rows allows batch Retry/Remove in one action, and dropping a list of URLs onto `QueueTab` enqueues each valid URL cleanly.

---

### [U-UI-04] Timeline Playhead Cursor, `I`/`O` Range Hotkeys & Instant 5s Stream Snippet Preview
- **Impact:** High | **Effort:** L
- **Current Limitation:** `Timeline` (`qt_ui/timeline.py`) displays storyboard sprites spaced 10–60 s apart and supports `S`, `Del`, `←`/`→`, `+`/`-`/`0`, but has no scrubbable playhead cursor, no `I`/`O` in/out trimming hotkeys, and no audio/video playback to audition exact cut boundaries before downloading.
- **Proposed Upgrade:**
  1. Add a draggable playhead needle on the `Timeline` time ruler; bind `I` / `O` keys to snap the selected part's start/end to the playhead position (and update `ShortcutsDialog` to match).
  2. Add a **Preview 5s** button in `TimelinePreviewCard` (`qt_ui/timeline_preview.py`) and `Space` keybind that resolves the HLS/direct stream URL (`get_playlist_url` / `yt-dlp -g`) and plays a 5-second snippet around the playhead in an embedded `QMediaPlayer` / `ffplay` modal.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `qt_ui/timeline.py`, `qt_ui/timeline_painters.py`, `qt_ui/timeline_preview.py`, `qt_ui/shell.py`, `core/download.py`.
  - **Acceptance Criteria:** Clicking the ruler positions the playhead, `I`/`O` snap part boundaries accurately with undo/clamp validation, and clicking «Preview 5s» plays audio/video at the cursor timestamp without blocking the GUI thread.

---

### [U-UI-05] Multi-Category Selection & One-Click «Split by Game Chapter» Export
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** Editors splitting multi-game variety VODs must manually place cut ranges around each Twitch category segment in `Timeline` (`qt_ui/timeline.py:372-395`) or click chapters one by one.
- **Proposed Upgrade:**
  1. Support `Shift+Click` multi-selection across category pills/bands in `Timeline` to create parts for multiple selected games at once.
  2. Add a **Split all game chapters into parts** toolbar action in `PlanTab` that clears/replaces parts from non-empty game chapters (`src.chapters`) and supports `{game}` / `{chapter}` tokens in per-part naming templates (`core/finalize.py`).
- **Files Affected & Acceptance Criteria:**
  - **Files:** `qt_ui/timeline.py`, `qt_ui/tabs/plan.py`, `qt_ui/tabs/plan_crop_controls.py`, `core/finalize.py`.
  - **Acceptance Criteria:** Clicking «Split all game chapters» generates one contiguous `Part` per game chapter with sanitized `{game}` filenames in `part_stem()`.

---

### [U-UI-06] Unified Bounded `QThreadPool` Thumbnail & Avatar Loader
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** Four widgets spawn independent daemon `threading.Thread`s (`VodStrip._fetch_thumbnail` in `qt_ui/shell.py:619-639`, `PlanPlaylistMixin._fetch_generic_thumbnail` in `qt_ui/tabs/plan_playlist_dialog.py:238-259`, `QueueTab._ensure_thumbnail` in `qt_ui/tabs/queue.py:818-837`, and `SearchTab._fetch_avatar_async` in `qt_ui/tabs/search.py:862-887`), risking unbounded thread spawns when restoring queues (`D-07`), duplicate network downloads for the same URL, and stale-URL paint races.
- **Proposed Upgrade:** Build a shared `ThumbFetcher` backed by a bounded `QThreadPool` (`maxThreadCount=4`) in `qt_ui/thumbs.py` that deduplicates in-flight URL fetches, validates `(widget_id, generation)` tokens before delivering `QPixmap` callbacks on the GUI thread, and populates restored queue items (`SessionPersistenceMixin._restore_queue_state`) without extra threads.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `qt_ui/thumbs.py`, `qt_ui/shell.py`, `qt_ui/tabs/plan_playlist_dialog.py`, `qt_ui/tabs/queue.py`, `qt_ui/tabs/search.py`, `qt_ui/session_persistence.py`.
  - **Acceptance Criteria:** Restoring a 50-item queue uses <= 4 concurrent image workers, duplicate URLs across `VodStrip` and `QueueTab` trigger one HTTP fetch, and rapid switching between VODs never flashes stale thumbnails.

---

### [U-UI-07] Global Command Palette (`Ctrl+K`) & Accessible About / Diagnostics Entry Point
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** `MainWindow.open_about_dialog()` (`qt_ui/main_window.py:203-205`) and `export_diagnostics_bundle()` (`qt_ui/dialogs.py:299-413`) have zero UI triggers (V2 `D-04` / V1 `L-03`), and Options/action discovery relies on scrolling through 1,088 lines of `OptionsTab`.
- **Proposed Upgrade:**
  1. Surface `MainWindow.open_about_dialog()` via an info button in `NavRail` (`qt_ui/shell.py`) and an **About & Diagnostics…** button in `OptionsTab`.
  2. Add a lightweight `Ctrl+K` Command Palette popup (`qt_ui/dialogs.py`) that fuzzy-searches Options settings, recent streamers, watchlist channels, and quick commands (`Get Info`, `Start Queue`, `Open Output Folder`, `Export Diagnostics Bundle`, `Check for Updates`, `Switch Language`).
- **Files Affected & Acceptance Criteria:**
  - **Files:** `qt_ui/main_window.py`, `qt_ui/shell.py`, `qt_ui/tabs/options.py`, `qt_ui/dialogs.py`.
  - **Acceptance Criteria:** Pressing `Ctrl+K` opens the palette, fuzzy-filtering jumps to or executes commands (including `Export Diagnostics…`), and clicking the new info button opens `AboutDialog`.

---

## Theme 4 — Premiere CEP Integration (`U-CEP-*`)

### [U-CEP-01] Automatic Sequence Backup (`seq.clone()`) Before Destructive Phases
- **Impact:** High | **Effort:** S
- **Current Limitation:** `DEFAULT_SETTINGS.backup = true` (`premiere-plugin-cep/src/markers-core.js:84`) and `ops.backup()` in `runRecipe()` (`markers-core.js:739-749`) belong to dead UXP code; neither `runner.js` nor `host.jsx` calls `app.project.activeSequence.clone()` before running hundreds of razor cuts and ripple deletes (V2 `F-04`). Stepping back via `Ctrl+Z` requires undoing hundreds of individual timeline edits.
- **Proposed Upgrade:** Add `LT_b_clone()` in `host.jsx` invoking `app.project.activeSequence.clone()` before the first cut or delete phase in **Do it all**, **Cut**, or **Delete the gaps**, gated by a **"Back up sequence before cutting"** toggle in Settings.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `premiere-plugin-cep/cep-panel/jsx/host.jsx`, `premiere-plugin-cep/cep-panel/js/runner.js`, `premiere-plugin-cep/cep-panel/index.html`, `premiere-plugin-cep/mock/run-mock-all.js`.
  - **Acceptance Criteria:** Running «Do it all» with backup enabled creates a cloned backup sequence in the Premiere Project panel before any razor cut occurs, and aborts cleanly before modifying the active sequence if cloning fails.

---

### [U-CEP-02] Multi-Track / Linked Overlay Support (`V2` Chat Overlay & `A2..AN` Multi-Track Audio)
- **Impact:** High | **Effort:** M
- **Current Limitation:** `LTGuard.evaluate()` (`premiere-plugin-cep/src/guard.js:130-149`) rejects any sequence containing clips on `V2..VN` or `A2..AN`. Editors who import LuckyDownloader's rendered Chat Overlay onto `V2` or record multi-track OBS audio (`A1` mix, `A2` VOD audio, `A3` mic) cannot cut or ripple-delete via the CEP panel.
- **Proposed Upgrade:** Add an opt-in **"Cut synced tracks (`V2`, `A2..AN`)"** setting in Settings; update `LTGuard.evaluate()` (`src/guard.js`), `ltCCut` (`host.jsx`), `ltDDel` (`host.jsx`), and `ltLink` to verify matching source ranges across all populated synced tracks, cut/ripple-delete them together in `runner.js`, and link surviving per-piece groups.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `premiere-plugin-cep/src/guard.js`, `premiere-plugin-cep/cep-panel/jsx/host.jsx`, `premiere-plugin-cep/cep-panel/js/runner.js`, `premiere-plugin-cep/cep-panel/index.html`, `premiere-plugin-cep/test/guard.test.js`.
  - **Acceptance Criteria:** Sequences with matching-length overlay/audio clips on `V2` / `A2` pass preflight when synced-track mode is enabled, cut and ripple-delete in lockstep with `V1`/`A1`, and keep zero frame drift across tracks.

---

### [U-CEP-03] Sequence Timeline Marker Placement Option & Highlight Subclip Bin Generator
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** The panel adds markers only onto the longest V1 `ProjectItem` (`host.jsx:23-30, 83-162`), while `mapItemsToTimeline()` (`premiere-plugin-cep/src/markers-core.js:494-522`) is unused. Once `V1` is split into pieces, clip markers duplicate across split instances rather than appearing cleanly at final cut positions on the sequence ruler, and highlight editors cannot generate reorderable subclips.
- **Proposed Upgrade:**
  1. Add a **"Marker target: Clip (`ProjectItem`) / Sequence Timeline"** choice in `index.html`; when `Sequence Timeline` is chosen during «Do it all», write markers onto `app.project.activeSequence.markers` *after* the Delete phase using `mapItemsToTimeline(items, keptRanges)`.
  2. Add a **"Create Highlight Subclips in Bin"** action calling `projectItem.createSubClip(...)` sorted by view count inside a `LuckyDownloader Highlights` bin.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `premiere-plugin-cep/cep-panel/jsx/host.jsx`, `premiere-plugin-cep/cep-panel/js/runner.js`, `premiere-plugin-cep/cep-panel/index.html`, `premiere-plugin-cep/src/markers-core.js`.
  - **Acceptance Criteria:** Sequence Timeline mode creates markers at post-ripple sequence positions matching YouTube chapter timestamps, and Subclip mode generates valid subclips inside the Project panel bin.

---

### [U-CEP-04] Interactive Clip & Chapter Inspector with Click-to-Seek Playhead
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** Once a `.markers.json` file loads, the CEP panel displays only `"Found (32 markers)"` (`runner.js` / `ui.js`). Editors cannot preview individual clip titles, view counts, or timestamps inside the panel, click to scrub Premiere's playhead to verify a moment, or toggle individual clips off before cutting.
- **Proposed Upgrade:** Add a collapsible **"Clips & Chapters (N)"** drawer in `index.html` / `ui.js` listing each parsed marker item with timestamp, duration, category/views, an include checkbox wired into `planCutSet()` (`runner.js`), and a click-to-seek handler invoking `app.project.activeSequence.setPlayerPosition(LTTime.framesToTicks(...))` in `host.jsx`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `premiere-plugin-cep/cep-panel/index.html`, `premiere-plugin-cep/cep-panel/js/ui.js`, `premiere-plugin-cep/cep-panel/js/runner.js`, `premiere-plugin-cep/cep-panel/jsx/host.jsx`.
  - **Acceptance Criteria:** Clicking a clip row jumps Premiere's CTI playhead to that frame, and unchecking items excludes them from subsequent Cut and Delete phases without editing `.markers.json` on disk.

---

### [U-CEP-05] One-Click «Import VOD & Build Sequence from `.markers.json`» Bootstrap
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** Before using the panel, editors must manually locate the downloaded VOD file next to `.markers.json`, import it into Premiere, create a matching sequence from the clip, and switch sequence display format away from drop-frame timecode (`F-04`).
- **Proposed Upgrade:** When preflight finds no active sequence (or an empty `V1`) while a sibling `.mp4`/`.mkv`/`.ts` matching `.markers.json` exists on disk, show an **"Import VOD & Create Sequence"** action in the preflight card that runs `app.project.importFiles(...)` + `app.project.createNewSequenceFromClips(...)` in `host.jsx` and configures non-drop-frame display.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `premiere-plugin-cep/cep-panel/jsx/host.jsx`, `premiere-plugin-cep/cep-panel/js/runner.js`, `premiere-plugin-cep/cep-panel/js/ui.js`.
  - **Acceptance Criteria:** Clicking the bootstrap button imports the matching video, opens a populated non-drop-frame sequence ready for preflight, and refreshes panel readiness automatically.

---

### [U-CEP-06] J/L Audio Crossfade / Constant Power Transition at Ripple-Delete Seams
- **Impact:** Low | **Effort:** M
- **Current Limitation:** Razor cuts and ripple deletes in `ltCCut` / `ltDDel` (`host.jsx:196-320`) create hard audio jump-cuts across every kept highlight, frequently slicing mid-waveform and producing audible pops/clicks between segments.
- **Proposed Upgrade:** Add an optional **"Add 2-frame audio crossfade at seams"** toggle in Settings that walks kept `A1` clip boundaries after `ltLink` via QE DOM and applies Premiere's default `Constant Power` audio transition (2–4 frames) across each interior edit point.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `premiere-plugin-cep/cep-panel/jsx/host.jsx`, `premiere-plugin-cep/cep-panel/js/runner.js`, `premiere-plugin-cep/cep-panel/index.html`.
  - **Acceptance Criteria:** When enabled, every interior edit seam on `A1` receives a short crossfade transition without changing clip timing or triggering `LTGuard` sync errors.

---

## Theme 5 — Developer Workflow, CI & Release Engineering (`U-DEV-*`)

### [U-DEV-01] Atomic Draft-to-Public GitHub Release Pipeline & Parallel `build` / `build-cli` CI Matrix
- **Impact:** High | **Effort:** S
- **Current Limitation:** `.github/workflows/build.yml:37-68, 173-329` publishes a live non-draft GitHub Release in `init-release` before any binary finishes compiling, uploads assets piecemeal per matrix leg, and blocks `build-cli` (`needs: [build]`) behind all GUI builds (V2 `I-01`). Meanwhile Nuitka cache keys omit `core/**` and `qt_ui/**`.
- **Proposed Upgrade:**
  1. Run `build-cli` in parallel (`needs: [test]`) alongside GUI `build` legs, and upload all artifacts from `build`, `build-cli`, and `plugin` via `actions/upload-artifact@v4`.
  2. Consolidate GitHub Release creation into one atomic `publish-release` job (`needs: [build, build-cli, plugin]`) that creates the release (or flips `draft: false`) only after generating `SHA256SUMS.txt` and verifying every expected platform artifact is present.
  3. Include `'core/**'` and `'qt_ui/**'` in Nuitka cache keys and smoke-test `LuckyDownloader-CLI --version`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `.github/workflows/build.yml`.
  - **Acceptance Criteria:** No partial release or missing `SHA256SUMS.txt` is ever visible under `/releases/latest` if a build leg fails, and tag-build wall-clock duration drops via parallel `build` + `build-cli`.

---

### [U-DEV-02] Clean Dependency Split (`requirements-build.txt`, Slim `requirements-cli.txt`) & Consistent CLI Archives
- **Impact:** Medium | **Effort:** S
- **Current Limitation:** `requirements-cli.txt:1-5` includes `nuitka`, `zstandard`, and `pillow` (slowing Google Colab installs and conflating build vs. runtime deps), `yt-dlp` lacks an upper bound and is missing from `requirements-dev.txt` (V2 `I-02`, `J-02`), `build_*_cli.*` bundles desktop `assets/` and `luckytwitch_engine`, and `build_windows_cli.bat:55` creates a flat zip without a top-level folder (`I-03`).
- **Proposed Upgrade:**
  1. Keep `requirements-cli.txt` to `requests` and bounded `yt-dlp`, move `nuitka` / `zstandard` into `requirements-build.txt`, and include `-r requirements-cli.txt` in `requirements-dev.txt`.
  2. Drop `--include-data-dir=assets=assets` and `--include-module=luckytwitch_engine` and add `--nofollow-import-to=PIL` in `build_*_cli.*`, and wrap `LuckyDownloader-CLI-windows.zip` inside a top-level `LuckyDownloader-CLI/` folder.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `requirements.txt`, `requirements-cli.txt`, `requirements-dev.txt`, `requirements-build.txt`, `build_windows_cli.bat`, `build_linux_cli.sh`, `build_mac_cli.sh`.
  - **Acceptance Criteria:** `pip install -r requirements-cli.txt` installs only `requests` + `yt-dlp`, CLI archives contain zero GUI icons, and extracting `LuckyDownloader-CLI-windows.zip` creates a single `LuckyDownloader-CLI\` directory matching Linux/macOS tarballs.

---

### [U-DEV-03] Complete AST i18n Scanner (`core/` Stage Sinks, `.po` Mojibake Guard & `t(..., **kwargs)` Enforcement)
- **Impact:** Medium | **Effort:** S
- **Current Limitation:** `tools/i18n.py:523-568` misses `ctx.stage`, `ctx.relabel`, `on_status`, and `+`-concatenated `ctx.log` calls in `core/` (V2 `H-02`), does not catch mid-word `?` encoding corruption (`locale/es/LC_MESSAGES/luckydownloader.po:3564`, `H-01`), and allows 59 `.format(...)` chains on `t(...)` that bypass `_fill()` (`H-03`).
- **Proposed Upgrade:**
  1. Teach `scan_source()` in `tools/i18n.py` to check `stage`, `relabel`, and `on_status` in `core/` and recurse across `ast.BinOp(op=ast.Add)` string expressions.
  2. Add a mojibake/? detector in `tools/i18n.py:message_problems()` plus an AST check flagging `.format(` chained directly onto `t()`/`_t()`/`tc()`, and migrate the 59 call sites to `t("...", key=val)`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `tools/i18n.py`, `core/i18n.py`, `core/finalize.py`, `core/tools.py`, `core/chat.py`, `locale/es/LC_MESSAGES/luckydownloader.po`.
  - **Acceptance Criteria:** `python tools/i18n.py check` fails on simulated `?` corruption, unwrapped `ctx.stage(...)` calls, and `t(...).format(...)` chains, and passes cleanly once existing sites are updated.

---

## Theme 6 — Headless CLI & Automation (`U-CLI-*`)

### [U-CLI-01] Unified Parameterized `cli.py` Subcommands (`cut-local`, `batch`) Replacing Hardcoded Root Colab Scripts
- **Impact:** High | **Effort:** M
- **Current Limitation:** Five root-level scripts (`colab_job.sh`, `cut_colab.py`, `cut_colab.sh`, `transcribe_colab.py`, `transcribe_colab.sh`) hardcode personal Drive paths (`/content/drive/MyDrive/VideosParaSubir/Vexoria`), VOD URLs, and 22 Zelda timestamps (`M-01`), shell wrappers run `git reset --hard origin/main` wiping local edits, `colab_job.sh` uses `mv *.mp4` + `rm -rf /tmp/* /root/.cache/*` (`M-02`), and `cut_colab.py` scans Drive FUSE once per cut without `.part` staging (`M-04`).
- **Proposed Upgrade:**
  1. Add a `--local-file <path>` (or `cut-local <file> -c "<cuts>" -o <dir>`) mode in `cli.py` powered by `core.finalize.split_copy` (or `cut_exact` with `--exact`), reusing existing time parsing, progress reporting, and `.part` staging.
  2. Add `--batch <tasks.json|tasks.txt>` in `cli.py` to execute multi-video download/cut manifests without editing Python source.
  3. Move generic, CLI-parameterized Colab shell wrappers into `tools/colab/` (`--url`, `--target`, `--cuts`, `--lang`) and update `docs/GOOGLE_COLAB.md`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `cli.py`, `tools/colab/`, `docs/GOOGLE_COLAB.md`, `tests/test_cli.py` (removing hardcoded root scripts `cut_colab.*` / `colab_job.sh`).
  - **Acceptance Criteria:** `cli.py cut-local <video.mp4> -c "0:00-1:00,2:00-3:00"` splits local files in one pass via `split_copy`, `--batch` executes multi-item manifests cleanly, and zero personal paths/URLs exist at repo root.

---

### [U-CLI-02] Full Engine Parity in `cli.py` (Twitch API `--chapters`, Playlists, `--download-archive`, Premiere Export & Fast `--dry-run`)
- **Impact:** High | **Effort:** M
- **Current Limitation:** `cli.py:331` instantiates `Job` without `client=make_client()` (silently breaking `--chapters` on every Twitch VOD, V2 `M-05`), runs `ensure_tools(ctx)` during `--dry-run` (`cli.py:264`), rejects playlist/channel URLs (`cli.py:267`), and omits `--download-archive`, `--premiere-xml`, `--premiere-json`, `--game-markers`, `--muted-markers`, and `--chat-render`.
- **Proposed Upgrade:**
  1. Pass `client=make_client()` into `Job` when `--chapters` or Twitch API features are requested (supporting `LUCKYDOWNLOADER_TWITCH_TOKEN` or `config.json` in headless environments).
  2. Expose `--download-archive`, `--items`, `--premiere-xml`, `--premiere-json`, `--game-markers`, `--muted-markers`, `--chat-render`, and `--no-update-tools` in `cli.build_parser()`.
  3. Expand playlist/channel metadata in `cli.py` via `parse_playlist_info` + `expand_playlist_jobs`, and skip `ffmpeg` / `yt-dlp` update network checks under `--dry-run`.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `cli.py`, `tests/test_cli.py`, `docs/GOOGLE_COLAB.md`.
  - **Acceptance Criteria:** `cli.py --chapters <twitch_vod>` embeds real Twitch chapters when credentials exist, `--dry-run` executes offline without touching `ensure_tools`, and playlists + `--download-archive` work end-to-end.

---

### [U-CLI-03] Crash-Resumable, Parameterized Whisper Transcription Tool (`tools/colab/transcribe.py`) with SRT/VTT/Chapter Output
- **Impact:** Medium | **Effort:** M
- **Current Limitation:** `transcribe_colab.py:49, 60, 95-198` hardcodes one creator's Drive path, a 5 GB minimum size, and `language="en"`, shares `/content/audio_chunks` across all videos (causing cross-video chunk mix-ups on interrupt), skips interrupted transcripts > 1,024 bytes permanently (V2 `M-03`), and `transcribe_colab.sh:49` introduces a trailing-`:` `LD_LIBRARY_PATH` (CWE-426).
- **Proposed Upgrade:**
  1. Move `transcribe_colab.py` to `tools/colab/transcribe.py` with full `argparse` flags (`--input-dir` / `--file`, `--output-dir`, `--model`, `--lang` defaulting to auto-detect, `--min-size-mb`, `--format txt,srt,vtt`).
  2. Isolate audio chunks per file (`/content/audio_chunks/<sha1>`) behind a `.extracted` sentinel, compute exact chunk offsets via `wave.open` / chunk duration rather than subtracting 44 header bytes, and write output incrementally to `.part` with checkpointing before atomic `os.replace`.
  3. Fix `LD_LIBRARY_PATH` expansion (`${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}`) in the Colab runner.
- **Files Affected & Acceptance Criteria:**
  - **Files:** `tools/colab/transcribe.py`, `tools/colab/transcribe.sh`, `docs/GOOGLE_COLAB.md`.
  - **Acceptance Criteria:** Killing and restarting transcription resumes cleanly on the interrupted video with zero cross-video chunk reuse, supports arbitrary languages and output formats (`txt`/`srt`), and leaves `LD_LIBRARY_PATH` free of empty path entries.
