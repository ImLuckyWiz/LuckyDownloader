# Remediation Plans — Master Index (`REVIEW_2026_11.md`)

This index maps **all 67 findings (`A-01`..`L-05`)** from [`docs/REVIEW_2026_11.md`](./REVIEW_2026_11.md) into **7 priority-ordered execution plans** (`PLAN_01` through `PLAN_07`), with **7 dedicated releases (`v2.14.1` through `v2.15.0`)**—one at the end of each plan.

> [!IMPORTANT]
> **Model Selection & Relay Rules (Gemini Flash vs. Argon / Claude Sonnet):**
> 1. Follow the **Execution Progress Tracker** below in strict top-to-bottom order. Never skip ahead over an unchecked `[ ]` step.
> 2. **Gemini Flash** may ONLY execute steps labeled `[Model: Gemini Flash]`. As soon as the next unchecked `[ ]` step is labeled `[Model: Argon / Claude Sonnet]` (including the final Release step at the end of each plan), **Gemini Flash must STOP immediately** and ask the user to switch to Argon / Claude Sonnet.
> 3. **Argon / Claude Sonnet** may ONLY execute steps labeled `[Model: Argon / Claude Sonnet]`. As soon as the next unchecked `[ ]` step is labeled `[Model: Gemini Flash]`, **Argon / Claude Sonnet must STOP immediately** and ask the user to switch back to Gemini Flash.
> 4. After finishing any step and passing its tests, immediately change `[ ]` to `[x]` in the tracker below before checking the next step.
> 5. **Public Release Notes Guideline:** When authoring `RELEASE_NOTES.md` during a release step, keep notes user-facing, clear, and professional. Do NOT include internal project tracking jargon (such as audit finding codes `A-01`, `G-02`, plan names like `Plan 01`, or internal architectural review IDs). Focus on user impact, bug fixes, performance, and new features.

---

## Execution Progress Tracker (Step-by-Step Relay Checklist)

