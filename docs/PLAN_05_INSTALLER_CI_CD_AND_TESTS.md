# Plan 05 — Priority 5: Installer, CI/CD Workflow & Test Suite Fixes

- **Priority:** 5 (Prevents broken releases from shipping, fixes the Windows installer upgrade directory bug, fixes Linux `os._exit(0)` masking pytest collection failures, isolates test state, and unlocks all 31 skipped tests on Windows)
- **Findings Covered:** `I-02`, `I-01`, `I-03` (Old Audit A9/A10), `I-04`, `I-05`, `J-01`, `J-02`, `J-03`, `J-04`
- **Recommended Model:** **Gemini Flash** for all 9 steps

---

## Step 1 — Set `UsePreviousAppDir=no` in `installer.iss` (`I-02`, High)

- **Model:** Gemini Flash
- **File:** `installer.iss` (lines 19–39)
- **Problem:** `installer.iss` keeps the legacy `LuckyTwitch` `AppId={{E4F8A9B2-7C3D-4E5F-9A1B-2C3D4E5F6A7B}` for seamless upgrade detection, and also runs `CleanupLegacyLuckyTwitch()` in `CurStepChanged(ssInstall)` to uninstall any previous install at `%LOCALAPPDATA%\Programs\LuckyTwitch`. Because Inno Setup defaults to `UsePreviousAppDir=yes`, upgrading an existing `LuckyTwitch` user reuses the old `%LOCALAPPDATA%\Programs\LuckyTwitch` folder as `{app}`, and then `CleanupLegacyLuckyTwitch()` runs the legacy uninstaller against that exact directory during installation.

### Instructions for Step 1
Add `UsePreviousAppDir=no` right below `DefaultDirName={autopf}\{#MyAppName}` in `installer.iss`.

#### Before (`installer.iss:26-31`)
```iss
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
```

#### After (`installer.iss:26-32`)
```iss
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
UsePreviousAppDir=no
DefaultGroupName={#MyAppName}
```

### Verification
```powershell
pytest tests/test_qt_packaging.py -q
```

---

## Step 2 — Gate GitHub Release Jobs on the `test` Job in `.github/workflows/build.yml` (`I-01`, High)

- **Model:** Gemini Flash
- **File:** `.github/workflows/build.yml` (lines 42–247)
- **Problem:** `init-release`, `build`, and `plugin` do not list `test` in `needs:`, and `checksums` uses `if: always() && startsWith(github.ref, 'refs/tags/v')`. A tagged commit with failing tests will still build, publish binaries, and upload `SHA256SUMS.txt` to the GitHub Release.

### Instructions for Step 2
Update `needs:` and `if:` in `.github/workflows/build.yml`:
1. On `init-release` (around line 44): add `needs: [test]`.
2. On `build` (around line 66): change `needs: init-release` to `needs: [test, init-release]`.
3. On `plugin` (around line 191): change `needs: init-release` to `needs: [test, init-release]`.
4. On `checksums` (around line 245): change `if: always() && startsWith(github.ref, 'refs/tags/v')` to `if: startsWith(github.ref, 'refs/tags/v')`.

---

## Step 3 — Pin CI Permissions, `appimagetool` SHA-256, and Python Dependencies (`I-03`, Medium)

- **Model:** Gemini Flash
- **Files:** `.github/workflows/build.yml` (lines 9–10, 105–110), `requirements.txt`, `requirements-dev.txt`
- **Instructions:**
  1. In `.github/workflows/build.yml:9-10`, change top-level `permissions:` to:
     ```yaml
     permissions:
       contents: read
     ```
     and add job-level `permissions: { contents: write }` only on `init-release`, `build`, `plugin`, and `checksums`.
  2. In `.github/workflows/build.yml:105-110`, replace the unverified `appimagetool-x86_64.AppImage` continuous URL download with a pinned release tag (e.g. tag `13`) and verify its SHA-256 via `sha256sum -c` before `chmod +x`.
  3. In `requirements.txt` and `requirements-dev.txt`, add upper bounds or exact version pins (`PySide6>=6.6,<6.9`, `Pillow>=10.0,<12.0`, `pyinstaller>=6.10,<7.0`, `pytest>=8.0,<9.0`).

---

## Step 4 — Fix Empty-Colon `LD_LIBRARY_PATH` / `PATH` Expansion in `build_linux.sh` (`I-04`, Medium)

- **Model:** Gemini Flash
- **File:** `build_linux.sh` (lines 68–75)
- **Problem:** When `LD_LIBRARY_PATH` is unset, `export LD_LIBRARY_PATH="$HERE/usr/lib:$LD_LIBRARY_PATH"` expands to `"$HERE/usr/lib:"`. A trailing colon in `LD_LIBRARY_PATH` tells `ld.so` to search the current working directory `.` for shared libraries (CWE-426).

### Instructions for Step 4
Use `${VAR:+:$VAR}` parameter expansion in `build_linux.sh`:

#### Before (`build_linux.sh:68-73`)
```bash
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$PATH"
export LD_LIBRARY_PATH="$HERE/usr/lib:$LD_LIBRARY_PATH"
exec "$HERE/usr/bin/LuckyDownloader" "$@"
EOF
```

#### After (`build_linux.sh:68-73`)
```bash
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin${PATH:+:$PATH}"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$HERE/usr/bin/LuckyDownloader" "$@"
EOF
```

---

## Step 5 — Clean Up CI Matrix `allow-failure` and Smoke Test (`I-05`, Low)

- **Model:** Gemini Flash
- **File:** `.github/workflows/build.yml` (lines 22–27, 159–164)
- **Instructions:**
  1. Remove the redundant `LuckyDownloader --help || true` line at `.github/workflows/build.yml:161` (since `LuckyDownloader` is a GUI binary without a `--help` exit hook and `test -x` on line 160 already checks the binary).
  2. Either remove `3.14` from the test matrix or remove `allow-failure: true` once PySide6 wheels for 3.14 are stable in CI.

---

## Step 6 — Fix `tests/conftest.py` `os._exit(0)` Hiding Pytest Errors on Linux (`J-01`, High)

- **Model:** Gemini Flash
- **File:** `tests/conftest.py` (lines 83–92)
- **Problem:** `pytest_unconfigure` checks `if failed == 0:` without checking `errors == 0` or `passed > 0`, and also does not check `session.exitstatus`. If a syntax error or import error causes a collection error (`failed == 0`, `errors > 0`), `os._exit(0)` forces exit code `0` on Linux CI.

### Instructions for Step 6
Update `pytest_unconfigure` in `tests/conftest.py:83-92` to check `errors == 0 and passed > 0`.

#### Before (`tests/conftest.py:83-92`)
```python
def pytest_unconfigure(config):
    if sys.platform.startswith("linux"):
        rep = config.pluginmanager.get_plugin("terminalreporter")
        failed = len(rep.stats.get("failed", [])) if rep else 0
        if failed == 0:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
```

#### After (`tests/conftest.py:83-95`)
```python
def pytest_unconfigure(config):
    if sys.platform.startswith("linux"):
        rep = config.pluginmanager.get_plugin("terminalreporter")
        failed = len(rep.stats.get("failed", [])) if rep else 0
        errors = len(rep.stats.get("error", [])) if rep else 0
        passed = len(rep.stats.get("passed", [])) if rep else 0
        if failed == 0 and errors == 0 and passed > 0:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_core_helpers.py -q
```

---

## Step 7 — Isolate `DATA_DIR`, `HISTORY_PATH`, and `WATCHLIST_PATH` in `tests/conftest.py` (`J-02`, Medium)

- **Model:** Gemini Flash
- **File:** `tests/conftest.py` (lines 18–34)
- **Problem:** The autouse `_data_folder_in_tmp` fixture patches `SETTINGS_FILE`, `CONFIG_FILE`, `RECENT_FILE`, and `UI_STATE_FILE`, but forgets `DATA_DIR`, `HISTORY_PATH` (`core.history`), and `WATCHLIST_PATH` (`core.watchlist`). Any test that does not manually monkeypatch `HISTORY_PATH` or `WATCHLIST_PATH` reads/writes the developer's real `%APPDATA%\LuckyDownloader\history.json` and `watchlist.json`.

### Instructions for Step 7
Update `_data_folder_in_tmp` in `tests/conftest.py:18-34` to also patch `DATA_DIR`, `HISTORY_PATH`, and `WATCHLIST_PATH`.

#### Before (`tests/conftest.py:18-34`)
```python
@pytest.fixture(autouse=True)
def _data_folder_in_tmp(tmp_path, monkeypatch):
    import luckydownloader_engine as eng
    import core.paths as _paths
    for mod in (eng, _paths):
        monkeypatch.setattr(mod, "DATA_FOLDER", tmp_path, raising=False)
        monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json", raising=False)
        monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config.json", raising=False)
        monkeypatch.setattr(mod, "RECENT_FILE", tmp_path / "recent_searches.json", raising=False)
        monkeypatch.setattr(mod, "UI_STATE_FILE", tmp_path / "ui_state.json", raising=False)
    yield
```

#### After (`tests/conftest.py:18-40`)
```python
@pytest.fixture(autouse=True)
def _data_folder_in_tmp(tmp_path, monkeypatch):
    import luckydownloader_engine as eng
    import core.paths as _paths
    import core.history as _history
    import core.watchlist as _watchlist
    for mod in (eng, _paths):
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path, raising=False)
        monkeypatch.setattr(mod, "DATA_FOLDER", tmp_path, raising=False)
        monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json", raising=False)
        monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config.json", raising=False)
        monkeypatch.setattr(mod, "RECENT_FILE", tmp_path / "recent_searches.json", raising=False)
        monkeypatch.setattr(mod, "UI_STATE_FILE", tmp_path / "ui_state.json", raising=False)
        monkeypatch.setattr(mod, "HISTORY_PATH", tmp_path / "history.json", raising=False)
        monkeypatch.setattr(mod, "WATCHLIST_PATH", tmp_path / "watchlist.json", raising=False)
    monkeypatch.setattr(_history, "HISTORY_PATH", tmp_path / "history.json", raising=False)
    monkeypatch.setattr(_watchlist, "WATCHLIST_PATH", tmp_path / "watchlist.json", raising=False)
    yield
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest -q
```

