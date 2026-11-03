# Plan 03 — Priority 3: Qt UI Lifecycle, Parallel Queue & Win32 Native Frame Fixes

- **Priority:** 3 (Fixes parallel worker thread leaks on window close, signal leaks, duplicate dialogs, shimmer timer CPU usage, and Win32 caption button hit-testing)
- **Findings Covered:** `D-01`, `D-02`, `D-03` (Old Audit A1), `D-04` (Old Audit A5/A6), `D-05`, `D-06`, `D-07`, `D-08`, `D-09`, `E-01`, `E-02`, `E-03`
- **Recommended Model:**
  - **Steps 1, 2, 3, 5, 7, 8, 9, 10, 12:** Safe for **Gemini Flash**
  - **Steps 4 (`D-04`), 6 (`D-06`), 11 (`E-02`):** Recommended for **Argon or Claude Sonnet**

---

## Step 1 — Fix `MainWindow.closeEvent` Leaking Parallel Queue Workers (`D-01`, High)

- **Model:** Gemini Flash
- **File:** `qt_ui/main_window.py` (lines 1054–1068)
- **Problem:** `MainWindow.closeEvent` calls `self._queue_runner.ctx.cancel()`. In parallel mode (`max_workers > 1`), `QueueRunner` creates a per-worker `Ctx` in `self._active_workers: dict[int, Ctx]`, while `self._queue_runner.ctx` is only a dummy `Ctx`. Calling `.ctx.cancel()` instead of `.cancel()` leaves active `yt-dlp`/`ffmpeg` subprocesses running after the window closes.

### Instructions for Step 1
In `qt_ui/main_window.py:1058-1064`, call `self._queue_runner.cancel()` and `self._info_runner.cancel()`.

#### Before (`qt_ui/main_window.py:1058-1064`)
```python
        for runner in (self._info_runner, self._queue_runner):
            if runner is not None:
                try:
                    runner.ctx.cancel()
                except Exception as e:
                    log.debug("Cancel runner on close failed: %s", e)
```

#### After (`qt_ui/main_window.py:1058-1067`)
```python
        for runner in (self._info_runner, self._queue_runner):
            if runner is not None:
                try:
                    if hasattr(runner, "cancel"):
                        runner.cancel()
                    elif getattr(runner, "ctx", None) is not None:
                        runner.ctx.cancel()
                except Exception as e:
                    log.debug("Cancel runner on close failed: %s", e)
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_qt_main_window.py tests/test_qt_smoke.py -q
```

---

## Step 2 — Fix `QueueTab` Signal Leak on `language_bus().changed` (`D-02`, High)

- **Model:** Gemini Flash
- **File:** `qt_ui/tabs/queue.py` (lines 140–230)
- **Problem:** `language_bus().changed.connect(self.refresh_language)` is placed at the bottom of `QueueTab._sync_running()` (`qt_ui/tabs/queue.py:221`), which is called at the start and end of every queue job. After `N` jobs, `self.refresh_language` is connected `2N + 1` times.

### Instructions for Step 2
Move `language_bus().changed.connect(self.refresh_language)` out of `_sync_running()` and into the end of `QueueTab.__init__()`.

#### Before (`qt_ui/tabs/queue.py:216-222`)
```python
        self.pause_btn.setVisible(running)
        self.cancel_btn.setVisible(running)
        self.run_btn.setVisible(not running)
        self._update_empty_state()

        language_bus().changed.connect(self.refresh_language)
```

#### After (`qt_ui/tabs/queue.py:216-220`)
```python
        self.pause_btn.setVisible(running)
        self.cancel_btn.setVisible(running)
        self.run_btn.setVisible(not running)
        self._update_empty_state()
```
And at the end of `QueueTab.__init__` (right after `self._sync_running(False)` around line 150):
```python
        language_bus().changed.connect(self.refresh_language)
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_qt_smoke.py -q
```

---

## Step 3 — Remove Duplicate `history_btn.clicked` Connection (`D-03`, Medium / Old Audit A1)

- **Model:** Gemini Flash
- **File:** `qt_ui/main_window.py` (lines 262–268)
- **Problem:** `self.history_btn.clicked.connect(self._open_history)` is called on two consecutive lines (`265` and `266`), opening two stacked modal `HistoryDialog` instances on one click.

### Instructions for Step 3
Delete the duplicate line `266` in `qt_ui/main_window.py`.

#### Before (`qt_ui/main_window.py:264-267`)
```python
        self.history_btn = self.shell.history_btn
        self.history_btn.clicked.connect(self._open_history)
        self.history_btn.clicked.connect(self._open_history)
```

