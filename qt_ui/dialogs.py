"""Message boxes and system pickers, in one place, so the tabs call ``dialogs.info(...)`` and the tests replace
these functions.

Phase 9h (H1, H2): Themed custom dialogs with dark surfaces, vector icons, expandable error details fold,
and one-click 'Copy details' button.
"""

from __future__ import annotations

from pathlib import Path
import unicodedata

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
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
        self.export_btn.clicked.connect(self.export_diagnostics_bundle)
        btn_row.addWidget(self.export_btn)

        btn_row.addStretch(1)

        self.close_btn = QPushButton(t("Close"), self)
        self.close_btn.setProperty("variant", "accent")
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)

        outer.addLayout(btn_row)

    def export_diagnostics_bundle(self, target_path: str | Path | None = None) -> bool:
        return export_diagnostics_bundle(self, target_path=target_path)

    def _on_export_diagnostics(self) -> None:
        self.export_diagnostics_bundle()


def export_diagnostics_bundle(parent: QWidget | None = None, target_path: str | Path | None = None) -> bool:
    """Prompt (unless ``target_path`` is supplied) and export a redacted diagnostics zip bundle."""
    from core.diagnostics import export_diagnostics_zip

    if target_path:
        path = str(target_path)
    else:
        path, _ = QFileDialog.getSaveFileName(
            parent,
            t("Export Diagnostics Bundle"),
            "luckydownloader_diagnostics.zip",
            "Zip archives (*.zip);;All files (*.*)",
        )
    if not path:
        return False
    try:
        export_diagnostics_zip(Path(path))
        info(parent, t("Diagnostics Exported"), t("Diagnostics bundle successfully saved to:\n{path}", path=path))
        return True
    except Exception as e:
        error(parent, t("Export Failed"), t("Could not export diagnostics bundle: {error}", error=e))
        return False


def _fold_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").casefold()) if unicodedata.category(c) != "Mn")


def fuzzy_score(query: str, text: str) -> int | None:
    """Return a positive fuzzy match score (higher is better), or None when ``query`` does not match ``text``."""
    q_fold = _fold_text(query).strip()
    if not q_fold:
        return 0
    t_fold = _fold_text(text)
    if not t_fold:
        return None
    total = 0
    for tok in q_fold.split():
        idx = t_fold.find(tok)
        if idx >= 0:
            bonus = 100 if (idx == 0 or not t_fold[idx - 1].isalnum()) else 0
            total += 200 + bonus - min(idx, 100)
            continue
        pos = -1
        span = 0
        first = -1
        matched = True
        for ch in tok:
            nxt = t_fold.find(ch, pos + 1)
            if nxt < 0:
                matched = False
                break
            if first < 0:
                first = nxt
            pos = nxt
        if not matched:
            return None
        span = pos - first + 1
        total += max(5, 60 - max(0, span - len(tok)) * 2)
    return total