---

## Step 8 — Unlock All 31 Skipped Tests on Windows (`J-03`, Low)

- **Model:** Gemini Flash
- **Files:**
  - `tests/test_chat_and_game_markers.py` (lines 125–145)
  - `tests/test_chat_overlay.py` (lines 28–35, 170–178)
- **Problem:** 31 tests across `test_chat_and_game_markers.py` (25 tests) and `test_chat_overlay.py` (6 tests) are marked `@posix_only` solely because their `fake_cli()` helper creates a POSIX `#!/bin/sh` script that runs `python3 -c <body> "$@"`. On Windows, generating a `.cmd` wrapper (`@echo off\r\n"{sys.executable}" "{py_script}" %*\r\n`) works natively with `subprocess.Popen`.

### Instructions for Step 8
1. In `tests/test_chat_and_game_markers.py:125-136` and `tests/test_chat_overlay.py:170-176`, update `fake_cli(tmp_path, name, body_py)` so that on `sys.platform == "win32"`:
   - It writes `body_py` to `script_py = tmp_path / f"{name}_impl.py"`.
   - It writes `@echo off\r\n"{sys.executable}" "{script_py}" %*\r\n` to `p = tmp_path / f"{name}.cmd"`.
   - It returns `str(p)`.
2. Remove the `@posix_only` skip decorator (or change `posix_only` to a no-op decorator) in both files.

### Verification
```powershell
pytest tests/test_chat_and_game_markers.py tests/test_chat_overlay.py -q
```
*(Expect 0 skipped and all 31 previously skipped tests passing on Windows.)*

---

## Step 9 — Add Regression Unit Tests for `C-02`, `G-01`, and `D-01` (`J-04`, Medium)

- **Model:** Gemini Flash
- **Files:** `tests/test_updates.py`, `tests/test_watchlist.py`, `tests/test_qt_main_window.py`
- **Instructions:**
  1. In `tests/test_updates.py`, add tests for `verify_download()`:
     - Valid matching SHA-256 returns `(True, "SHA-256 verified")`.
     - Mismatched SHA-256 returns `(False, "SHA-256 mismatch ...")`.
     - Missing `sha256_url` returns `(True, "")`.
  2. In `tests/test_watchlist.py`, add `test_check_all_watchers_persists_last_seen_id(tmp_path)`:
     - Call `add_to_watchlist("https://twitch.tv/streamer", "streamer")`.
     - Call `check_all_watchers(fetch_items_fn=lambda url, max_items: [{"id": "vod_999", "title": "Stream"}])`.
     - Reload from disk with `load_watchlist()` and assert `watchers[0].last_seen_id == "vod_999"` and `watchers[0].last_checked > 0`.
  3. In `tests/test_qt_main_window.py`, add a test verifying that `MainWindow.closeEvent` invokes `self._queue_runner.cancel()` rather than only `self._queue_runner.ctx.cancel()`.

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_updates.py tests/test_watchlist.py tests/test_qt_main_window.py -q
```


---

## Step 10 — Plan 05 Final Review, Release Notes, Commit & Tag (`v2.14.5`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 10 with Gemini Flash. Even though Steps 1–9 of Plan 05 are executed by Gemini Flash, the final review, CI workflow audit, `RELEASE_NOTES.md` preparation, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.14.5`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_05` (`I-01`..`I-05`, `J-01`..`J-04`). Double-check `.github/workflows/build.yml` YAML syntax and `installer.iss` directives.
  2. **Run Full Verification Suite:**
     ```powershell
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     python tools/i18n.py check
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
     Confirm that all 31 previously skipped Windows tests now execute and pass (`0 skipped`).
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.14.5`.
     - **Public-Facing Language:** Ensure notes are written for end users (installer improvements, upgrade compatibility, build stability) without internal jargon, plan IDs, or audit codes.
     - Prepend a `## v2.14.5` section at the top of `RELEASE_NOTES.md` summarizing all installer, CI/CD, and test suite improvements from Plan 05 (`UsePreviousAppDir=no` in `installer.iss` for clean upgrades from `LuckyTwitch`, gating GitHub Release jobs on `test`, least-privilege workflow permissions, `AppRun` `LD_LIBRARY_PATH` hardening, `conftest.py` isolation, and full Windows test coverage with 0 skipped tests).
  4. **Commit & Tag Release `v2.14.5`:**
     - Mark Step 10 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.14.5): complete Plan 05 installer, CI/CD workflow, and test suite fixes`, and create annotated tag `git tag -a v2.14.5 -m "LuckyDownloader v2.14.5"`.