#### After (`qt_ui/main_window.py:264-266`)
```python
        self.history_btn = self.shell.history_btn
        self.history_btn.clicked.connect(self._open_history)
```

---

## Step 4 — Aggregate Parallel Worker Progress and Rate Limits (`D-04`, Medium / Old Audit A5 & A6)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> `QueueRunner` (`qt_ui/queue_runner.py`) coordinates signals between worker threads, `QueueTableModel`, and `MainWindow._on_queue_progress`. Execute this step with **Argon or Claude Sonnet**.

- **Files:** `qt_ui/queue_runner.py` (lines 80–120) and `qt_ui/main_window.py` (lines 1098–1114)
- **Problem:**
  1. When `max_workers > 1`, each worker emits `self.progress.emit(frac, label)` with its own `0..1` fraction, causing the global progress bar to jump back and forth between concurrent jobs.
  2. Each worker gets the full `rate_limit` setting (e.g., `5M`), resulting in `N * rate_limit` aggregate bandwidth.

### Instructions for Step 4
1. In `QueueRunner` (`qt_ui/queue_runner.py`), track per-row progress in `self._worker_progress: dict[int, float]` and emit the mean progress across active/total items on `self.progress.emit(overall_frac, label)`.
2. When `max_workers > 1` and `opts.rate_limit` is set (e.g., `"5M"` or `"500K"`), either divide the numeric rate limit by `len(active_workers)` or update the Options tab tooltip/label to clarify `"Rate limit (per active download)"`.

---

## Step 5 — Stop `QueueRowDelegate._shimmer_timer` When No Job Is Running (`D-05`, Medium)

- **Model:** Gemini Flash
- **File:** `qt_ui/tabs/queue.py` (lines 85–110)
- **Problem:** `QueueRowDelegate._tick_shimmer()` only stops the 40 ms (25 FPS) timer when `m.rowCount() == 0`. Once any completed or pending row is in the queue, the timer ticks forever even when all jobs are idle.

### Instructions for Step 5
In `QueueRowDelegate._tick_shimmer()` (`qt_ui/tabs/queue.py:92-102`), stop `self._shimmer_timer` whenever `not has_running`.

#### Before (`qt_ui/tabs/queue.py:92-102`)
```python
    def _tick_shimmer(self) -> None:
        m = self._view.model()
        if m is None or m.rowCount() == 0:
            self._shimmer_timer.stop()
            return
        self._shimmer_phase = (self._shimmer_phase + 0.04) % 1.0
        has_running = False
        for row in range(m.rowCount()):
            idx = m.index(row, 0)
            if idx.data(ROLE_STATUS) == "running":
                has_running = True
                self._view.update(idx)
```

#### After (`qt_ui/tabs/queue.py:92-105`)
```python
    def _tick_shimmer(self) -> None:
        m = self._view.model()
        if m is None or m.rowCount() == 0:
            self._shimmer_timer.stop()
            return
        self._shimmer_phase = (self._shimmer_phase + 0.04) % 1.0
        has_running = False
        for row in range(m.rowCount()):
            idx = m.index(row, 0)
            if idx.data(ROLE_STATUS) == "running":
                has_running = True
                self._view.update(idx)
        if not has_running:
            self._shimmer_timer.stop()
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_qt_smoke.py -q
```

---

## Step 6 — Move `TwitchClient.refresh_token()` Off the Qt GUI Thread (`D-06`, Medium)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Moving `refresh_token()` into a `QThread` in `TwitchCredentialsDialog._test()` (`qt_ui/twitch_dialog.py:173-191`) and `SearchTab._ensure_client()` (`qt_ui/tabs/search.py:259-277`) requires managing button disabled states and thread lifecycle on dialog close. Assign to **Argon or Claude Sonnet**.

- **Files:** `qt_ui/twitch_dialog.py` (lines 173–191) and `qt_ui/tabs/search.py` (lines 259–277)
- **Instructions:**
  1. In `qt_ui/tabs/search.py`, remove `client.refresh_token()` from `_ensure_client()` on the GUI thread and let `_SearchWorker.run()` (which already runs on a background `QThread`) perform the token refresh when `not client.access_token`.
  2. In `qt_ui/twitch_dialog.py`, run `client.refresh_token()` inside a small `QThread` worker while disabling the Test button (`self.test_btn.setEnabled(False)`), updating `self.status_lbl` via a Qt signal when finished.

---

## Step 7 — Guard Async Thumbnail Callbacks Against Stale URLs (`D-07`, Low)

