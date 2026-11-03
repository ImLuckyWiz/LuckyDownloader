# Plan 07 — Priority 7: Architecture Refactors & Product Roadmap (`A-08`, `A-09`, `D-10`, `L-01`..`L-05`)

- **Priority:** 7 (Longer-term robustness features and structural refactors from Area L and maintainability findings `A-08`, `A-09`, `D-10`)
- **Findings Covered:** `A-08`, `A-09`, `D-10`, `L-01`, `L-02`, `L-03`, `L-04`, `L-05`
- **Recommended Model:**
  - **Steps 1 (`L-01`) & 2 (`L-03`):** Safe for **Gemini Flash**
  - **Steps 3 (`A-08`/`L-04`), 4 (`L-02`), 5 (`A-09`/`L-05`), 6 (`D-10`):** Recommended for **Argon or Claude Sonnet**

---

## Step 1 — Pre-Flight Disk-Space Check Before Starting Jobs (`L-01`, Low)

- **Model:** Gemini Flash
- **Files:** `core/finalize.py` (lines 575–595) and `core/source_info.py`
- **Goal:** Check `shutil.disk_usage(opts.out_dir).free` before launching `yt-dlp` so users get an immediate, clear error message when their drive is nearly full instead of failing hours later during the `ffmpeg` concat/remux step (`2x` temporary space needed for multi-segment jobs).

### Instructions for Step 1
1. In `core/finalize.py`, add a helper `check_disk_space(out_dir: str, required_bytes: int = 200 * 1024 * 1024) -> None`:
   ```python
   def check_disk_space(out_dir: str, required_bytes: int = 200 * 1024 * 1024) -> None:
       try:
           usage = shutil.disk_usage(out_dir)
       except OSError:
           return
       if usage.free < required_bytes:
           free_mb = usage.free // (1024 * 1024)
           need_mb = required_bytes // (1024 * 1024)
           raise RuntimeError(
               f"Insufficient disk space in {out_dir}: {free_mb} MB free, at least {need_mb} MB required."
           )
   ```
2. In `run_job()` (`core/finalize.py:579`), right after `os.makedirs(opts.out_dir, exist_ok=True)`, estimate `required_bytes`:
   - If the selected `FormatChoice` has `filesize > 0`, require `int(filesize * (2.1 if len(ranges) > 1 else 1.1))`.
   - Otherwise require a minimum floor of `200 * 1024 * 1024` (200 MB).
   - Call `check_disk_space(opts.out_dir, required_bytes)`.

### Verification
```powershell
pytest tests/test_finalize_unit.py tests/test_core_pipeline.py -q
```

---

## Step 2 — Rotating Log File and One-Click "Export Diagnostics Bundle" (`L-03`, Low / Old Audit A13)

- **Model:** Gemini Flash
- **Files:** `core/paths.py`, `luckytwitch_qt.py` (startup logging setup), `qt_ui/dialogs.py` (`AboutDialog`)
- **Goal:** Attach a `logging.handlers.RotatingFileHandler` writing to `paths.DATA_DIR / "logs" / "luckydownloader.log"` (`maxBytes=2_000_000`, `backupCount=3`) and add an **"Export Diagnostics..."** button in `AboutDialog` that zips the log file, redacted `settings.json`, `yt-dlp`/`ffmpeg` versions, and OS/Python info.

### Instructions for Step 2
1. Create a helper `setup_file_logging()` in `core/paths.py` (or a new `core/diagnostics.py` module):
   ```python
   import logging
   from logging.handlers import RotatingFileHandler

   def setup_file_logging() -> Path:
       log_dir = DATA_DIR / "logs"
       log_dir.mkdir(parents=True, exist_ok=True)
       log_file = log_dir / "luckydownloader.log"
       root = logging.getLogger()
       if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
           handler = RotatingFileHandler(
               log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
           )
           handler.setFormatter(
               logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
           )
           root.addHandler(handler)
           root.setLevel(logging.DEBUG)
       return log_file
   ```
2. Add `export_diagnostics_zip(dest_zip: Path) -> Path` in `core/diagnostics.py` that writes:
   - `system_info.json` (`sys.version`, `platform.platform()`, `APP_VERSION`, `yt-dlp --version`, `ffmpeg -version` first line).
   - `settings_redacted.json` (`load_settings()` with cookie paths and tokens redacted).
   - `logs/luckydownloader.log` (if present).
