"""Tools setup (yt-dlp / ffmpeg) and application update check controller mixin for ``MainWindow``."""

from __future__ import annotations

from core import paths, updates
from core.i18n import t
from core.options import flag
from qt_ui import dialogs, notify


class UpdateControllerMixin:
    """Mixin for ``MainWindow`` handling external tools setup/updates and GitHub release checks."""

    def _set_update_pill_visible(self, visible: bool) -> None:
        from qt_ui.motion import DURATION_FAST, Motion, animate_opacity

        if not Motion.enabled() or not self.isVisible():
            self.update_pill.setVisible(visible)
            return

        if visible:
            if not self.update_pill.isVisible():
                self.update_pill.setVisible(True)
                animate_opacity(self.update_pill, 0.0, 1.0, DURATION_FAST)
        else:
            if self.update_pill.isVisible():
                animate_opacity(
                    self.update_pill, 1.0, 0.0, DURATION_FAST,
                    on_finished=lambda: self.update_pill.setVisible(False),
                )

    # ---------------------------- tools (yt-dlp / ffmpeg) ---------------------------- #
    def start_tools_setup(self, force: bool = False) -> None:
        """Download missing tools / update yt-dlp in the background (``luckytwitch_qt.main`` calls this at start)."""
        if self.tools_busy:
            return
        self.tools_busy = True
        self.info_btn.setEnabled(False)
        self.tab_options.set_tools_running(True)
        self.set_status(t("Preparing tools (yt-dlp, ffmpeg)…"))
        update = force or flag(self.settings, "auto_update")
        self.tools_ctx = self.tools_runner.start(update, force)

    def update_tools_now(self) -> None:
        if self.tab_queue.runner.is_running():
            dialogs.info(self, t("Running"), t("Wait for the running job to finish (or cancel it) first."))
            return
        self.start_tools_setup(force=True)

    def on_tools_done(self, error: str) -> None:
        self.tools_busy = False
        self.tools_ctx = None
        self.info_btn.setEnabled(True)
        self.tab_options.set_tools_running(False)
        self.set_progress(0, "")
        if error:
            self.log(f"Tools: {error}")
            self.set_status(t("Some tools are missing. See the log."))
            dialogs.warning(self, t("Tools"), error)
        else:
            self.set_status(t("Ready. Paste a VOD URL or ID and press «Get info»."))
            if getattr(self, "_pending_retry_url", None):
                retry_url = self._pending_retry_url
                self._pending_retry_url = None
                self.vod_entry.setText(retry_url)
                self.on_get_info()

    # ---------------------------- LuckyDownloader updates ---------------------------- #
    def start_update_check(self, force: bool = False, manual: bool | None = None) -> None:
        """Start background check for application updates on GitHub."""
        if manual is not None:
            force = manual

        if not force:
            if not self.settings.get("check_app_updates", True):
                return
            if not updates.is_valid_app_version(paths.BUNDLED_VERSION):
                return
        if self.tab_queue.runner.is_running() or self.tools_busy:
            if force:
                notify.info(self, t("Check updates"), t("Cannot check for updates while downloads or tools are busy."))
            return

        self._checking_updates_manually = force
        self.update_check_runner.start(force=force)

    def on_update_checked(self, info, error: str) -> None:
        manual = self._checking_updates_manually
        self._checking_updates_manually = False

        self.tab_options.refresh_app_update_state()

        if error:
            self.log(f"Updates: could not check: {error}")
            if manual:
                notify.info(self, t("Check updates"), t("Could not check for updates: {error}", error=error))
            return

        if info:
            self._update_info = info
            state = updates.load_state()
            is_skipped = state.get("skipped_tag") == info.tag
            if not is_skipped:
                self.update_pill.setText(t("● Update available · {version}", version=info.tag))
                self._set_update_pill_visible(True)
                if state.get("notified_tag") != info.tag:
                    state["notified_tag"] = info.tag
                    updates.save_state(state)
                    cur = paths.BUNDLED_VERSION or "current version"
                    notify.info(
                        self, t("Update available"),
                        t("LuckyDownloader {version} is out (you have {current}).", version=info.tag, current=cur),
                        action=(t("View update"), lambda: self.open_update_dialog(info)),
                        duration_ms=12000,
                    )
            else:
                self._set_update_pill_visible(False)
            if manual:
                self.open_update_dialog(info)
        else:
            self._set_update_pill_visible(False)
            if manual:
                cur = paths.BUNDLED_VERSION or "current version"
                notify.info(self, t("Up to date"), t("LuckyDownloader is up to date ({version}).", version=cur))

    def open_update_dialog(self, info=None) -> None:
        target = info or self._update_info
        if not target:
            state = updates.load_state()
            cached = state.get("cached")
            target = updates.UpdateInfo.from_dict(cached) if cached else None
        if not target:
            return
        from qt_ui.update_dialog import UpdateDialog
        dlg = UpdateDialog(target, host=self, parent=self)
        dlg.exec()

    def on_update_skipped(self, tag: str) -> None:
        self._set_update_pill_visible(False)