- **Model:** Gemini Flash
- **File:** `qt_ui/tabs/plan.py` (lines 926–961)
- **Problem:** When the user switches between two sources quickly, an earlier thumbnail HTTP request can finish after the newer one and overwrite `self.thumb_label` with the previous video's thumbnail.

### Instructions for Step 7
Store `self._expected_thumb_url = url` before launching `_ThumbLoader(url)` in `PlanTab._load_thumbnail`, and verify `url == getattr(self, "_expected_thumb_url", None)` inside `_on_thumb_data`.

---

## Step 8 — Synchronize `ShortcutsDialog` With Actual `MainWindow` Shortcuts (`D-08`, Low)

- **Model:** Gemini Flash
- **File:** `qt_ui/dialogs.py` (lines 239–274)
- **Problem:** `ShortcutsDialog` lists `Ctrl+I` for `"Import queue"` and `Ctrl+O` for `"Export queue"`, whereas `MainWindow._setup_shortcuts` (`qt_ui/main_window.py:296-306`) binds `Ctrl+I` to `_focus_url` (`"Focus URL bar"`), `Ctrl+O` to `_import_queue` (`"Import queue"`), `Ctrl+E` to `_export_queue` (`"Export queue"`), and `F2` to `"Rename range"` in `PlanTab`.

### Instructions for Step 8
Update the `rows` list in `ShortcutsDialog.__init__` (`qt_ui/dialogs.py:249-260`) to match `MainWindow._setup_shortcuts`:

#### Before (`qt_ui/dialogs.py:254-258`)
```python
            ("Ctrl+I", t("Import queue")),
            ("Ctrl+O", t("Export queue")),
```

#### After (`qt_ui/dialogs.py:254-260`)
```python
            ("Ctrl+I", t("Focus URL bar")),
            ("Ctrl+O", t("Import queue")),
            ("Ctrl+E", t("Export queue")),
            ("F2", t("Rename selected segment")),
```

---

## Step 9 — Fix Double Translation `t(t(...))` and Dead `row_number` Attribute (`D-09`, Nit)

- **Model:** Gemini Flash
- **Files:** `qt_ui/welcome/overlay.py` (line 78) and `qt_ui/queue_model.py` (line 255)
- **Instructions:**
  1. In `qt_ui/welcome/overlay.py:78`, change `self._next_btn.setText(t(t("Next →")))` to `self._next_btn.setText(t("Next →"))`.
  2. In `qt_ui/queue_model.py:255`, change `num = getattr(item, "row_number", row + 1)` to `num = getattr(item, "n", row + 1)`.

---

## Step 10 — Fix Top 6 px Resize Border Blocking Titlebar Caption Buttons (`E-01`, Medium)