3. Add an `"Export Diagnostics..."` button to `AboutDialog` (`qt_ui/dialogs.py`) that opens `QFileDialog.getSaveFileName` and calls `export_diagnostics_zip`.

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_qt_smoke.py -q
```

---

## Step 3 — Deterministic Resumable Work Directories & Stale Workdir Cleanup (`A-08` & `L-04`, Medium/Low)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Changing how `.luckytwitch_*` work directories are named and cleaned up interacts with `Plan 01 Step 3 (A-01)` and `yt-dlp --continue` behavior. Assign this step to **Argon or Claude Sonnet**.

- **Files:** `core/finalize.py` (lines 578–587, 730–736) and `qt_ui/main_window.py`
- **Instructions:**
  1. Compute a deterministic job hash from `(src.site, src.id, opts.fmt_id, tuple(ranges), opts.reencode)` so each distinct job gets `.luckydownloader_work_<id_slug>_<hash8>`. Two jobs with different cut ranges get different hashes (solving `A-01`), while retrying the *exact same* job after a crash/cancel reuses its partial `.part` / `.ytdl` files (`yt-dlp --continue`).
  2. Add `cleanup_stale_workdirs(out_dir: str, max_age_hours: float = 48.0) -> int` in `core/finalize.py` that scans `out_dir` for `.luckytwitch_*` and `.luckydownloader_work_*` directories older than `max_age_hours` and removes them when no queue is active, plus a `"Clean temporary files"` button in the Options tab.

---

## Step 4 — Automatic Queue Persistence & Crash/Update Recovery (`L-02`, Low)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Queue persistence touches `QueueTableModel`, `MainWindow._save_session`, and startup initialization. Assign this step to **Argon or Claude Sonnet**.

- **Files:** `qt_ui/main_window.py`, `qt_ui/queue_model.py`, `core/paths.py`
- **Instructions:**
  1. Add `QUEUE_STATE_FILE = DATA_DIR / "queue_state.json"` in `core/paths.py`.
  2. Whenever queue items are added, removed, reordered, or change status (`pending`, `running`, `done`, `error`, `cancelled`), atomically write all `pending` and `running` items (re-marking `running` as `pending` in the serialized snapshot) using `MainWindow._serialize_queue()` and `atomic_write_json`.
  3. On startup (`MainWindow.__init__`), if `QUEUE_STATE_FILE` contains non-empty pending items, prompt or restore them into `self.queue_model`.

---

## Step 5 — Decouple `core/` From `sys.modules.get("luckytwitch_engine")` (`A-09` & `L-05`, Medium/Low)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 5 with Gemini Flash. Dozens of unit tests in `tests/test_core_pipeline.py`, `tests/test_download_unit.py`, `tests/test_source_info_unit.py`, and `tests/test_finalize_unit.py` monkeypatch attributes on `luckytwitch_engine` (`eng.which_or_hint`, `eng.run_logged`, `eng._run_ytdlp_json`, `eng.download_full`, `eng.download_section`). Refactoring this requires updating or shimming those test fixtures in lockstep. Assign to **Argon or Claude Sonnet**.

- **Files:** `core/tools.py`, `core/download.py`, `core/source_info.py`, `core/finalize.py`, `core/chat.py`, `core/muted.py`, `luckytwitch_engine.py`, `tests/`
- **Instructions:**
  1. Introduce a `PipelineDeps` dataclass (or explicit keyword callables with defaults pointing to the real `core.*` functions) in `core/finalize.py` and `core/download.py`.
  2. Have `luckytwitch_engine.run_job` pass its own module attributes into `core.finalize.run_job(..., deps=...)` so legacy tests that monkeypatch `luckytwitch_engine` continue to work without `core/*` ever importing or inspecting `sys.modules["luckytwitch_engine"]`.

---

## Step 6 — Split Qt UI God-Modules (`D-10`, Low)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Splitting 1,400–2,100 line PySide6 classes (`qt_ui/main_window.py`, `qt_ui/tabs/plan.py`, `qt_ui/timeline.py`) requires preserving all signal/slot attributes and test introspection hooks (`tests/test_qt_main_window.py`, `tests/test_qt_smoke.py`). Assign to **Argon or Claude Sonnet**.

- **Files:**
  - `qt_ui/main_window.py` (1,547 lines) -> extract `qt_ui/session_persistence.py`, `qt_ui/update_controller.py`, and `qt_ui/watchlist_controller.py`.
  - `qt_ui/tabs/plan.py` (2,163 lines) -> extract `qt_ui/tabs/plan_playlist_dialog.py`, `qt_ui/tabs/plan_Crop_controls.py`, and `qt_ui/tabs/plan_storyboard.py`.
  - `qt_ui/timeline.py` (1,480 lines) -> extract `qt_ui/timeline_painters.py` and `qt_ui/timeline_ preview.py`.


---

## Step 7 — Plan 07 Final Review, Release Notes, Commit & Tag (`v2.15.0`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 7 with Gemini Flash. Final architectural review, full test verification, `RELEASE_NOTES.md` authoring, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.15.0`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Architectural Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_07` (`A-08`, `A-09`, `D-10`, `L-01`..`L-05`). Verify all module imports, PyInstaller/Nuitka packaging hooks (`tests/test_qt_packaging.py`), and i18n catalogs.
  2. **Run Full Verification Suite:**
     ```powershell
     python tools/i18n.py build
     python tools/i18n.py check
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.15.0`.
     - **Public-Facing Language:** Ensure notes are written for end users (new features, user diagnostics, resilience, reliability) without internal jargon, plan IDs, or audit codes.
     - Prepend a `## v2.15.0` section at the top of `RELEASE_NOTES.md` summarizing the new features and architectural improvements from Plan 07 (pre-flight disk-space check, rotating log file & one-click Diagnostics Bundle export, deterministic resumable work directories & stale workdir cleanup, automatic queue crash/update recovery, decoupled `core/` pipeline dependencies, and modularized Qt UI components).
  4. **Commit & Tag Release `v2.15.0`:**
     - Mark Step 7 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.15.0): complete Plan 07 architecture refactors and robustness features`, and create annotated tag `git tag -a v2.15.0 -m "LuckyDownloader v2.15.0"`.
