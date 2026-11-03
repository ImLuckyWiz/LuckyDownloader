# Plan 01 — Priority 1: Critical Data, Core Pipeline & Watchlist Fixes

- **Priority:** 1 (Highest — fixes silent data loss, parallel file deletion races, path traversal, and broken features)
- **Findings Covered:** `G-01`, `G-03`, `A-01`, `A-02`, `A-03`, `A-04`, `A-05`, `A-06`, `A-07`, `A-10`, `A-11`
- **Recommended Model:**
  - **Steps 1, 2, 3, 4, 7, 8, 9, 10, 11:** Safe for **Gemini Flash**
  - **Steps 5 (`A-03`) & 6 (`A-04`):** Recommended for **Argon or Claude Sonnet** (see warnings inside those steps)

---

## Step 1 — Fix `check_all_watchers` Never Saving Updated Watchlist (`G-01`, High)

- **Model:** Gemini Flash
- **File:** `core/watchlist.py` (lines 222–261)
- **Problem:** `check_channel_new_items(w, ...)` mutates `w.last_checked` and `w.last_seen_id` in-place and returns `w`. In `check_all_watchers()`, `if updated is not w:` is always `False`, so `changed` stays `False` and `save_watchlist(watchers)` is never called.

### Instructions for Step 1
Open `core/watchlist.py` around line 235 (`check_all_watchers`) and compare `(w.last_seen_id, w.last_checked)` before and after calling `check_channel_new_items`.

#### Before (`core/watchlist.py:240-255`)
```python
    changed = False
    for idx, w in enumerate(watchers):
        if cancel_check and cancel_check():
            break
        try:
            updated, new_items = check_channel_new_items(
                w, fetch_items_fn=fetch_items_fn
            )
            if updated is not w:
                watchers[idx] = updated
                changed = True
            if new_items:
                results.append((w, new_items))
        except Exception as e:
            log.debug("Watchlist check failed for %s: %s", w.channel_login, e)
```

#### After (`core/watchlist.py:240-257`)
```python
    changed = False
    for idx, w in enumerate(watchers):
        if cancel_check and cancel_check():
            break
        try:
            prev_state = (w.last_seen_id, w.last_checked)
            updated, new_items = check_channel_new_items(
                w, fetch_items_fn=fetch_items_fn
            )
            watchers[idx] = updated
            if (updated.last_seen_id, updated.last_checked) != prev_state:
                changed = True
            if new_items:
                results.append((updated, new_items))
        except Exception as e:
            log.debug("Watchlist check failed for %s: %s", w.channel_login, e)
```

### Verification
```powershell
pytest tests/test_watchlist.py -q
```

---

## Step 2 — Fix Substring Matching and Empty-String Bug in Watchlist Lookup (`G-03`, Medium)

- **Model:** Gemini Flash
- **File:** `core/watchlist.py` (lines 125–162)
- **Problem:** `remove_from_watchlist` and `is_watched` evaluate `clean_login in w.url.lower()`. Passing `""` matches every URL (`"" in url` is `True`) and deletes the entire watchlist; passing `"ann"` matches `"https://twitch.tv/channel"`.

### Instructions for Step 2
In `core/watchlist.py`, update `remove_from_watchlist` and `is_watched` to return early on empty input and compare only `w.channel_login.lower() == clean_login` or `w.url.rstrip("/").lower() == clean_url`.

#### Before (`core/watchlist.py:125-162`)
```python
def remove_from_watchlist(channel_login_or_url: str) -> bool:
    """Remove a channel by login or URL. Returns True if removed."""
    clean_login = extract_channel_login(channel_login_or_url) or channel_login_or_url.strip().lower()
    watchers = load_watchlist()
    before = len(watchers)
    watchers = [
        w for w in watchers
        if w.channel_login.lower() != clean_login
        and clean_login not in w.url.lower()
    ]
    if len(watchers) < before:
        save_watchlist(watchers)
        return True
    return False


def is_watched(channel_login_or_url: str) -> bool:
    """Check if a channel is in the watchlist."""
    if not channel_login_or_url:
        return False
    clean_login = extract_channel_login(channel_login_or_url) or channel_login_or_url.strip().lower()
    if not clean_login:
        return False
    watchers = load_watchlist()
    return any(
        w.channel_login.lower() == clean_login or clean_login in w.url.lower()
        for w in watchers
    )
```

