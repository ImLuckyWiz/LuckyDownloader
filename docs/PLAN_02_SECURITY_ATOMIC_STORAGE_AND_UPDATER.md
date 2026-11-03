# Plan 02 — Priority 2: Security, Atomic JSON Persistence & Updater Hardening

- **Priority:** 2 (Fixes non-atomic JSON state writes, deep-link auto-invocation, updater `%TEMP%` TOCTOU risks, and legacy uninstaller/migration bugs)
- **Findings Covered:** `G-02` (Old Audit A2), `C-06` (Old Audit A4), `C-01`, `C-02`, `C-03`, `G-04`, `C-04`, `C-05`, `C-07`
- **Recommended Model:**
  - **Steps 1, 2, 3, 4, 5, 6, 8:** Safe for **Gemini Flash**
  - **Step 7 (`C-05`):** Recommended for **Argon or Claude Sonnet**

---

## Step 1 — Add `atomic_write_json` and Corrupt-File Backup Across All State Files (`G-02` & `C-06`, High/Medium)

- **Model:** Gemini Flash
- **Files:**
  - `core/files.py`
  - `core/settings.py` (lines 55–85)
  - `core/config.py` (lines 15–28)
  - `core/history.py` (lines 49–76)
  - `core/watchlist.py` (lines 57–84)
  - `core/recent.py` (lines 10–53)
  - `core/ui_state.py` (lines 38–74)
- **Problem:**
  1. Every JSON persistence module uses `Path.write_text(...)`, which truncates in place (`O_TRUNC`). A crash, disk-full error, or force-close during save leaves a 0-byte or half-written JSON file.
  2. In `core/settings.py:59-64`, if `settings.json` contains a valid JSON list `[]` instead of `{}` (or is corrupted), `out.update(saved)` raises `TypeError` or silently resets without backing up the corrupted file.
  3. In `core/config.py:23-26` (`C-06`), `config.json` (which stores Twitch `client_secret`) is written with default world-readable permissions on POSIX.

### Instructions for Step 1

#### 1A. Add `atomic_write_json` and `backup_corrupt_file` to `core/files.py`
Append these helpers to `core/files.py`:

```python
import json
import tempfile
from pathlib import Path


def atomic_write_json(
    path: Path | str,
    data: object,
    *,
    indent: int = 2,
    chmod_mode: int | None = None,
) -> None:
    """Atomically serialize *data* as UTF-8 JSON to *path* via temp file + os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=indent, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if chmod_mode is not None and sys.platform != "win32":
            try:
                os.chmod(tmp_name, chmod_mode)
            except OSError:
                pass
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def backup_corrupt_json(path: Path | str) -> None:
    """Rename a corrupted JSON file to <name>.corrupt so user data isn't silently overwritten."""
    target = Path(path)
    if not target.exists():
        return
    try:
        backup = target.with_suffix(target.suffix + ".corrupt")
        os.replace(target, backup)
    except OSError:
        pass
```

#### 1B. Update `core/settings.py` (`load_settings` and `save_settings`)
In `core/settings.py:56-82`:
- Check `if isinstance(saved, dict): out.update(saved)` instead of assuming `json.loads` returned a `dict`.
- On `json.JSONDecodeError`, call `backup_corrupt_json(path)`.
- In `save_settings`, replace `path.write_text(...)` with `atomic_write_json(path, data)`.

```python
def load_settings() -> dict:
    """Read settings from disk, filling in any missing keys from DEFAULTS."""
    out = dict(DEFAULTS)
    path = _settings_file()
    try:
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                out.update(saved)
            else:
                from core.files import backup_corrupt_json
                backup_corrupt_json(path)
    except json.JSONDecodeError as e:
        log.debug("Failed to load settings from %s: %s", path, e)
        from core.files import backup_corrupt_json
        backup_corrupt_json(path)
    except Exception as e:
        log.debug("Failed to load settings from %s: %s", path, e)
    # ... keep existing out_dir fallback logic ...
```

And in `save_settings(data: dict) -> None`:
```python
def save_settings(data: dict) -> None:
    """Persist settings dict to disk."""
    path = _settings_file()
    try:
        from core.files import atomic_write_json
        atomic_write_json(path, data)
    except Exception as e:
        log.debug("Failed to save settings to %s: %s", path, e)
```

