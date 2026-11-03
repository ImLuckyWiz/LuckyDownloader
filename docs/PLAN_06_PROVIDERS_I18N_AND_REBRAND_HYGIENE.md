# Plan 06 — Priority 6: Providers, i18n & Rebrand Hygiene Fixes

- **Priority:** 6 (Fixes YouTube channel URL detection, Twitch clip format strings, YouTube-scoped CLI flags, i18n string extraction, and leftover `LuckyTwitch` branding)
- **Findings Covered:** `B-01`, `B-02`, `B-03`, `B-04`, `B-05`, `G-05`, `H-01`, `H-02`, `H-03`, `K-01`, `K-02`, `K-03`, `K-04`
- **Recommended Model:**
  - **Steps 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13:** Safe for **Gemini Flash**
  - **Step 3 (`B-03`):** Recommended for **Argon or Claude Sonnet**

---

## Step 1 — Normalize `YoutubeTab` Extractor Names and Channel URLs (`B-01`, Medium)

- **Model:** Gemini Flash
- **Files:** `core/source_info.py` (lines 480–490) and `core/providers/detect.py` (lines 75–139)
- **Problem:** When given a YouTube channel tab URL (`https://www.youtube.com/@handle/videos`), `yt-dlp` returns `extractor_key = "YoutubeTab"` (`extractor.lower() == "youtube:tab"`). `core/source_info.py:483` sets `site = raw_ext.split(":")[0]` (`"youtube"`), or if `extractor_key` is used it becomes `"youtubetab"`, and `detect_provider()` does not match `/@handle` channel paths as `YOUTUBE_PROVIDER` video/playlist URLs.

### Instructions for Step 1
1. In `core/source_info.py:483-486`, normalize known `yt-dlp` extractor prefixes:
   ```python
   raw_ext = (info.get("extractor") or info.get("extractor_key") or "generic").lower()
   site = raw_ext.split(":")[0]
   if site.startswith("youtube"):
       site = "youtube"
   elif site.startswith("twitch"):
       site = "twitch"
   ```
2. In `core/providers/detect.py`, ensure `youtube.com/@...`, `youtube.com/channel/...`, and `youtube.com/c/...` resolve to `YOUTUBE_PROVIDER` with `kind="playlist"`.

### Verification
```powershell
pytest tests/test_providers_detect.py tests/test_providers_youtube.py tests/test_playlist.py -q
```

---

## Step 2 — Fix Twitch Clip Synthetic Format IDs vs `build_generic_format_string` (`B-02`, Medium)

- **Model:** Gemini Flash
- **Files:** `core/source_info.py` (lines 555–573) and `core/finalize.py` (lines 541–547)
- **Problem:** When a Twitch clip JSON has no `formats` array, `get_source_info` synthesizes `FormatChoice(id="best", ...)` (`core/source_info.py:567`), whereas `parse_clip_formats` (`core/source_info.py:434`) synthesizes `id="source"`. When `src.site != "twitch"` or `build_generic_format_string("source", src)` is used, `yt-dlp -f "source/best"` emits a warning if `"source"` is not an actual format ID.

### Instructions for Step 2
In `core/finalize.py:541-547` (`build_generic_format_string`), treat `fmt_id in ("best", "source", "")` identically as `"bestvideo+bestaudio/best"`:

```python
def build_generic_format_string(fmt_id: str, src: SourceInfo) -> str:
    if not fmt_id or fmt_id in ("best", "source"):
        return "bestvideo+bestaudio/best"
    if getattr(src, "format_Needs_audio_merge", False) or getattr(
        next((f for f in src.formats if f.id == fmt_id), None), "video_only", False
    ):
        return f"{fmt_id}+bestaudio/{fmt_id}/best"
    return f"{fmt_id}/best"
```

### Verification
```powershell
pytest tests/test_core_pipeline.py tests/test_finalize_unit.py -q
```

---

## Step 3 — Deduplicate `_run_ytdlp_json` Across `source_info.py`, `generic.py`, and `youtube.py` (`B-03`, Low)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Multiple test files (`test_source_info_unit.py`, `test_providers_generic.py`, `test_providers_youtube.py`) monkeypatch `_run_ytdlp_json` on individual modules (`core.source_info`, `core.providers.generic`, `core.providers.youtube`, or `luckytwitch_engine`). Consolidating these functions without breaking test monkeypatches requires preserving per-module wrapper hooks. Assign to **Argon or Claude Sonnet**.

- **Files:** `core/source_info.py:172-251`, `core/providers/generic.py:66-142`, `core/providers/youtube.py:121-190`
- **Instructions:**
  Keep `_run_ytdlp_json` in `core/source_info.py` as the single implementation (supporting an optional `is_youtube: bool` flag), and have `core/providers/generic.py` and `core/providers/youtube.py` delegate to `core.source_info._run_ytdlp_json` when their own module-level `_run_ytdlp_json` has not been monkeypatched.

---

## Step 4 — Scope YouTube `--extractor-args` and `--remote-components` to YouTube URLs (`B-04`, Low)