- **Model:** Gemini Flash
- **File:** `qt_ui/frameless.py` (lines 78–125)
- **Problem:** `FramelessController.hit_test()` returns `HTTOP` (`y < b`, top 6 px) **before** checking whether the cursor is over `self._titlebar` interactive widgets (Minimize, Maximize, Close buttons) and **without** skipping resize borders when the window is maximized (`isMaximized()`). Consequently, moving the mouse to the top-right corner when maximized returns `HTTOP` / `HTTOPRIGHT` instead of letting the user click the Close (`✕`) button (Fitts's Law broken).

### Instructions for Step 10
In `FramelessController.hit_test()` (`qt_ui/frameless.py:85-124`):
1. Skip resize border checks (`top`, `bottom`, `left`, `right`) when `self._window.isMaximized() or self._window.isFullScreen()`.
2. Check if the cursor is over an interactive child widget of `self._titlebar` (buttons, combos) **before** returning `HTTOP`.

#### Before (`qt_ui/frameless.py:88-124`)
```python
        b = self._border
        left = x < b
        right = x >= w - b
        top = y < b
        bottom = y >= h - b

        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM

        if self._titlebar is not None and self._titlebar.isVisible():
            tb_pos = self._titlebar.mapFromGlobal(QPoint(gx, gy))
            if self._titlebar.rect().contains(tb_pos):
                if self._titlebar.is_caption_at(tb_pos):
                    return HTCAPTION
                return HTCLIENT
```

#### After (`qt_ui/frameless.py:88-130`)
```python
        # Check interactive titlebar buttons first so top-edge Fitts's Law clicks
        # on Minimize/Maximize/Close are never swallowed by the 6px HTTOP resize zone.
        if self._titlebar is not None and self._titlebar.isVisible():
            tb_pos = self._titlebar.mapFromGlobal(QPoint(gx, gy))
            if self._titlebar.rect().contains(tb_pos):
                if not self._titlebar.is_caption_at(tb_pos):
                    return HTCLIENT

        if not (self._window.isMaximized() or self._window.isFullScreen()):
            b = self._border
            left = x < b
            right = x >= w - b
            top = y < b
            bottom = y >= h - b

            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM

        if self._titlebar is not None and self._titlebar.isVisible():
            tb_pos = self._titlebar.mapFromGlobal(QPoint(gx, gy))
            if self._titlebar.rect().contains(tb_pos):
                if self._titlebar.is_caption_at(tb_pos):
                    return HTCAPTION
                return HTCLIENT
```

### Verification
```powershell
$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_qt_smoke.py -q
```

---

## Step 11 — Add Explicit 64-Bit `ctypes` `argtypes`/`restype` in `qt_ui/frameless.py` (`E-02`, Low)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Incorrect `ctypes` structure packing or `WNDPROCTYPE` / `HMONITOR` declarations on 64-bit Windows can cause native access violations. Assign Step 11 to **Argon or Claude Sonnet**.

- **File:** `qt_ui/frameless.py` (lines 343–443)
- **Instructions:**
  Declare explicit `argtypes` and `restype` once at module initialization (when `sys.platform == "win32"`) for:
  - `user32.MonitorFromWindow` (`[wintypes.HWND, wintypes.DWORD] -> wintypes.HMONITOR`)
  - `user32.GetMonitorInfoW` (`[wintypes.HMONITOR, ctypes.c_void_p] -> wintypes.BOOL`)
  - `user32.GetWindowLongW` / `user32.SetWindowLongW`
  - `user32.SetWindowPos`
  - `dwmapi.DwmSetWindowAttribute` and `dwmapi.DwmExtendFrameIntoClientArea`
  - `shell32.SHAppBarMessage` (`[wintypes.DWORD, ctypes.c_void_p] -> ctypes.c_size_t`)

---

## Step 12 — Check Per-Monitor Auto-Hide Taskbar Alongside `ABM_GETSTATE` (`E-03`, Low)

- **Model:** Gemini Flash
- **File:** `qt_ui/frameless.py` (lines 363–381)
- **Instructions:**
  In `_has_autohide_taskbar()`, keep the fast `ABM_GETSTATE` check and, if `rc_work == rc_monitor` on a maximized monitor (`_adjust_maximized_rect` at line 426), always apply the 1 px bottom inset (`rect.bottom -= 1`) so Windows DWM does not blank out an auto-hide taskbar on secondary monitors.


---

## Step 13 — Plan 03 Final Review, Release Notes, Commit & Tag (`v2.14.3`)

> [!WARNING]
> **Disclaimer — Recommended Model: Argon or Claude Sonnet**
> Do **not** run Step 13 with Gemini Flash. Final code review, Qt UI & Win32 verification, `RELEASE_NOTES.md` authoring, git commit, and release tagging must be executed by **Argon or Claude Sonnet**.

- **Target Release Tag:** `v2.14.3`
- **Instructions for Argon / Claude Sonnet:**
  1. **Full Diff & Review:** Run `git status` and `git diff` to audit every file changed during `PLAN_03` (`D-01`..`D-09`, `E-01`..`E-03`).
  2. **Run Full Verification Suite:**
     ```powershell
     $env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests -q
     python tools/i18n.py check
     Push-Location premiere-plugin-cep; npm test; Pop-Location
     ```
  3. **Update `RELEASE_NOTES.md`:**
     - **CRITICAL CI RULE (`.github/workflows/build.yml:51-56`):** The very first line of `RELEASE_NOTES.md` **must** be `## v2.14.3`.
     - **Public-Facing Language:** Ensure notes are written for end users (UI responsiveness, smoother downloads, window control fixes) without internal jargon, plan IDs, or audit codes.
     - Prepend a `## v2.14.3` section at the top of `RELEASE_NOTES.md` summarizing all Qt UI, parallel queue, and Win32 native frame fixes from Plan 03 (cancelling all active parallel workers on window close, fixing `QueueTab` language signal leak, fixing duplicate History dialog, aggregating parallel queue progress & rate limits, stopping idle shimmer timer repaints, moving Twitch token refresh off the GUI thread, and fixing maximized top-edge caption button clicks on Windows).
  4. **Commit & Tag Release `v2.14.3`:**
     - Mark Step 13 `[x]` in `docs/PLAN_00_MASTER_INDEX.md`.
     - Stage all modified files (`git add -A`), commit with message `release(v2.14.3): complete Plan 03 Qt UI lifecycle, parallel queue, and Win32 fixes`, and create annotated tag `git tag -a v2.14.3 -m "LuckyDownloader v2.14.3"`.