#### After (`core/watchlist.py:125-168`)
```python
def remove_from_watchlist(channel_login_or_url: str) -> bool:
    """Remove a channel by login or URL. Returns True if removed."""
    raw = (channel_login_or_url or "").strip()
    if not raw:
        return False
    clean_login = (extract_channel_login(raw) or raw).strip().lower()
    clean_url = raw.rstrip("/").lower()
    if not clean_login:
        return False
    watchers = load_watchlist()
    before = len(watchers)
    watchers = [
        w for w in watchers
        if w.channel_login.lower() != clean_login
        and w.url.rstrip("/").lower() != clean_url
    ]
    if len(watchers) < before:
        save_watchlist(watchers)
        return True
    return False


def is_watched(channel_login_or_url: str) -> bool:
    """Check if a channel is in the watchlist."""
    raw = (channel_login_or_url or "").strip()
    if not raw:
        return False
    clean_login = (extract_channel_login(raw) or raw).strip().lower()
    clean_url = raw.rstrip("/").lower()
    if not clean_login:
        return False
    watchers = load_watchlist()
    return any(
        w.channel_login.lower() == clean_login
        or w.url.rstrip("/").lower() == clean_url
        for w in watchers
    )
```

### Verification
```powershell
pytest tests/test_watchlist.py -q
```

---

## Step 3 — Sanitize `src.id` and Scope Work Folder Per Job (`A-01` & `A-02`, High)

- **Model:** Gemini Flash
- **Files:** `core/finalize.py` (lines 575–590) and `core/source_info.py` (lines 555–565)
- **Problem:**
  1. `A-01`: `work = os.path.join(opts.out_dir, f".luckytwitch_{src.id}_{fmt_slug}")` is shared by two parallel jobs downloading different ranges of the same VOD. The first job to finish runs `shutil.rmtree(work)` and deletes the second job's in-progress media files.
  2. `A-02`: `src.id` from generic `yt-dlp` JSON is not sanitized (unlike `fmt_slug`), allowing `/` or `..` in `src.id` to escape `opts.out_dir` and be passed to `shutil.rmtree(work)`.

### Instructions for Step 3
1. In `core/finalize.py`, import `uuid` (at top of file if not already imported).
2. In `run_job()` (`core/finalize.py:580-583`), sanitize `src.id` with ` re.sub(r"[^A-Za-z0-9_-]", "_", str(src.id or "unknown"))[:64]` and append a short unique token `uuid.uuid4().hex[:8]` so concurrent jobs never collide on the same workdir.
3. In `core/source_info.py:561`, guard `info.get("id")` so it strips path separators.

#### Before (`core/finalize.py:578-585`)
```python
    os.makedirs(opts.out_dir, exist_ok=True)
    fmt_slug = re.sub(r"[^A-Za-z0-9_-]", "_", opts.fmt_id)[:40]
    work = os.path.join(opts.out_dir, f".luckytwitch_{src.id}_{fmt_slug}")
    os.makedirs(work, exist_ok=True)
    hide_folder_win(work)
```

#### After (`core/finalize.py:578-587`)
```python
    os.makedirs(opts.out_dir, exist_ok=True)
    id_slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(src.id or "unknown"))[:64] or "unknown"
    fmt_slug = re.sub(r"[^A-Za-z0-9_-]", "_", opts.fmt_id)[:40]
    job_nonce = uuid.uuid4().hex[:8]
    work = os.path.join(opts.out_dir, f".luckytwitch_{id_slug}_{fmt_slug}_{job_nonce}")
    os.makedirs(work, exist_ok=True)
    hide_folder_win(work)
```
*(Ensure `import uuid` is present at the top of `core/finalize.py`.)*

### Verification
```powershell
pytest tests/test_core_pipeline.py tests/test_finalize_unit.py -q
```

---

## Step 4 — Guard `download_section_aligned` Against Non-Twitch Sources (`A-05`, Medium)

- **Model:** Gemini Flash
- **File:** `core/finalize.py` (lines 674–698)
- **Problem:** `use_aligned = opts.keyframe_align and not opts.reencode and (s > 0 or e < src.duration)` does not check `src.site == "twitch"`. If `keyframe_align=True` on a YouTube/generic job (e.g. from playlist expansion), `download_section_aligned` fails or fetches wrong streams.

### Instructions for Step 4
Add `and getattr(src, "site", "twitch") == "twitch"` to `use_aligned` in `core/finalize.py`.

#### Before (`core/finalize.py:676-679`)
```python
                use_aligned = (
                    opts.keyframe_align
                    and not opts.reencode
                    and (s > 0 or (src.duration > 0 and e < src.duration))
                )
```

#### After (`core/finalize.py:676-680`)
```python
                use_aligned = (
                    opts.keyframe_align
                    and not opts.reencode
                    and getattr(src, "site", "twitch") == "twitch"
                    and (s > 0 or (src.duration > 0 and e < src.duration))
                )
```

### Verification
```powershell
pytest tests/test_core_pipeline.py tests/test_finalize_unit.py -q
```