class CommandPaletteDialog(QDialog):
    """Global Ctrl+K Command Palette for quick commands, Options settings, watchlist, and recent streamers."""

    def __init__(
        self,
        host: QWidget | None = None,
        items: list[dict] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent or host)
        self.host = host
        self.setObjectName("commandPaletteDialog")
        self.setWindowTitle(t("Command Palette"))
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(560, 420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(10)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("commandPaletteSearch")
        self.search_input.setPlaceholderText(t("Type a command, setting, or channel…"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.installEventFilter(self)
        self.search_input.textChanged.connect(self.filter_items)
        outer.addWidget(self.search_input)

        # Compatibility aliases
        self.search_edit = self.search_input
        self.input = self.search_input

        self.results_list = QListWidget(self)
        self.results_list.setObjectName("commandPaletteList")
        self.results_list.itemActivated.connect(self._on_item_activated)
        self.results_list.itemClicked.connect(self._on_item_activated)
        outer.addWidget(self.results_list, 1)
        self.list_widget = self.results_list

        self.hint_label = QLabel(t("Enter to run · ↑/↓ to navigate · Esc to close"), self)
        self.hint_label.setProperty("role", "muted")
        outer.addWidget(self.hint_label)

        self._all_items: list[dict] = list(items) if items is not None else self.build_entries_from_host(host)
        self.filtered_items: list[dict] = []
        self.filter_items("")

    @staticmethod
    def build_entries_from_host(host: QWidget | None) -> list[dict]:
        entries: list[dict] = []

        def add_entry(
            entry_id: str,
            title: str,
            subtitle: str,
            category: str,
            action,
            extra_search: str = "",
        ) -> None:
            search_text = " ".join(x for x in (title, subtitle, category, extra_search) if x)
            entries.append({
                "id": entry_id,
                "title": title,
                "subtitle": subtitle,
                "category": category,
                "search_text": search_text,
                "action": action,
            })

        cat_cmd = t("Command")
        if host is not None:
            def _do_get_info() -> None:
                entry = getattr(host, "vod_entry", None)
                if entry is not None and entry.text().strip() and hasattr(host, "on_get_info"):
                    host.on_get_info()
                elif hasattr(host, "focus_vod_bar"):
                    host.focus_vod_bar()

            add_entry("cmd:get_info", t("Get Info"), t("Fetch VOD or video metadata"), cat_cmd, _do_get_info, "get info fetch vod url")
            if hasattr(host, "tab_queue"):
                add_entry("cmd:start_queue", t("Start Queue"), t("Start queued downloads"), cat_cmd, host.tab_queue.start_queue, "start queue downloads")
                add_entry("cmd:open_folder", t("Open Output Folder"), t("Open the download destination folder"), cat_cmd, host.tab_queue.open_output_folder, "open output folder")
            if hasattr(host, "export_diagnostics_bundle"):
                add_entry("cmd:export_diagnostics", t("Export Diagnostics Bundle"), t("Save redacted system logs and diagnostics"), cat_cmd, host.export_diagnostics_bundle, "export diagnostics bundle zip")
            if hasattr(host, "start_update_check"):
                add_entry("cmd:check_updates", t("Check for Updates"), t("Check GitHub releases for new versions"), cat_cmd, lambda: host.start_update_check(force=True), "check updates version")
            if hasattr(host, "toggle_language"):
                add_entry("cmd:switch_language", t("Switch Language"), t("Toggle interface language (English / Español)"), cat_cmd, host.toggle_language, "switch language idioma")
            if hasattr(host, "open_about_dialog"):
                add_entry("cmd:about", t("About & Diagnostics…"), t("Show version info and diagnostics export"), cat_cmd, host.open_about_dialog, "about diagnostics")
            if hasattr(host, "show_shortcuts"):
                add_entry("cmd:shortcuts", t("Keyboard shortcuts"), t("Show keyboard shortcuts reference"), cat_cmd, host.show_shortcuts, "shortcuts f1")

        # Options settings
        tab_options = getattr(host, "tab_options", None)
        if tab_options is not None and hasattr(tab_options, "searchable_rows"):
            cat_opt = t("Options")
            for item in tab_options.searchable_rows:
                key = str(item.get("key") or "")
                if not key or key == "_about_diag":
                    continue
                row = item.get("row")
                title = (
                    row.title_label.text()
                    if row is not None and getattr(row, "title_label", None) is not None
                    else str(item.get("raw_title") or key)
                )
                hint = (
                    row.hint_label.text()
                    if row is not None and getattr(row, "hint_label", None) is not None
                    else str(item.get("raw_hint") or "")
                )
                extra = f"{key} {item.get('en_text', '')} {item.get('section_key', '')}"
                add_entry(
                    f"opt:{key}",
                    title,
                    hint or str(item.get("section_key") or ""),
                    cat_opt,
                    (lambda k=key: host.jump_to_option(k)) if hasattr(host, "jump_to_option") else (lambda k=key: tab_options.jump_to_setting(k)),
                    extra,
                )

        # Watchlist channels
        seen_twitch: set[str] = set()
        if host is not None and hasattr(host, "open_channel_from_palette"):
            try:
                from core.watchlist import load_watchlist
                cat_watch = t("Watch list")
                for w in load_watchlist():
                    login = str(getattr(w, "login", "") or "").strip()
                    name = str(getattr(w, "name", "") or login).strip()
                    prov = str(getattr(w, "provider", "twitch") or "twitch").strip()
                    url = str(getattr(w, "url", "") or "").strip()
                    if prov == "twitch" and login:
                        seen_twitch.add(login.lower())
                    add_entry(
                        f"watch:{prov}:{login or url}",
                        name or login or url,
                        f"{prov.capitalize()} · {cat_watch}",
                        cat_watch,
                        lambda l=login, n=name, p=prov, u=url: host.open_channel_from_palette(login=l, name=n, provider=p, url=u),
                        f"{login} {prov} {url}",
                    )
            except Exception:
                pass

            # Recent Twitch streamers and YouTube searches
            cat_recent = t("Recent")
            tab_browse = getattr(host, "tab_browse", None)
            recent_twitch = list(getattr(tab_browse, "recent", None) or [])
            if not recent_twitch:
                try:
                    from core.recent import load_recent
                    recent_twitch = load_recent()
                except Exception:
                    recent_twitch = []
            for ch in recent_twitch:
                login = str(ch.get("login") or "").strip()
                name = str(ch.get("name") or login).strip()
                if not (login or name):
                    continue
                if login and login.lower() in seen_twitch:
                    continue
                add_entry(
                    f"recent:twitch:{login or name}",
                    name,
                    t("Recent streamer"),
                    cat_recent,
                    lambda l=login, n=name: host.open_channel_from_palette(login=l, name=n, provider="twitch"),
                    f"{login} twitch streamer",
                )

            recent_yt = list(getattr(tab_browse, "recent_yt", None) or [])
            if not recent_yt:
                try:
                    from core.recent import load_recent_searches
                    recent_yt = load_recent_searches()
                except Exception:
                    recent_yt = []
            for ch in recent_yt:
                qname = str(ch.get("name") or ch.get("login") or "").strip()
                if not qname:
                    continue
                add_entry(
                    f"recent:youtube:{qname}",
                    qname,
                    t("Recent YouTube search"),
                    cat_recent,
                    lambda q=qname: host.open_channel_from_palette(login=q, name=q, provider="youtube"),
                    f"{qname} youtube",
                )

        return entries

    def filter_items(self, query: str) -> list[dict]:
        scored: list[tuple[int, int, dict]] = []
        for idx, entry in enumerate(self._all_items):
            sc = fuzzy_score(query, entry.get("search_text", entry.get("title", "")))
            if sc is not None:
                scored.append((sc, idx, entry))
        if (query or "").strip():
            scored.sort(key=lambda pair: (-pair[0], pair[1]))
        self.filtered_items = [pair[2] for pair in scored]

        self.results_list.clear()
        for entry in self.filtered_items:
            cat = entry.get("category", "")
            title = entry.get("title", "")
            sub = entry.get("subtitle", "")
            label = f"[{cat}] {title}" if cat else title
            if sub:
                label = f"{label}  —  {sub}"
            lw_item = QListWidgetItem(label)
            lw_item.setData(Qt.ItemDataRole.UserRole, entry)
            self.results_list.addItem(lw_item)
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)
        return list(self.filtered_items)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self.trigger_item(item)

    def trigger_item(self, item: QListWidgetItem | int | None = None) -> bool:
        if isinstance(item, int):
            item = self.results_list.item(item)
        if item is None:
            item = self.results_list.currentItem()
            if item is None and self.results_list.count() > 0:
                item = self.results_list.item(0)
        if item is None:
            return False
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return False
        action = entry.get("action")
        self.accept()
        if callable(action):
            action()
        return True

    def execute_selected(self) -> bool:
        return self.trigger_item(self.results_list.currentItem())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                count = self.results_list.count()
                if count > 0:
                    cur = self.results_list.currentRow()
                    step = 1 if key == Qt.Key.Key_Down else -1
                    nxt = (cur + step) % count if cur >= 0 else 0
                    self.results_list.setCurrentRow(nxt)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.execute_selected():
                    return True
        return super().eventFilter(watched, event)


CommandPalette = CommandPaletteDialog

