"""The «Update available» dialog: display new version, release notes, and update actions."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import paths, updates
from core.i18n import t
from qt_ui.theme import dark_titlebar
from qt_ui.widgets import Card, WrapLabel


def clean_release_notes(notes: str, max_chars: int = 2500) -> str:
    """Strip raw HTML and markdown images from release notes and cap length."""
    if not notes:
        return t("No release notes provided.")
    text = re.sub(r"<[^>]+>", "", notes)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n… " + t("(Read the full notes on GitHub)")
    return text


class UpdateDialog(QDialog):
    def __init__(self, info: updates.UpdateInfo, host=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.info = info
        self.host = host
        self._download_ctx = None
        self._bridge = None
        self._runner = None

        self.setWindowTitle(t("Update available"))
        self.setModal(True)
        self.resize(540, 480)
        dark_titlebar(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # Header
        head_box = QVBoxLayout()
        head_box.setSpacing(4)
        title_lbl = QLabel(t("Update available"))
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
        current_ver = paths.BUNDLED_VERSION or t("dev build")
        sub_lbl = QLabel(t("LuckyDownloader {tag}   (you have {cur})", tag=info.tag, cur=current_ver))
        sub_lbl.setProperty("role", "muted")
        head_box.addWidget(title_lbl)
        head_box.addWidget(sub_lbl)
        root.addLayout(head_box)

        # Release notes card
        card = Card(title=t("What's new"), padding=14, parent=self)

        scroll = QScrollArea(card)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        notes_container = QWidget()
        notes_lay = QVBoxLayout(notes_container)
        notes_lay.setContentsMargins(0, 0, 8, 0)
        notes_lbl = WrapLabel(clean_release_notes(info.notes))
        notes_lbl.setProperty("role", "secondary")
        notes_lay.addWidget(notes_lbl)
        notes_lay.addStretch(1)
        scroll.setWidget(notes_container)
        card.add_widget(scroll)

        root.addWidget(card, 1)

        # Progress area (hidden initially)
        self.progress_container = QWidget(self)
        self.progress_container.setVisible(False)
        prog_lay = QVBoxLayout(self.progress_container)
        prog_lay.setContentsMargins(0, 0, 0, 0)
        prog_lay.setSpacing(4)
        self.progress_label = QLabel(self.progress_container)
        self.progress_label.setProperty("role", "secondary")
        self.progress_bar = QProgressBar(self.progress_container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        prog_lay.addWidget(self.progress_label)
        prog_lay.addWidget(self.progress_bar)
        root.addWidget(self.progress_container)

        # Muted reassurance notice
        notice_lbl = QLabel(t("Your settings, Twitch login and tools are kept."))
        notice_lbl.setProperty("role", "muted")
        root.addWidget(notice_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_update = QPushButton(t("Update now"))
        self.btn_update.setProperty("variant", "primary")
        self.btn_update.setDefault(True)
        self.btn_update.clicked.connect(self.on_update_now)
        btn_row.addWidget(self.btn_update)

        self.btn_release_page = QPushButton(t("Release page"))
        self.btn_release_page.clicked.connect(self.on_release_page)
        btn_row.addWidget(self.btn_release_page)

        self.btn_later = QPushButton(t("Later"))
        self.btn_later.clicked.connect(self.on_cancel_or_later)
        btn_row.addWidget(self.btn_later)

        btn_row.addStretch(1)

        self.btn_skip = QPushButton(t("Skip {tag}", tag=info.tag))
        self.btn_skip.clicked.connect(self.on_skip)
        btn_row.addWidget(self.btn_skip)

        root.addLayout(btn_row)

    def on_update_now(self) -> None:
        """Handle update action. On Windows with Inno Setup, downloads and executes silently.
        Otherwise opens release/asset page in default browser.
        """
        if not (updates.is_installed_setup() and self.info.asset_url and self.info.asset_name.endswith(".exe")):
            target_url = self.info.asset_url or self.info.page_url
            if target_url:
                QDesktopServices.openUrl(QUrl(target_url))
            self.accept()
            return

        if self.host:
            is_busy = False
            if hasattr(self.host, "tab_queue") and hasattr(self.host.tab_queue, "runner") and self.host.tab_queue.runner.is_running():
                is_busy = True
            elif getattr(self.host, "tools_busy", False) or getattr(self.host, "saved_chat_busy", False):
                is_busy = True
            if is_busy:
                from qt_ui import dialogs
                dialogs.info(self, t("Busy"), t("Wait for running downloads or tool tasks to finish before updating."))
                return

        self._start_download()

    def _start_download(self) -> None:
        from qt_ui.background_jobs import UpdateDownloadRunner
        from qt_ui.bridge import Bridge

        safe_tag = re.sub(r"[^A-Za-z0-9._-]", "_", self.info.tag or "latest")[:40]
        ext = ".exe" if sys.platform == "win32" else (".dmg" if sys.platform == "darwin" else ".AppImage")
        dest = updates.get_update_temp_dir() / f"LuckyDownloader-Setup-{safe_tag}{ext}"
        self.progress_container.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText(t("Downloading LuckyDownloader {tag}...", tag=self.info.tag))
        self.btn_update.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.btn_later.setText(t("Cancel"))

        self._bridge = Bridge()
        self._bridge.progress.connect(self._on_download_progress)
        self._bridge.update_download_done.connect(self._on_download_done)
        self._runner = UpdateDownloadRunner(self._bridge)
        self._download_ctx = self._runner.start(self.info, dest)

    def _on_download_progress(self, frac: float, text: str) -> None:
        self.progress_bar.setValue(int(frac * 100))
        self.progress_label.setText(text)

    def _on_download_done(self, dest_str: str, error: str) -> None:
        self._download_ctx = None
        if error:
            self.progress_bar.setVisible(False)
            self.progress_label.setText(error)
            self.btn_later.setText(t("Close"))
            self.btn_update.setText(t("Open release page"))
            self.btn_update.setEnabled(True)
            try:
                self.btn_update.clicked.disconnect()
            except RuntimeError:
                pass
            self.btn_update.clicked.connect(self.on_release_page)
            self.btn_skip.setEnabled(True)
            return

        from qt_ui import dialogs
        proceed = dialogs.ask_yes_no(
            self,
            t("Install and restart"),
            t("LuckyDownloader will close, update and reopen.\nSettings, Twitch login and tools are kept.\n\nDo you want to proceed?"),
        )
        if not proceed:
            self.progress_label.setText(t("Update ready to install."))
            self.btn_later.setText(t("Later"))
            self.btn_update.setText(t("Install now"))
            self.btn_update.setEnabled(True)
            try:
                self.btn_update.clicked.disconnect()
            except RuntimeError:
                pass
            self.btn_update.clicked.connect(lambda: self._install_and_restart(dest_str))
            return

        self._install_and_restart(dest_str)

    def _install_and_restart(self, dest_str: str) -> None:
        # Re-verify download digest/size before saving state or launching installer (C-02 / C-05 TOCTOU defense)
        sha256 = str(getattr(self.info, "sha256", "") or "").strip()
        asset_size = int(getattr(self.info, "asset_size", 0) or 0)
        if not sha256 or not updates.verify_download(Path(dest_str), asset_size, sha256):
            try:
                Path(dest_str).unlink(missing_ok=True)
            except OSError:
                pass
            self.progress_label.setText(t("Update verification failed."))
            return

        state = updates.load_state()
        state["installer_path"] = dest_str
        updates.save_state(state)

        ok = updates.launch_installer(dest_str, expected_sha256=sha256, expected_size=asset_size)
        if not ok:
            self.progress_label.setText(t("Could not start the installer."))
            self.btn_update.setText(t("Open release page"))
            self.btn_update.setEnabled(True)
            try:
                self.btn_update.clicked.disconnect()
            except RuntimeError:
                pass
            self.btn_update.clicked.connect(self.on_release_page)
            return

        self.accept()
        if self.host:
            self.host.close()

    def on_cancel_or_later(self) -> None:
        if self._download_ctx:
            self._download_ctx.cancel()
            self._download_ctx = None
            self.progress_label.setText(t("Update cancelled."))
            self.btn_later.setText(t("Later"))
            self.btn_update.setEnabled(True)
            self.btn_skip.setEnabled(True)
            return
        self.reject()

    def on_release_page(self) -> None:
        if self.info.page_url:
            QDesktopServices.openUrl(QUrl(self.info.page_url))

    def on_skip(self) -> None:
        state = updates.load_state()
        state["skipped_tag"] = self.info.tag
        updates.save_state(state)
        if self.host and hasattr(self.host, "on_update_skipped"):
            self.host.on_update_skipped(self.info.tag)
        self.reject()