#### 1C. Update `core/config.py` (`C-06`)
In `core/config.py:21-26`, use `atomic_write_json(p, data, chmod_mode=0o600)`:
```python
def save_config(data: dict) -> None:
    try:
        from core.files import atomic_write_json
        atomic_write_json(_config_file(), data, chmod_mode=0o600)
    except Exception as e:
        log.debug("Failed to save config: %s", e)
```

#### 1D. Update `core/history.py`, `core/watchlist.py`, `core/recent.py`, `core/ui_state.py`
Replace `path.write_text(json.dumps(...), encoding="utf-8")` in `_save_raw` (`core/history.py:72`), `save_watchlist` (`core/watchlist.py:80`), `add_recent`/`clear_recent` (`core/recent.py:41, 50`), and `save_ui_state` (`core/ui_state.py:69`) with `atomic_write_json(path, ...)`.

### Verification
```powershell
pytest tests/test_core_helpers.py tests/test_history.py tests/test_watchlist.py tests/test_ui_state.py -q
```

---

## Step 2 — Harden Deep Links (`luckydownloader://`) and SSRF Host Check (`C-01`, High)

- **Model:** Gemini Flash
- **Files:** `qt_ui/main_window.py` (lines 1385–1416) and `weblink.py` (lines 67–78)
- **Problem:**
  1. `MainWindow.open_link()` populates `url_edit` from an untrusted `luckydownloader://open?url=...` link in a browser and immediately calls `self.on_get_info()`, spawning `yt-dlp` (with any enabled browser cookies) without user confirmation.
  2. `weblink._blocked_host()` only catches standard dotted-quad IPs via `ipaddress.ip_address(host)`, missing integer (`2130706433`), hex (`0x7f000001`), or octal (`0177.0.0.1`) loopback forms that `curl`/`yt-dlp` accept.

### Instructions for Step 2

#### 2A. Require User Confirmation or Manual Click on External Deep Links (`qt_ui/main_window.py:1385-1416`)
In `MainWindow.open_link`, populate and focus/select `self.url_edit` and bring the window to the foreground, or only auto-fetch when the host is a known first-party provider (`twitch.tv`, `youtube.com`, `youtu.be`, `kick.com`, `tiktok.com`) rather than an arbitrary generic URL.

```python
        self.tabs.setCurrentIndex(0)
        self.url_edit.setText(url)
        self.url_edit.setFocus()
        self.url_edit.selectAll()
        # Only auto-fetch metadata for trusted first-party video hosts;
        # for arbitrary URLs, pre-fill the URL bar so the user clicks Fetch.
        from core.providers.detect import detect_provider
        if detect_provider(url).site != "generic":
            self.on_get_info()
```

#### 2B. Reject Numeric/Hex/Octal Loopback Host Encodings in `weblink.py:67-78`
In `weblink._blocked_host(host: str) -> bool`, reject purely numeric hosts (`host.isdigit()`), hex hosts (`host.startswith("0x")`), and dotted quad octets with leading zeros (`0177.0.0.1`):

```python
def _blocked_host(host: str) -> bool:
    h = host.strip("[]").lower()
    if not h or h in _BLOCKED_HOSTS or h.endswith(".local") or h.endswith(".internal"):
        return True
    if h.isdigit() or h.startswith("0x"):
        return True
    # Block octal dotted quads such as 0177.0.0.1
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() or p.startswith("0x") for p in parts):
        if any(len(p) > 1 and p.startswith("0") for p in parts):
            return True
    try:
        ip = ipaddress.ip_address(h)
        return (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_qt_main_window.py -q
```

---

## Step 3 — Stage Updates in App Data Directory and Re-Verify Hash Before Launch (`C-02`, Medium)

- **Model:** Gemini Flash
- **Files:** `core/updates.py` (lines 335–350) and `qt_ui/update_dialog.py` (lines 155–220)
- **Problem:**
  1. `UpdateDialog._start_download()` downloads the installer to `Path(tempfile.gettempdir()) / f"LuckyDownloader_Update_{info.tag}{ext}"` (shared `%TEMP%` with unvalidated `info.tag`).
  2. When the user selects "Install on quit", `launch_installer(self._pending_installer)` runs much later at `closeEvent` without re-running `verify_download()`, creating a TOCTOU window.