### Plan 01 — [`docs/PLAN_01_CRITICAL_DATA_PIPELINE_AND_WATCHLIST.md`](./PLAN_01_CRITICAL_DATA_PIPELINE_AND_WATCHLIST.md) -> Release `v2.14.1`
- [x] **Plan 01 - Step 1** (`G-01`): Fix `check_all_watchers` never saving updated watchlist — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 2** (`G-03`): Fix substring matching and empty-string bug in watchlist lookup — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 3** (`A-01`, `A-02`): Sanitize `src.id` and scope work folder per job with nonce — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 4** (`A-05`): Guard `download_section_aligned` against non-Twitch sources — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 5** (`A-03`): Wire `JobOptions.download_archive` into `yt-dlp` and handle archive skips — `[Model: Argon / Claude Sonnet]`
- [x] **Plan 01 - Step 6** (`A-04`): Close the `Ctx.cancel()` race window around `subprocess.Popen` — `[Model: Argon / Claude Sonnet]`
- [x] **Plan 01 - Step 7** (`A-06`): Filter Windows reserved device names and cap length in `safe_name` — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 8** (`A-07`): Catch `AttributeError` and `TypeError` in `format_map` template rendering — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 9** (`A-10`): Guard `effective_ranges` against unknown duration `0.0` — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 10** (`A-11`): Clean up stale comments & docstrings in `core/` — `[Model: Gemini Flash]`
- [x] **Plan 01 - Step 11 (RELEASE `v2.14.1`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.14.1`), commit & git tag `v2.14.1` — `[Model: Argon / Claude Sonnet]`

### Plan 02 — [`docs/PLAN_02_SECURITY_ATOMIC_STORAGE_AND_UPDATER.md`](./PLAN_02_SECURITY_ATOMIC_STORAGE_AND_UPDATER.md) -> Release `v2.14.2`
- [x] **Plan 02 - Step 1** (`G-02`, `C-06`): Add `atomic_write_json`, `.corrupt` backup, and `0o600` on `config.json` — `[Model: Gemini Flash]`
- [x] **Plan 02 - Step 2** (`C-01`): Harden deep links (`luckydownloader://`) and SSRF host check — `[Model: Gemini Flash]`
- [x] **Plan 02 - Step 3** (`C-02`): Stage updates in `DATA_DIR/updates` and re-verify hash before launch — `[Model: Gemini Flash]`
- [x] **Plan 02 - Step 4** (`C-03`, `G-04`): Fix legacy migration sentinel and unsafe uninstaller cleanup — `[Model: Gemini Flash]`
- [x] **Plan 02 - Step 5** (`C-04`): Validate segment and init URLs in `parse_hls_playlist` — `[Model: Gemini Flash]`
- [x] **Plan 02 - Step 6** (`C-07`): Sanitize quotes in `reveal_in_file_manager` — `[Model: Gemini Flash]`
- [x] **Plan 02 - Step 7** (`C-05`): Add SHA-256 verification to macOS `ffmpeg`/`ffprobe` auto-downloader — `[Model: Argon / Claude Sonnet]`
- [x] **Plan 02 - Step 8 (RELEASE `v2.14.2`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.14.2`), commit & git tag `v2.14.2` — `[Model: Argon / Claude Sonnet]`

### Plan 03 — [`docs/PLAN_03_QT_UI_PARALLEL_QUEUE_AND_WIN32.md`](./PLAN_03_QT_UI_PARALLEL_QUEUE_AND_WIN32.md) -> Release `v2.14.3`
- [x] **Plan 03 - Step 1** (`D-01`): Fix `MainWindow.closeEvent` leaking parallel queue workers — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 2** (`D-02`): Fix `QueueTab` signal leak on `language_bus().changed` — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 3** (`D-03`): Remove duplicate `history_btn.clicked` connection — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 4** (`D-04`): Aggregate parallel worker progress and rate limits — `[Model: Argon / Claude Sonnet]`
- [x] **Plan 03 - Step 5** (`D-05`): Stop `QueueRowDelegate._shimmer_timer` when no job is running — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 6** (`D-06`): Move `TwitchClient.refresh_token()` off the Qt GUI thread — `[Model: Argon / Claude Sonnet]`
- [x] **Plan 03 - Step 7** (`D-07`): Guard async thumbnail callbacks against stale URLs — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 8** (`D-08`): Synchronize `ShortcutsDialog` with actual `MainWindow` shortcuts — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 9** (`D-09`): Fix double translation `t(t(...))` and dead `row_number` attribute — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 10** (`E-01`): Fix top 6 px resize border blocking titlebar caption buttons — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 11** (`E-02`): Add explicit 64-bit `ctypes` `argtypes`/`restype` in `qt_ui/frameless.py` — `[Model: Argon / Claude Sonnet]`
- [x] **Plan 03 - Step 12** (`E-03`): Check per-monitor auto-hide taskbar alongside `ABM_GETSTATE` — `[Model: Gemini Flash]`
- [x] **Plan 03 - Step 13 (RELEASE `v2.14.3`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.14.3`), commit & git tag `v2.14.3` — `[Model: Argon / Claude Sonnet]`

### Plan 04 — [`docs/PLAN_04_PREMIERE_CEP_PLUGIN_HARDENING.md`](./PLAN_04_PREMIERE_CEP_PLUGIN_HARDENING.md) -> Release `v2.14.4`
- [x] **Plan 04 - Step 1** (`F-01`): Remove unused `--enable-nodejs`/`--mixed-context` and gate `.debug` on dev flag — `[Model: Gemini Flash]`
- [x] **Plan 04 - Step 2** (`F-02`): Replace `innerHTML` concatenation with safe DOM nodes in `ui.js` — `[Model: Gemini Flash]`
- [x] **Plan 04 - Step 3** (`F-03`): Verify `ZXPSignCmd` SHA-256 and read cert password from env — `[Model: Gemini Flash]`
- [x] **Plan 04 - Step 4** (`F-04`): Remove duplicate functions in `markers-core.js` and wire `applyPreferences` in `runner.js` — `[Model: Gemini Flash]`
- [x] **Plan 04 - Step 5** (`F-05`): Populate `source.id` for non-Twitch sources in `premiere_export.py` and sync docs — `[Model: Gemini Flash]`
- [x] **Plan 04 - Step 6 (RELEASE `v2.14.4`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.14.4`), commit & git tag `v2.14.4` — `[Model: Argon / Claude Sonnet]`

### Plan 05 — [`docs/PLAN_05_INSTALLER_CI_CD_AND_TESTS.md`](./PLAN_05_INSTALLER_CI_CD_AND_TESTS.md) -> Release `v2.14.5`
- [x] **Plan 05 - Step 1** (`I-02`): Set `UsePreviousAppDir=no` in `installer.iss` — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 2** (`I-01`): Gate GitHub Release jobs on the `test` job in `.github/workflows/build.yml` — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 3** (`I-03`): Pin CI permissions, `appimagetool` SHA-256, and Python dependencies — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 4** (`I-04`): Fix empty-colon `LD_LIBRARY_PATH` / `PATH` expansion in `build_linux.sh` — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 5** (`I-05`): Clean up CI matrix `allow-failure` and smoke test — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 6** (`J-01`): Fix `tests/conftest.py` `os._exit(0)` hiding pytest errors on Linux — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 7** (`J-02`): Isolate `DATA_DIR`, `HISTORY_PATH`, and `WATCHLIST_PATH` in `tests/conftest.py` — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 8** (`J-03`): Unlock all 31 skipped tests on Windows — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 9** (`J-04`): Add regression unit tests for `C-02`, `G-01`, and `D-01` — `[Model: Gemini Flash]`
- [x] **Plan 05 - Step 10 (RELEASE `v2.14.5`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.14.5`), commit & git tag `v2.14.5` — `[Model: Argon / Claude Sonnet]`

### Plan 06 — [`docs/PLAN_06_PROVIDERS_I18N_AND_REBRAND_HYGIENE.md`](./PLAN_06_PROVIDERS_I18N_AND_REBRAND_HYGIENE.md) -> Release `v2.14.6`
- [ ] **Plan 06 - Step 1** (`B-01`): Normalize `YoutubeTab` extractor names and channel URLs — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 2** (`B-02`): Fix Twitch clip synthetic format IDs vs `build_generic_format_string` — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 3** (`B-03`): Deduplicate `_run_ytdlp_json` across `source_info.py`, `generic.py`, and `youtube.py` — `[Model: Argon / Claude Sonnet]`
- [ ] **Plan 06 - Step 4** (`B-04`): Scope YouTube `--extractor-args` and `--remote-components` to YouTube URLs — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 5** (`B-05`): Validate playlist entry URLs and add `--` separator before target URLs — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 6** (`H-01`): Fix `tools/i18n.py` regex to extract `_t("...")` calls — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 7** (`G-05`): Wrap untranslated user-facing strings in `t(...)` — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 8** (`H-02`, `H-03`): Recompile `.mo` files and sync `luckytwitch.mo` — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 9** (`K-01`): Update default `out_dir` and Windows `AppUserModelID` to `LuckyDownloader` — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 10** (`K-02`): Flip `luckydownloader_*` vs `luckytwitch_*` facade direction — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 11** (`K-03`): Update `.gitignore` and clean up duplicate legacy icon assets — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 12** (`K-04`): Update stale `LuckyTwitch` branding in `LICENSE`, `README.es.md`, and `docs/README.md` — `[Model: Gemini Flash]`
- [ ] **Plan 06 - Step 13 (RELEASE `v2.14.6`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.14.6`), commit & git tag `v2.14.6` — `[Model: Argon / Claude Sonnet]`

### Plan 07 — [`docs/PLAN_07_ARCHITECTURE_AND_PRODUCT_ROADMAP.md`](./PLAN_07_ARCHITECTURE_AND_PRODUCT_ROADMAP.md) -> Release `v2.15.0`
- [ ] **Plan 07 - Step 1** (`L-01`): Pre-flight disk-space check before starting jobs — `[Model: Gemini Flash]`
- [ ] **Plan 07 - Step 2** (`L-03`): Rotating log file and one-click "Export Diagnostics Bundle" — `[Model: Gemini Flash]`
- [ ] **Plan 07 - Step 3** (`A-08`, `L-04`): Deterministic resumable work directories & stale workdir cleanup — `[Model: Argon / Claude Sonnet]`
- [ ] **Plan 07 - Step 4** (`L-02`): Automatic queue persistence & crash/update recovery — `[Model: Argon / Claude Sonnet]`
- [ ] **Plan 07 - Step 5** (`A-09`, `L-05`): Decouple `core/` from `sys.modules.get("luckytwitch_engine")` — `[Model: Argon / Claude Sonnet]`
- [ ] **Plan 07 - Step 6** (`D-10`): Split Qt UI god-modules (`main_window.py`, `tabs/plan.py`, `timeline.py`) — `[Model: Argon / Claude Sonnet]`
- [ ] **Plan 07 - Step 7 (RELEASE `v2.15.0`)**: Final diff review, full test suite, `RELEASE_NOTES.md` (`## v2.15.0`), commit & git tag `v2.15.0` — `[Model: Argon / Claude Sonnet]`

---

## Release Schedule Overview (7 Releases for 7 Plans)

| Plan | Release Tag | Focus | Final Review & Release Owner |
|---|---|---|---|
| **Plan 01** | `v2.14.1` | Critical Data Pipeline & Watchlist Fixes | **Argon / Claude Sonnet** (Step 11) |
| **Plan 02** | `v2.14.2` | Security, Atomic Storage & Updater Hardening | **Argon / Claude Sonnet** (Step 8) |
| **Plan 03** | `v2.14.3` | Qt UI Lifecycle, Parallel Queue & Win32 Frame | **Argon / Claude Sonnet** (Step 13) |
| **Plan 04** | `v2.14.4` | Premiere Pro CEP Plugin Security & Bug Fixes | **Argon / Claude Sonnet** (Step 6) |
| **Plan 05** | `v2.14.5` | Installer, CI/CD Workflow & Test Suite Fixes | **Argon / Claude Sonnet** (Step 10) |
| **Plan 06** | `v2.14.6` | Providers, i18n & Rebrand Hygiene Fixes | **Argon / Claude Sonnet** (Step 13) |
| **Plan 07** | `v2.15.0` | Architecture Refactors & Robustness Features | **Argon / Claude Sonnet** (Step 7) |

> [!NOTE]
> **How CI Releases Work in This Repo (`.github/workflows/build.yml:49-63`):**
> - The build workflow extracts the release body from `RELEASE_NOTES.md` by checking that **line 1 of `RELEASE_NOTES.md` is literally `## <tag>`** (e.g. `## v2.14.1`).
> - During each build, `build_windows.bat` / `build_linux.sh` / `build_mac.sh` automatically stamps `GITHUB_REF_NAME` into `version.txt` (`paths.BUNDLED_VERSION`).

---

## Standard Verification Commands

```powershell
# 1. Python test suite (headless Qt)
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q

# 2. i18n catalog check
python tools/i18n.py check

# 3. Premiere CEP test suite
Push-Location premiere-plugin-cep; npm test; Pop-Location
```
