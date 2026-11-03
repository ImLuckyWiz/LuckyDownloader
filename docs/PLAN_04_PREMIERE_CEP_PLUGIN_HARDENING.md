# Plan 04 — Priority 4: Premiere Pro CEP Plugin Security & Bug Fixes

- **Priority:** 4 (Hardens the Premiere Pro CEP extension against RCE/XSS, secures the ZXP packager, and fixes duplicate/unused preference functions in `markers-core.js`)
- **Findings Covered:** `F-01`, `F-02`, `F-03`, `F-04`, `F-05`
- **Recommended Model:** **Gemini Flash** for all 5 steps (all changes are self-contained and verified by `npm test` and `pytest`)

---

## Step 1 — Remove Unused `--enable-nodejs`/`--mixed-context` and Gate `.debug` on Dev Flag (`F-01`, High)

- **Model:** Gemini Flash
- **Files:**
  - `premiere-plugin-cep/cep-panel/CSXS/manifest.xml` (lines 14–19)
  - `premiere-plugin-cep/install.ps1` (lines 1–60)
  - `premiere-plugin-cep/install-mac.command` (lines 1–42)
  - `tools/package_cep.py` (lines 90–145)
- **Problem:**
  1. `manifest.xml` declares `<Parameter>--enable-nodejs</Parameter>` and `<Parameter>--mixed-context</Parameter>`, even though the CEP panel (`csinterface-shim.js`, `runner.js`, `ui.js`) uses only `window.__adobe_cep__` and `fetch()` and never calls `require()` or `cep_node`.
  2. `install.ps1`, `install-mac.command`, and `tools/package_cep.py` unconditionally copy `.debug` (opening Chrome DevTools port `8088` on localhost) and set `PlayerDebugMode = "1"`.

### Instructions for Step 1

#### 1A. Remove `--enable-nodejs` and `--mixed-context` in `premiere-plugin-cep/cep-panel/CSXS/manifest.xml`
##### Before (`premiere-plugin-cep/cep-panel/CSXS/manifest.xml:14-19`)
```xml
        <CEFCommandLine>
          <Parameter>--enable-nodejs</Parameter>
          <Parameter>--mixed-context</Parameter>
        </CEFCommandLine>
```

##### After (`premiere-plugin-cep/cep-panel/CSXS/manifest.xml:14-16`)
```xml
        <CEFCommandLine />
```

#### 1B. Exclude `.debug` From Production ZXP Archive (`tools/package_cep.py:96`)
In `tools/package_cep.py:96`, add `".debug"` to `STAGE_EXCLUDES`:
```python
STAGE_EXCLUDES = {".DS_Store", "Thumbs.db", ".git", "__pycache__", ".debug"}
```

#### 1C. Gate `.debug` Copy in `premiere-plugin-cep/install.ps1` and `install-mac.command`
In `premiere-plugin-cep/install.ps1`, add `[switch]$Dev` to `param(...)` at the top of the script and only copy `.debug` when `$Dev` is passed:
```powershell
if ($Dev -and (Test-Path (Join-Path $RepoRoot ".debug"))) {
    Copy-Item (Join-Path $RepoRoot ".debug") (Join-Path $Target ".debug") -Force
}
```
In `premiere-plugin-cep/install-mac.command`, only copy `.debug` when `"$1" = "--dev"`:
```bash
if [ "$1" = "--dev" ] && [ -f "$HERE/.debug" ]; then
    cp "$HERE/.debug" "$TARGET/.debug"
fi
```

### Verification
```powershell
Push-Location premiere-plugin-cep; npm test; Pop-Location
```

---

## Step 2 — Replace `innerHTML` Concatenation With Safe DOM Nodes in `ui.js` (`F-02`, Medium)

- **Model:** Gemini Flash
- **File:** `premiere-plugin-cep/cep-panel/js/ui.js` (lines 52–65 and 245–256)
- **Problem:** `populateGames(payload)` and `populateRecipes()` concatenate `g` (`payload.games` from `.markers.json` / Twitch metadata) and `r.label` into `sel.innerHTML += '<option value="' + g + '">' + g + '</option>'`. If a game/category name contains `<img src=x onerror=...>` or `"`, it breaks the `<option>` markup or executes JS in the CEP context.

### Instructions for Step 2

#### Before (`premiere-plugin-cep/cep-panel/js/ui.js:52-63`)
```javascript
  function populateGames(payload) {
    var sel = $("flt-game");
    if (!sel) return;
    var games = C.uniqueGames(payload);
    sel.innerHTML = '<option value="">All games (' + games.length + ')</option>';
    for (var i = 0; i < games.length; i++) {
      var g = games[i];
      sel.innerHTML += '<option value="' + g.replace(/"/g, "&quot;") + '">' + g + '</option>';
    }
  }
```

#### After (`premiere-plugin-cep/cep-panel/js/ui.js:52-68`)
```javascript
  function populateGames(payload) {
    var sel = $("flt-game");
    if (!sel) return;
    var games = C.uniqueGames(payload);
    sel.textContent = "";
    var allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = "All games (" + games.length + ")";
    sel.appendChild(allOpt);
    for (var i = 0; i < games.length; i++) {
      var opt = document.createElement("option");
      opt.value = games[i];
      opt.textContent = games[i];
      sel.appendChild(opt);
    }
  }
```

Apply the same `document.createElement("option")` + `opt.textContent = r.label` pattern to `populateRecipes()` (`premiere-plugin-cep/cep-panel/js/ui.js:245-255`).