### Instructions for Step 3
1. In `qt_ui/update_dialog.py:160-165`, sanitize `info.tag` with `re.sub(r"[^A-Za-z0-9._-]", "_", info.tag)[:40]` and stage the installer inside `paths.DATA_DIR / "updates"` (creating the folder with `mkdir(parents=True, exist_ok=True)`).
2. In `core/updates.py:340-346` (`launch_installer`), accept an optional `expected_sha256: str = ""` parameter (or verify via `verify_download` if `info` is provided) before executing `subprocess.Popen`.

#### Before (`qt_ui/update_dialog.py:160-165`)
```python
        ext = os.path.splitext(info.asset_name)[1] or ".exe"
        dest = os.path.join(
            tempfile.gettempdir(), f"LuckyDownloader_Update_{info.tag}{ext}"
        )
```

#### After (`qt_ui/update_dialog.py:160-168`)
```python
        ext = os.path.splitext(info.asset_name)[1] or ".exe"
        if ext.lower() not in (".exe", ".dmg", ".appimage", ".deb", ".zip", ".tar", ".gz"):
            ext = ".bin"
        safe_tag = re.sub(r"[^A-Za-z0-9._-]", "_", info.tag or "latest")[:40]
        updates_dir = paths.DATA_DIR / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        dest = str(updates_dir / f"LuckyDownloader_Update_{safe_tag}{ext}")
```
*(Ensure `import re` and `from core import paths` are imported in `qt_ui/update_dialog.py`.)*

3. In `qt_ui/update_dialog.py:196-218` (`_launch_now`), if `self._info.sha256_url` was verified during download, call `updates.verify_download(self._downloaded_path, self._info)` right before `updates.launch_installer(...)` or store the verified SHA-256 digest and re-check `updates.compute_sha256(self._downloaded_path)` before launching.

---

## Step 4 — Fix Legacy Migration Sentinel and Unsafe Uninstaller Cleanup (`C-03` & `G-04`, High/Medium)

- **Model:** Gemini Flash
- **File:** `core/paths.py` (lines 74–128, 165–183, 186–387)
- **Problem:**
  1. `G-04`: `migrate_from_legacy()` runs on every startup without a sentinel file, resurrects deleted files from the legacy `LuckyTwitch` folder, and omits `recent_searches.json` (`_MIGRATE_FILES` only lists 5 of 6 JSON files).
  2. `C-03`: `run_legacy_uninstaller()` on macOS runs `shutil.rmtree("/Applications/LuckyTwitch.app")` unconditionally without user confirmation.
  3. `C-03`: `_extract_uninstaller_exe()` splits unquoted paths on the first space (`cmd.split()[0]`), truncating `"C:\Program Files\LuckyTwitch\unins000.exe" /SILENT` to `"C:\Program"`.
  4. `C-03`: `find_legacy_uninstaller()` falls back to scanning all `HKCU`/`HKLM` uninstall keys with `"luckytwitch" in display_name.lower()`.

### Instructions for Step 4

#### 4A. Add `"recent_searches.json"` and a `.migrated_from_luckytwitch` Sentinel in `core/paths.py:74-128`
```python
_MIGRATE_FILES = (
    "settings.json",
    "config.json",
    "history.json",
    "watchlist.json",
    "ui_state.json",
    "recent_searches.json",
)
_MIGRATION_SENTINEL = ".migrated_from_luckytwitch"
```
At the start of `migrate_from_legacy(data_dir, legacy_dirs)`:
```python
    sentinel = data_dir / _MIGRATION_SENTINEL
    if sentinel.exists():
        return []
```
And at the end of `migrate_from_legacy` (after checking legacy dirs, once `data_dir` exists):
```python
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("1", encoding="utf-8")
    except OSError:
        pass
```

#### 4B. Fix `_extract_uninstaller_exe` (`core/paths.py:165-183`) for Unquoted Paths with Spaces
Use regex to match up to `.exe` (case-insensitive) when the string does not start with `"`:
```python
def _extract_uninstaller_exe(uninstall_string: str) -> str | None:
    s = (uninstall_string or "").strip()
    if not s:
        return None
    if s.startswith('"'):
        end = s.find('"', 1)
        if end > 1:
            return s[1:end]
        return None
    m = re.match(r"^(.+?\.exe)\b", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s.split()[0] if s else None
```

#### 4C. Remove Unconditional `shutil.rmtree("/Applications/LuckyTwitch.app")` and Broad Registry Scan
In `core/paths.py`:
- In `find_legacy_uninstaller()`, only match the known Inno Setup registry key `"{E4F8A9B2-7C3D-4E5F-9A1B-2C3D4E5F6A7B}_is1"` (do not scan arbitrary registry keys by substring).
- In `run_legacy_uninstaller()`, remove the `sys.platform == "darwin"` branch that calls `shutil.rmtree(Path("/Applications/LuckyTwitch.app"))` without user confirmation.