- **Model:** Gemini Flash
- **Files:** `core/download.py` (lines 296–335) and `core/source_info.py` (lines 180–205)
- **Problem:** `_ytdlp_base_args` in `core/download.py:326-327` and `_run_ytdlp_json` in `core/source_info.py:191-192` pass `--extractor-args youtube:player_client=default,-tv_simply` and `--remote-components ejs:github` to `yt-dlp` on every download (including Twitch, Kick, TikTok, and generic sites).

### Instructions for Step 4
Add a small helper `_is_youtube_url(url: str) -> bool` (checking if host is `youtube.com`, `www.youtube.com`, `m.youtube.com`, `music.youtube.com`, or `youtu.be`) and only append `--extractor-args youtube:...` and `--remote-components ejs:github` when `_is_youtube_url(url)` is `True`.

### Verification
```powershell
pytest tests/test_download_unit.py tests/test_source_info_unit.py tests/test_providers_youtube.py -q
```

---

## Step 5 — Validate Playlist Entry URLs and Add `--` Separator Before Target URLs (`B-05`, Low)

- **Model:** Gemini Flash
- **Files:** `core/source_info.py` (lines 496–503), `core/playlist.py` (lines 88–96), `core/download.py` (lines 341, 631)
- **Problem:**
  1. Playlist entry `url` values from flat playlist JSON are passed into `SourceInfo.url` without checking that they start with `http://` or `https://` (or resolving relative YouTube IDs to `https://www.youtube.com/watch?v=<id>`).
  2. `yt-dlp` CLI invocations append `[url]` without a preceding `"--"` option terminator.

### Instructions for Step 5
1. In `core/source_info.py:496-503`, if `entry_url` does not start with `("http://", "https://")`:
   - If `site == "youtube"` and `e.get("id")` matches `^[A-Za-z0-9_-]{11}$`, construct `f"https://www.youtube.com/watch?v={e['id']}"`.
   - Otherwise skip the entry (`continue`).
2. In `core/playlist.py:91`, skip any entry whose `entry.url` does not start with `("http://", "https://")`.

### Verification
```powershell
pytest tests/test_playlist.py tests/test_source_info_unit.py -q
```

---

## Step 6 — Fix `tools/i18n.py` Regex to Extract `_t("...")` Calls (`H-01`, Medium)

- **Model:** Gemini Flash
- **File:** `tools/i18n.py` (lines 555–565)
- **Problem:** `T_CALL_RE` in `tools/i18n.py:558-562` uses `r"""\bt\(\s*..."""`, which only matches `t("...")` and misses `_t("...")` in 6 Qt UI modules that import `from core.i18n import t as _t` (`qt_ui/chat_render_dialog.py`, `qt_ui/Drop_overlay.py`, `qt_ui/premiere_dialog.py`, `qt_ui/theme.py`, `qt_ui/twitch_dialog.py`, `qt_ui/watchlist_panel.py`).

### Instructions for Step 6
Update `T_CALL_RE` in `tools/i18n.py:558-562` from `\bt\(` to `\b_?t\(`:

#### Before (`tools/i18n.py:558-562`)
```python
T_CALL_RE = re.compile(
    r"""\bt\(\s*(?P<q>["'])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
    re.DOTALL,
)
```

#### After (`tools/i18n.py:558-562`)
```python
T_CALL_RE = re.compile(
    r"""\b_?t\(\s*(?P<q>["'])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
    re.DOTALL,
)
```

### Verification
```powershell
python tools/i18n.py check
```

---

## Step 7 — Wrap Untranslated User-Facing Strings in `t(...)` (`G-05`, Low)

- **Model:** Gemini Flash
- **Files:** `core/chat.py:97, 179`, `core/finalize.py:591, 616, 637, 672, 682, 709`, `core/updates.py:310-335`
- **Instructions:**
  Import `from core.i18n import t` in `core/chat.py`, `core/finalize.py`, and `core/updates.py`, wrap user-facing progress and error strings (such as `"Downloading chat..."`, `"Joining segments..."`, `"No SHA-256 checksum published for this release"`) in `t(...)`, and add their Spanish translations to `tools/i18n.py`.

---

## Step 8 — Recompile `.mo` Files and Sync `luckytwitch.mo` (`H-02` & `H-03`, Low/Nit)

- **Model:** Gemini Flash
- **Files:** `core/i18n.py` (lines 65–72), `tools/i18n.py`, `locale/es/LC_MESSAGES/`
- **Problem:**
  1. `H-03`: `core/i18n.py:67` checks `for domain in ("luckytwitch", "luckydownloader"):`, loading the stale 36 KB `luckytwitch.mo` ahead of the 48 KB `luckydownloader.mo`!
  2. `H-02`: `locale/es/LC_MESSAGES/luckytwitch.mo` is stale relative to `luckydownloader.po`.

### Instructions for Step 8
1. In `core/i18n.py:67`, swap the domain tuple order so `"luckydownloader"` is checked first:
   ```python
   for domain in ("luckydownloader", "luckytwitch"):
   ```