---

## Step 5 — Wire `JobOptions.download_archive` into `yt-dlp` and Handle Archive Skips (`A-03`, High)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 5 with Gemini Flash without careful review. When `yt-dlp` receives `--download-archive <file>` and the video ID is already in the archive, `yt-dlp` exits with code `0` without writing a media file to `work`. In addition, several tests monkeypatch `download_full` and `download_section` through `luckytwitch_engine`, so adding a `download_archive` keyword parameter must preserve backward compatibility with existing positional/keyword test stubs.

- **Files:** `core/download.py` (lines 296–440) and `core/finalize.py` (lines 645–698)
- **Problem:** `JobOptions.download_archive` is set by `expand_playlist_to_jobs()` (`core/playlist.py:98`), and `build_generic_download_args()` (`core/download.py:617`) supports it, but `download_full()` and `download_section()` never pass `--download-archive` to `yt-dlp`.

### Instructions for Step 5
1. In `core/download.py`, add `download_archive: str = ""` (with default `""`) to `_ytdlp_base_args()`, `download_full()`, and `download_section()`.
2. Inside `_ytdlp_base_args()`, when `download_archive` is non-empty, append `["--download-archive", download_archive]`.
3. In `core/finalize.py`, pass `download_archive=opts.download_archive` when calling `download_full` (or check if the target signature accepts it via `inspect.signature` if a test monkeypatched `download_full` with a fixed signature).
4. In `download_full()`, if `download_archive` is set and `yt-dlp` exits `0` with no output file produced (and stdout/stderr contains `"has already been recorded in the archive"`), raise a dedicated `ArchiveSkippedError` or handle it cleanly in `run_job()` so the job completes as skipped rather than raising `"File not found after download"`.

### Verification
```powershell
pytest tests/test_playlist.py tests/test_core_pipeline.py tests/test_download_unit.py -q
```

---

## Step 6 — Close the `Ctx.cancel()` Race Window Around `subprocess.Popen` (`A-04`, Medium)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Concurrency changes to `Ctx` (`core/runtime.py`) and subprocess spawning (`core/download.py`, `core/chat.py`) affect cancellation tests across the suite. Execute with **Argon or Claude Sonnet**.

- **Files:** `core/runtime.py` (lines 145–175), `core/download.py` (lines 155–167, 342–358), `core/chat.py` (lines 100–108)
- **Problem:** `ctx.proc = proc` is assigned without a lock, and if `ctx.cancel()` runs between `if ctx.is_cancelled()` and `ctx.proc = subprocess.Popen(...)`, `kill_proc_tree(self.proc)` runs when `self.proc` is still `None`, leaving the newly spawned `yt-dlp` or `ffmpeg` process running.

### Instructions for Step 6
1. Add a `threading.Lock()` (`self._lock`) to `Ctx.__init__` in `core/runtime.py`.
2. Add a helper method `ctx.attach_proc(proc)`:
   ```python
   def attach_proc(self, proc) -> None:
       with self._lock:
           self.proc = proc
           cancelled = self._cancel.is_set()
       if cancelled and proc is not None:
           kill_proc_tree(proc)
           raise Cancelled()
   ```
3. Update `Ctx.cancel()` to read `self.proc` under `self._lock`.
4. Replace `ctx.proc = proc` in `core/download.py` and `core/chat.py` with `ctx.attach_proc(proc)`.

### Verification
```powershell
pytest tests/test_core_pipeline.py tests/test_download_unit.py -q
```

---

## Step 7 — Filter Windows Reserved Device Names and Cap Length in `safe_name` (`A-06`, Medium)

- **Model:** Gemini Flash
- **File:** `core/finalize.py` (lines 80–95)
- **Problem:** `safe_name("CON")` returns `"CON"`, and `safe_name("CON.mp4")` or channel/title templates with Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`..`COM9`, `LPT1`..`LPT9`, plus superscript digits `¹²³`) fail or hang on Windows. Also `safe_name` does not cap length (`_sanitize_part` caps at 120 chars, `safe_name` does not).

### Instructions for Step 7
Update `safe_name()` in `core/finalize.py:85-89` to cap at 150 characters and prefix `_` if the stem (before the first `.`) matches a Windows reserved device name.

#### Before (`core/finalize.py:85-89`)
```python
def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "")
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s or "video"
```

#### After (`core/finalize.py:85-97`)
```python
_WIN_RESERVED_RE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9\xb9\xb2\xb3]|LPT[1-9\xb9\xb2\xb3])(\..*)?$",
    re.IGNORECASE,
)


def safe_name(s: str, max_len: int = 150) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "")
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    if max_len > 0 and len(s) > max_len:
        s = s[:max_len].rstrip(". ")
    if _WIN_RESERVED_RE.match(s):
        s = f"_{s}"
    return s or "video"