### Verification
```powershell
pytest tests/test_core_helpers.py -q
```

---

## Step 5 — Validate Segment and Init URLs in `parse_hls_playlist` (`C-04`, Medium)

- **Model:** Gemini Flash
- **File:** `core/download.py` (lines 507–567)
- **Problem:** `parse_hls_playlist()` resolves `#EXT-X-MAP:URI="..."` and segment lines using `urllib.parse.urljoin(base_url, line)` without checking that the resolved URL uses `http://` or `https://` and contains no control characters (`\r`, `\n`). Because `download_section_aligned` writes these URLs into `concat.txt` and invokes `ffmpeg -protocol_whitelist file,http,https,tcp,tls,crypto -f concat -safe 0`, a `file://` URI would allow local file inclusion.

### Instructions for Step 5
Add a helper `_is_safe_hls_url(u: str) -> bool` in `core/download.py` and filter both `init_url` and segment `seg_url` through it.

```python
def _is_safe_hls_url(url: str) -> bool:
    if not url or any(ch in url for ch in ("\r", "\n", "\x00")):
        return False
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
```
In `parse_hls_playlist()`:
- After resolving `init_url`, if `not _is_safe_hls_url(init_url): init_url = None`.
- After resolving `seg_url`, if `not _is_safe_hls_url(seg_url): continue`.

### Verification
```powershell
pytest tests/test_download_unit.py tests/test_core_pipeline.py -q
```

---

## Step 6 — Sanitize Quotes in `reveal_in_file_manager` (`C-07`, Low)

- **Model:** Gemini Flash
- **File:** `core/files.py` (lines 14–32)
- **Instructions:**
  In `reveal_in_file_manager(path: str)` (`core/files.py:19`), sanitize any stray `"` from `norm` before formatting `f'/select,"{norm}"'`:
  ```python
  norm = os.path.normpath(path).replace('"', "")
  subprocess.Popen(["explorer", f'/select,"{norm}"'])
  ```

---

## Step 7 — Add SHA-256 Verification to macOS `ffmpeg`/`ffprobe` Auto-Downloader (`C-05`, Medium)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Pinning a deterministic version and SHA-256 for `evermeet.cx` macOS builds (or switching the macOS `ffmpeg` source to a versioned GitHub Release asset with published checksums) requires external release verification. Assign this step to **Argon or Claude Sonnet**.

- **File:** `core/tools.py` (lines 259–313)
- **Instructions:**
  1. Replace the unpinned `/getrelease/ffmpeg/zip` floating endpoint in `core/tools.py:268-274` with a pinned release URL and expected SHA-256 dictionary, or verify the downloaded archive hash before extracting and running `chmod 0o755`.
  2. Refuse to extract if the SHA-256 does not match.


---

## Step 8 — Plan 02 Final Review, Release Notes, Commit & Tag (`v2.14.2`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 8 with Gemini Flash. Final code review, security verification, `RELEASE_NOTES.md` authoring, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.14.2`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Security Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_02` (`G-02`, `C-06`, `C-01`, `C-02`, `C-03`, `G-04`, `C-04`, `C-05`, `C-07`). Verify `atomic_write_json` is used across all JSON state files and no regressions were introduced.
  2. **Run Full Verification Suite:**
     ```powershell
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     python tools/i18n.py check
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.14.2`.
     - **Public-Facing Language:** Ensure notes are written for end users (focus on data safety, reliability, and security improvements) without internal jargon, plan IDs, or audit codes.
     - Prepend a `## v2.14.2` section at the top of `RELEASE_NOTES.md` summarizing all security and persistence fixes from Plan 02 (atomic JSON writes + `.corrupt` backup across settings/history/watchlist/config/UI state, `0o600` permissions on `config.json`, deep-link confirmation & loopback SSRF hardening, updater staging inside `DATA_DIR/updates` with pre-launch SHA-256 verification, one-time legacy migration sentinel, and HLS segment URL validation).
  4. **Commit & Tag Release `v2.14.2`:**
     - Mark Step 8 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.14.2): complete Plan 02 security, atomic storage, and updater hardening`, and create annotated tag `git tag -a v2.14.2 -m "LuckyDownloader v2.14.2"`.