2. Run `python tools/i18n.py build` to regenerate `locale/es/LC_MESSAGES/luckydownloader.po` and `luckydownloader.mo`, and copy `luckydownloader.mo` over `locale/es/LC_MESSAGES/luckytwitch.mo` (or remove the stale `luckytwitch.mo` file).

### Verification
```powershell
python tools/i18n.py build
pytest tests/test_i18n.py -q
```

---

## Step 9 — Update Default `out_dir` and Windows `AppUserModelID` to `LuckyDownloader` (`K-01`, Medium)

- **Model:** Gemini Flash
- **Files:** `core/settings.py` (line 17) and `luckytwitch_qt.py` (lines 75–100)
- **Instructions:**
  1. In `core/settings.py:17`, change:
     ```python
     "out_dir": str(Path.home() / "Videos" / "LuckyTwitch"),
     ```
     to:
     ```python
     "out_dir": str(Path.home() / "Videos" / "LuckyDownloader"),
     ```
     *(Check if any test in `tests/test_core_helpers.py` asserts `"LuckyTwitch"` in `DEFAULTS["out_dir"]` and update that assertion if needed.)*
  2. In `luckytwitch_qt.py:78-96`, change `app.setApplicationName("LuckyTwitch")` to `app.setApplicationName("LuckyDownloader")` and `SetCurrentProcessExplicitAppUserModelID("LuckyDownloader.App.2")` (matching `installer.iss:22`).

---

## Step 10 — Flip `luckydownloader_*` vs `luckytwitch_*` Facade Direction (`K-02`, Low)

- **Model:** Gemini Flash
- **Files:** `luckydownloader_engine.py`, `luckytwitch_engine.py`, `luckydownloader_qt.py`, `luckytwitch_qt.py`
- **Instructions:**
  Add a clear module docstring to `luckytwitch_engine.py` and `luckytwitch_qt.py` noting that they are kept for backward-compatible test monkeypatching (`sys.modules["luckydownloader_engine"] = sys.modules[__name__]`), or move the canonical implementation into `luckydownloader_qt.py` and make `luckytwitch_qt.py` re-export it.

---

## Step 11 — Update `.gitignore` and Clean Up Duplicate Legacy Icon Assets (`K-03`, Low)

- **Model:** Gemini Flash
- **File:** `.gitignore` (lines 20–32)
- **Instructions:**
  Add `recent_searches.json` and `luckydownloader_queue.json` to the `# User data / runtime state` section of `.gitignore`:
  ```gitignore
  # User data / runtime state
  settings.json
  config.json
  history.json
  watchlist.json
  ui_state.json
  recent_searches.json
  luckydownloader_queue.json
  ```

---

## Step 12 — Update Stale `LuckyTwitch` Branding in `LICENSE`, `README.es.md`, and `docs/README.md` (`K-04`, Low)

- **Model:** Gemini Flash
- **Files:** `LICENSE` (line 12), `README.es.md` (lines 55–57), `docs/README.md` (lines 1–85)
- **Instructions:**
  1. In `LICENSE:12`, update `The software is provided under the name "LuckyTwitch"` to `"LuckyDownloader (formerly LuckyTwitch)"`.
  2. In `README.es.md:56`, update `python luckytwitch_qt.py` to `python luckydownloader_qt.py`.
  3. In `docs/README.md`, update the title and architecture tree so `luckydownloader_qt.py` / `luckydownloader_engine.py` are listed as primary entry points and `core/providers/`, `premiere-plugin-cep/`, and `REVIEW_2026_11.md` are indexed.

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest -q
```


---

## Step 13 — Plan 06 Final Review, Release Notes, Commit & Tag (`v2.14.6`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 13 with Gemini Flash. Final code review, i18n `.po`/`.mo` catalog verification, `RELEASE_NOTES.md` authoring, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.14.6`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_06` (`B-01`..`B-05`, `G-05`, `H-01`..`H-03`, `K-01`..`K-04`).
  2. **Rebuild & Check i18n Catalogs + Run Full Test Suite:**
     ```powershell
     python tools/i18n.py build
     python tools/i18n.py check
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.14.6`.
     - **Public-Facing Language:** Ensure notes are written for end users (provider improvements, translation accuracy, branding consistency) without internal jargon, plan IDs, or audit codes.
     - Prepend a `## v2.14.6` section at the top of `RELEASE_NOTES.md` summarizing all provider, i18n, and rebrand hygiene fixes from Plan 06 (YouTube channel tab detection, Twitch clip format handling, YouTube-scoped CLI flags, playlist URL validation, complete Spanish i18n extraction for `_t(...)` calls and rebuilt `.mo` catalogs, and `LuckyDownloader` branding alignment).
  4. **Commit & Tag Release `v2.14.6`:**
     - Mark Step 13 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.14.6): complete Plan 06 providers, i18n, and rebrand hygiene fixes`, and create annotated tag `git tag -a v2.14.6 -m "LuckyDownloader v2.14.6"`.