```

### Verification
```powershell
pytest tests/test_core_helpers.py tests/test_finalize_unit.py -q
```

---

## Step 8 — Catch `AttributeError` and `TypeError` in `format_map` Template Rendering (`A-07`, Low)

- **Model:** Gemini Flash
- **Files:** `core/finalize.py` (lines 148–151, 208–211, 274–277) and `core/chapters.py` (lines 70–73)
- **Problem:** User filename templates containing `{title.foo}` or `{title[0]}` raise `AttributeError` or `TypeError` inside `str.format_map()`, which is not caught by `except (KeyError, ValueError):`.

### Instructions for Step 8
Change all four `except (KeyError, ValueError):` blocks around `.format_map(...)` in `core/finalize.py` and `core/chapters.py` to `except (KeyError, ValueError, AttributeError, TypeError, IndexError):`.

### Verification
```powershell
pytest tests/test_finalize_unit.py tests/test_chapters.py -q
```

---

## Step 9 — Guard `effective_ranges` Against Unknown Duration `0.0` (`A-10`, Low)

- **Model:** Gemini Flash
- **File:** `core/planning.py` (lines 70–80)
- **Problem:** When `src.duration == 0.0` (live stream or metadata without duration) and `cuts` is non-empty, `pts = [0.0] + sorted(cuts) + [0.0]` produces an invalid backward range `(cut, 0.0)`.

### Instructions for Step 9
In `core/planning.py:72-78`, if `duration <= 0` and `not ranges`, return `[(0.0, 0.0)]` instead of building cut segments ending at `0.0`.

#### Before (`core/planning.py:72-78`)
```python
def effective_ranges(
    duration: float, ranges: list[tuple[float, float]], cuts: list[float]
) -> list[tuple[float, float]]:
    if ranges:
        return list(ranges)
    if cuts:
        pts = [0.0] + sorted(cuts) + [duration]
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i + 1] - pts[i] >= 0.5]
    return [(0.0, duration)]
```

#### After (`core/planning.py:72-78`)
```python
def effective_ranges(
    duration: float, ranges: list[tuple[float, float]], cuts: list[float]
) -> list[tuple[float, float]]:
    if ranges:
        return list(ranges)
    if cuts and duration > 0:
        pts = [0.0] + sorted(cuts) + [duration]
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i + 1] - pts[i] >= 0.5]
    return [(0.0, duration)]
```

### Verification
```powershell
pytest tests/test_core_helpers.py -q
```

---

## Step 10 — Clean Up Stale Comments & Docstrings in `core/` (`A-11`, Nit)

- **Model:** Gemini Flash
- **Files:** `core/download.py:28-31`, `core/tools.py:33-36`, `core/finalize.py:716-717`, `core/timeline.py:1-5`
- **Instructions:**
  1. In `core/download.py:28-31` and `core/tools.py:33-36`, update the comment from `"Allow test monkeypatching via luckydownloader_engine module"` to `"Allow test monkeypatching via luckytwitch_engine module"`.
  2. In `core/finalize.py:716-717`, remove or update the stale comment `# Move final files out of hidden work folder (already in out_dir)`.
  3. In `core/timeline.py:1-5`, update the module docstring so it no longer claims to be a compatibility re-export shim.

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest -q
```


---

## Step 11 — Plan 01 Final Review, Release Notes, Commit & Tag (`v2.14.1`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 11 with Gemini Flash. Final code review, i18n catalog verification, `RELEASE_NOTES.md` authoring, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.14.1`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Code Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_01` (`G-01`, `G-03`, `A-01`..`A-07`, `A-10`, `A-11`). Verify no unintended edits or debug leftovers exist.
  2. **Run Full Verification Suite:**
     ```powershell
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     python tools/i18n.py check
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
     All tests and `tools/i18n.py check` must pass with exit code `0`.
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.14.1` (exact match for the git tag).
     - Prepend a `## v2.14.1` section at the top of `RELEASE_NOTES.md` summarizing all fixes from Plan 01 (watchlist state persistence fix, parallel download workdir isolation, `src.id` path sanitization, `--download-archive` enforcement, subprocess cancel race fix, non-Twitch aligned section guard, Windows reserved filename filtering, and template error handling).
  4. **Commit & Tag Release `v2.14.1`:**
     - Mark Step 11 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.14.1): complete Plan 01 critical data pipeline and watchlist fixes`, and create annotated tag `git tag -a v2.14.1 -m "LuckyDownloader v2.14.1"`.
     - *(Ask the user before running `git push && git push origin v2.14.1`, or push if instructed.)*