### Verification
```powershell
Push-Location premiere-plugin-cep; npm test; Pop-Location
```

---

## Step 3 — Verify `ZXPSignCmd` SHA-256 and Read Cert Password From Env (`F-03`, Medium)

- **Model:** Gemini Flash
- **File:** `tools/package_cep.py` (lines 36–82 and 220–235)
- **Problem:**
  1. `tools/package_cep.py` downloads `ZXPSignCmd` binaries over HTTPS without verifying SHA-256 digests before executing them (`chmod 0o755` + `subprocess.run`).
  2. `CERT_PASSWORD = "luckydownloader-selfsigned"` is hardcoded instead of reading `os.environ.get("CEP_CERT_PASSWORD")`.

### Instructions for Step 3
1. In `tools/package_cep.py:42`, read `CERT_PASSWORD` from the environment with a fallback for local dev builds:
   ```python
   CERT_PASSWORD = os.environ.get("CEP_CERT_PASSWORD") or "luckydownloader-selfsigned"
   ```
2. Add a `ZXPSIGN_SHA256: dict[str, str]` dictionary next to `ZXPSIGN_URLS` in `tools/package_cep.py`, compute `hashlib.sha256(dest.read_bytes()).hexdigest().lower()` after `urllib.request.urlretrieve(url, dest)`, and raise `RuntimeError` (deleting `dest`) if the hash does not match.

---

## Step 4 — Remove Duplicate Functions in `markers-core.js` and Wire `applyPreferences` in `runner.js` (`F-04`, Medium)

- **Model:** Gemini Flash
- **Files:**
  - `premiere-plugin-cep/src/markers-core.js` (lines 207–245)
  - `premiere-plugin-cep/cep-panel/js/runner.js` (lines 229–271)
  - `docs/markers-format.md` (lines 35–40)
- **Problem:**
  1. `applyPreferences` and `applyRecipe` are defined twice in `premiere-plugin-cep/src/markers-core.js`: lines 207–245 (dead copies) and lines 331–389 (the real implementations that shadow the first ones).
  2. `docs/markers-format.md` lines 37 and 38 duplicate the `source.streamer` table row.
  3. `runner.js` (`loadJsonFromPath`) never calls `C.applyPreferences(payload, opts)` when loading a `.markers.json` file, so `preferences.import_chapters`, `import_moments`, `import_muted`, and `color_by_category` exported by Python (`core/premiere_export.py:224-229`) are ignored by the CEP UI.

### Instructions for Step 4
1. Delete the dead duplicate definitions of `applyPreferences` and `applyRecipe` at lines 207–245 of `premiere-plugin-cep/src/markers-core.js` (keep the canonical definitions at lines 331–389).
2. In `docs/markers-format.md:37-38`, delete one of the two identical `| source.streamer | ... |` rows.
3. In `premiere-plugin-cep/cep-panel/js/runner.js`, inside `loadJsonFromPath` after validating `res.payload`, call `C.applyPreferences(res.payload, currentFormState)` (or update the UI checkboxes `#chk-chapters`, `#chk-moments`, `#chk-muted`, `#chk-color-cat` when `res.payload.preferences` is present) before rendering the preview.

### Verification
```powershell
Push-Location premiere-plugin-cep; npm test; Pop-Location
```

---

## Step 5 — Populate `source.id` for Non-Twitch Sources in `premiere_export.py` and Sync Docs (`F-05`, Low)

- **Model:** Gemini Flash
- **Files:**
  - `core/premiere_export.py` (lines 180–187)
  - `docs/markers-format.md` (lines 58–63)
- **Instructions:**
  1. In `core/premiere_export.py:182`, fall back to `source.id` when `source.twitch_vod_id` is empty:
     ```python
     "id": str(getattr(source, "twitch_vod_id", "") or getattr(source, "id", "") or ""),
     ```
  2. In `docs/markers-format.md:59-62`, update the `"muted"` marker type note to match the current implementation (used when `preferences.import_muted` is enabled).

### Verification
```powershell
pytest tests/test_premiere_export.py -q
Push-Location premiere-plugin-cep; npm test; Pop-Location
```


---

## Step 6 — Plan 04 Final Review, Release Notes, Commit & Tag (`v2.14.4`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 6 with Gemini Flash. Even though Steps 1–5 of Plan 04 are executed by Gemini Flash, the final review, `RELEASE_NOTES.md` preparation, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.14.4`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_04` (`F-01`..`F-05`).
  2. **Run Full Verification Suite:**
     ```powershell
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     python tools/i18n.py check
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.14.4`.
     - **Public-Facing Language:** Ensure notes are written for end users (Premiere Pro plugin security, stability, marker accuracy) without internal jargon, plan IDs, or audit codes.
     - Prepend a `## v2.14.4` section at the top of `RELEASE_NOTES.md` summarizing all Premiere Pro CEP plugin fixes from Plan 04 (removing `--enable-nodejs`/`--mixed-context` from `manifest.xml`, gating `.debug` port on `--dev`/`-Dev`, eliminating `innerHTML` DOM XSS in `ui.js`, verifying `ZXPSignCmd` SHA-256 digests, removing duplicate functions in `markers-core.js`, and applying `.markers.json` `preferences` on load).
  4. **Commit & Tag Release `v2.14.4`:**
     - Mark Step 6 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.14.4): complete Plan 04 Premiere Pro CEP plugin hardening and fixes`, and create annotated tag `git tag -a v2.14.4 -m "LuckyDownloader v2.14.4"`.
