"""Message boxes and system pickers, in one place, so the tabs call ``dialogs.info(...)`` and the tests replace
these functions.

Phase 9h (H1, H2): Themed custom dialogs with dark surfaces, vector icons, expandable error details fold,
and one-click 'Copy details' button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from core.palette import ACCENT, ERR, MUTED
from core.i18n import t, tn
from qt_ui.icons import icon, pixmap
from qt_ui.theme import mono_font


class ThemedDialog(QDialog):
    """Modern themed modal dialog with vector icon, summary, optional collapsible technical details,
    and styled action buttons (Phase 9h, H1, H2)."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        icon_name: str = "info",
        icon_colour: str = ACCENT,
        details: str | None = None,
        buttons: tuple[tuple[str, str, bool], ...] = (("OK", "accent", True),),
    ):
        super().__init__(parent)
        self.setObjectName("themedDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMaximumWidth(540)

        # Parse text into summary and details if details not explicitly given
        summary = text
        auto_details = details
        if auto_details is None and "\n" in text:
            parts = text.split("\n", 1)
            summary = parts[0].strip()
            auto_details = parts[1].strip()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 16)
        outer.setSpacing(14)

        # Header: Icon + Title & Summary
        head = QHBoxLayout()
        head.setSpacing(14)
        head.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.icon_lbl = QLabel(self)
        self.icon_lbl.setPixmap(pixmap(icon_name, 28, icon_colour, dpr=1.0))
        self.icon_lbl.setFixedSize(32, 32)
        head.addWidget(self.icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(6)
        self.title_lbl = QLabel(title, self)
        font = self.title_lbl.font()
        font.setPointSize(11)
        font.setBold(True)
        self.title_lbl.setFont(font)
        text_box.addWidget(self.title_lbl)

        self.summary_lbl = QLabel(summary, self)
        self.summary_lbl.setWordWrap(True)
        text_box.addWidget(self.summary_lbl)
        head.addLayout(text_box, 1)
        outer.addLayout(head)

        # Optional Collapsible Details (H2)
        self._details_text = auto_details
        self.toggle_details_btn: QPushButton | None = None
        self.copy_details_btn: QPushButton | None = None
        self.details_edit: QPlainTextEdit | None = None

        if auto_details:
            details_bar = QHBoxLayout()
            details_bar.setSpacing(8)
            self.toggle_details_btn = QPushButton(t("Show details"), self)
            self.toggle_details_btn.setProperty("variant", "ghost")
            self.toggle_details_btn.setIcon(icon("chevron-down", 14))
            self.toggle_details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.toggle_details_btn.clicked.connect(self._toggle_details)
            details_bar.addWidget(self.toggle_details_btn)

            details_bar.addStretch(1)

            self.copy_details_btn = QPushButton(t("Copy details"), self)
            self.copy_details_btn.setProperty("variant", "ghost")
            self.copy_details_btn.setIcon(icon("copy", 14))
            self.copy_details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.copy_details_btn.clicked.connect(self._copy_details)
            details_bar.addWidget(self.copy_details_btn)
            outer.addLayout(details_bar)

            self.details_edit = QPlainTextEdit(self)
            self.details_edit.setObjectName("dialogDetails")
            self.details_edit.setPlainText(auto_details)
            self.details_edit.setReadOnly(True)
            self.details_edit.setFont(mono_font())
            self.details_edit.setFixedHeight(120)
            self.details_edit.setVisible(False)
            outer.addWidget(self.details_edit)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self.action_buttons: list[QPushButton] = []
        for btn_label, variant, is_accept in buttons:
            btn = QPushButton(btn_label, self)
            if variant:
                btn.setProperty("variant", variant)
            if is_accept:
                btn.setDefault(True)
                btn.clicked.connect(self.accept)
            else:
                btn.clicked.connect(self.reject)
            btn_row.addWidget(btn)
            self.action_buttons.append(btn)
        outer.addLayout(btn_row)

    def _toggle_details(self) -> None:
        if self.details_edit is None or self.toggle_details_btn is None:
            return
        from qt_ui.icons import icon
        from qt_ui.motion import DURATION_NORMAL, Motion, animate_height

        visible = not self.details_edit.isVisible()
        if not Motion.enabled():
            self.details_edit.setMaximumHeight(120 if visible else 0)
            self.details_edit.setVisible(visible)
            self.toggle_details_btn.setText(t("Hide details") if visible else t("Show details"))
            self.toggle_details_btn.setIcon(icon("chevron-down" if not visible else "x", 14))
            self.adjustSize()
            return

        if visible:
            self.details_edit.setMaximumHeight(0)
            self.details_edit.setVisible(True)
            self.toggle_details_btn.setText(t("Hide details"))
            self.toggle_details_btn.setIcon(icon("x", 14))
            animate_height(
                self.details_edit,
                start_h=0,
                end_h=120,
                duration_ms=DURATION_NORMAL,
                on_finished=self.adjustSize,
            )
        else:
            self.toggle_details_btn.setText(t("Show details"))
            self.toggle_details_btn.setIcon(icon("chevron-down", 14))

            def _after_collapse() -> None:
                self.details_edit.setVisible(False)
                self.adjustSize()

            animate_height(
                self.details_edit,
                start_h=self.details_edit.height(),
                end_h=0,
                duration_ms=DURATION_NORMAL,
                on_finished=_after_collapse,
            )

    def _copy_details(self) -> None:
        if self.copy_details_btn is None:
            return
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(self._details_text or "")
            self.copy_details_btn.setText(t("Copied!"))
            self.copy_details_btn.setIcon(icon("check", 14))
            btn = self.copy_details_btn
            def _reset() -> None:
                try:
                    btn.setText(t("Copy details"))
                    btn.setIcon(icon("copy", 14))
                except (RuntimeError, ReferenceError):
                    pass
            QTimer.singleShot(1500, _reset)


def info(parent: QWidget | None, title: str, text: str) -> None:
    ThemedDialog(parent, title, text, icon_name="info", icon_colour=ACCENT, buttons=(("OK", "accent", True),)).exec()


def warning(parent: QWidget | None, title: str, text: str) -> None:
    ThemedDialog(parent, title, text, icon_name="alert", icon_colour="#f59e0b", buttons=(("OK", "accent", True),)).exec()


def error(parent: QWidget | None, title: str, text: str, details: str | None = None) -> None:
    ThemedDialog(parent, title, text, icon_name="alert", icon_colour=ERR, details=details, buttons=(("OK", "destructive", True),)).exec()


def ask_yes_no(parent: QWidget | None, title: str, text: str, destructive: bool = False) -> bool:
    """«Yes» / «No» question (tkinter ``askyesno``). Escape and closing the box answer No."""
    dlg = ThemedDialog(
        parent, title, text,
        icon_name="alert" if destructive else "info",
        icon_colour=ERR if destructive else ACCENT,
        buttons=(("No", "ghost", False), ("Yes", "destructive" if destructive else "accent", True)),
    )
    return dlg.exec() == QDialog.DialogCode.Accepted


def ask_ok_cancel(parent: QWidget | None, title: str, text: str, destructive: bool = False) -> bool:
    """«OK» / «Cancel» question (tkinter ``askokcancel``)."""
    dlg = ThemedDialog(
        parent, title, text,
        icon_name="alert" if destructive else "info",
        icon_colour=ERR if destructive else ACCENT,
        buttons=(("Cancel", "ghost", False), ("OK", "destructive" if destructive else "accent", True)),
    )
    return dlg.exec() == QDialog.DialogCode.Accepted


def choose_folder(parent: QWidget | None, title: str, start: str = "") -> str:
    """The system's folder picker (tkinter ``askdirectory``). ``""`` when the person cancels."""
    return QFileDialog.getExistingDirectory(parent, title, start)


def open_file(parent: QWidget | None, title: str, start: str = "", name_filter: str = "All files (*.*)") -> str:
    """The system's file picker (tkinter ``askopenfilename``). ``""`` when the person cancels."""
    path, _chosen = QFileDialog.getOpenFileName(parent, title, start, name_filter)
    return path


def save_file(parent: QWidget | None, title: str, start: str = "", name_filter: str = "Text files (*.txt);;All files (*.*)") -> str:
    """The system's save-file picker (Phase 9c, F3 «Save log…»). ``""`` when the person cancels."""
    path, _chosen = QFileDialog.getSaveFileName(parent, title, start, name_filter)
    return path


class HistoryDialog(QDialog):
    """Download history dialog showing recorded downloads with options to open folder or load VOD."""

    vod_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("historyDialog")
        self.setWindowTitle(t("Download History"))
        self.setModal(True)
        self.resize(760, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Header row
        header = QHBoxLayout()
        title_lbl = QLabel(t("Download History"), self)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title_lbl)

        header.addStretch(1)

        self.clear_btn = QPushButton(t("Clear history"), self)
        self.clear_btn.setProperty("variant", "ghost")
        self.clear_btn.clicked.connect(self._on_clear)
        header.addWidget(self.clear_btn)

        outer.addLayout(header)

        # Table
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([t("Site"), t("Downloaded"), t("Streamer"), t("Title"), t("Parts"), t("Quality"), t("Actions")])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        outer.addWidget(self.table, 1)
        from qt_ui.widgets import EmptyState
        self.empty_state = EmptyState(self.table, top=28)

        # Footer
        footer = QHBoxLayout()
        self.count_label = QLabel("", self)
        self.count_label.setProperty("role", "muted")
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        close_btn = QPushButton(t("Close"), self)
        close_btn.setProperty("variant", "accent")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        self.refresh()

    def refresh(self) -> None:
        from core import history
        from PySide6.QtWidgets import QTableWidgetItem, QWidget, QHBoxLayout, QPushButton
        from core.files import open_in_file_manager

        entries = history.load_history()
        self.table.setRowCount(len(entries))
        self.count_label.setText(tn("{n} completed download", "{n} completed downloads", len(entries)))
        if not entries:
            self.empty_state.show_message(t("No downloads yet"), t("Finished downloads will appear here with date, parts and folder location."))
        else:
            self.empty_state.hide_message()

        for row, e in enumerate(entries):
            site_val = (getattr(e, "site", "twitch") or "twitch").capitalize()
            self.table.setItem(row, 0, QTableWidgetItem(site_val))
            self.table.setItem(row, 1, QTableWidgetItem(e.downloaded_at))
            self.table.setItem(row, 2, QTableWidgetItem(e.streamer))
            self.table.setItem(row, 3, QTableWidgetItem(e.title))
            self.table.setItem(row, 4, QTableWidgetItem(str(e.parts)))
            self.table.setItem(row, 5, QTableWidgetItem(e.quality))

            actions_widget = QWidget(self.table)
            act_lay = QHBoxLayout(actions_widget)
            act_lay.setContentsMargins(4, 2, 4, 2)
            act_lay.setSpacing(6)

            if e.folder:
                f_btn = QPushButton(t("Folder"), actions_widget)
                f_btn.setProperty("variant", "ghost")
                f_btn.clicked.connect(lambda _, p=e.folder: open_in_file_manager(p))
                act_lay.addWidget(f_btn)

            if e.vod_id or getattr(e, "url", ""):
                load_btn = QPushButton(t("Load"), actions_widget)
                load_btn.setProperty("variant", "ghost")
                load_btn.clicked.connect(lambda _, item=e: self._load_entry(item))
                act_lay.addWidget(load_btn)

            self.table.setCellWidget(row, 6, actions_widget)

    def _load_entry(self, entry) -> None:
        url = getattr(entry, "url", "")
        if not url:
            vid = getattr(entry, "vod_id", "")
            if getattr(entry, "site", "twitch") == "twitch" or vid.isdigit():
                url = f"https://www.twitch.tv/videos/{vid}"
            else:
                url = vid
        self.vod_requested.emit(url)
        self.accept()

    def _load_vod(self, vod_id: str) -> None:
        url = f"https://www.twitch.tv/videos/{vod_id}"
        self.vod_requested.emit(url)
        self.accept()

    def _on_clear(self) -> None:
        if not ask_yes_no(self, t("Clear history"), t("Clear download history? This cannot be undone."), destructive=True):
            return
        from core import history
        history.clear_history()
        self.refresh()


class AboutDialog(QDialog):
    """About LuckyDownloader dialog with app version, system diagnostics export, and credits."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle(t("About LuckyDownloader"))
        self.setModal(True)
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 18)
        outer.setSpacing(14)

        # Header with icon and title
        header = QHBoxLayout()
        header.setSpacing(14)

        icon_lbl = QLabel(self)
        from core.resources import resource_path
        icon_path = resource_path("assets/icon.png")
        if icon_path.is_file():
            from PySide6.QtGui import QPixmap
            icon_lbl.setPixmap(QPixmap(str(icon_path)).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            icon_lbl.setPixmap(pixmap("film", 48, ACCENT))
        header.addWidget(icon_lbl)

        title_lay = QVBoxLayout()
        title_lay.setSpacing(2)
        app_name = QLabel(t("LuckyDownloader"), self)
        app_name.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")
        title_lay.addWidget(app_name)

        from core.paths import BUNDLED_VERSION, read_bundled_version
        ver = BUNDLED_VERSION or read_bundled_version() or "dev"
        ver_lbl = QLabel(t("Version {ver}", ver=ver), self)
        ver_lbl.setProperty("role", "muted")
        title_lay.addWidget(ver_lbl)

        header.addLayout(title_lay)
        header.addStretch(1)
        outer.addLayout(header)

        # Description
        desc = QLabel(
            t("Modern Twitch VOD & clip downloader, cutter, chat archiver, and Premiere Pro exporter."),
            self,
        )
        desc.setWordWrap(True)
        outer.addWidget(desc)

        # System info summary
        import platform
        import sys
        sys_info_lbl = QLabel(
            t("Python {py} · {os} {release}", py=sys.version.split()[0], os=platform.system(), release=platform.release()),
            self,
        )
        sys_info_lbl.setProperty("role", "muted")
        sys_info_lbl.setStyleSheet("font-size: 11px;")
        outer.addWidget(sys_info_lbl)

        # Actions row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.export_btn = QPushButton(t("Export Diagnostics…"), self)
        self.export_btn.setProperty("variant", "ghost")
        self.export_btn.setIcon(icon("file-text", 14))
        self.export_btn.clicked.connect(self._on_export_diagnostics)
        btn_row.addWidget(self.export_btn)

        btn_row.addStretch(1)

        self.close_btn = QPushButton(t("Close"), self)
        self.close_btn.setProperty("variant", "accent")
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)

        outer.addLayout(btn_row)

    def _on_export_diagnostics(self) -> None:
        from pathlib import Path
        from core.diagnostics import export_diagnostics_zip
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Export Diagnostics Bundle"),
            "luckydownloader_diagnostics.zip",
            "Zip archives (*.zip);;All files (*.*)",
        )
        if not path:
            return
        try:
            export_diagnostics_zip(Path(path))
            info(self, t("Diagnostics Exported"), t("Diagnostics bundle successfully saved to:\n{path}", path=path))
        except Exception as e:
            error(self, t("Export Failed"), t("Could not export diagnostics bundle: {error}", error=e))

