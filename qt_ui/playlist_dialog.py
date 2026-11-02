"""
Playlist picker dialog (Phase 6): preview and pick items from a playlist or channel URL,
configure shared download options, and enqueue them as individual jobs.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import paths
from core.i18n import t
from core.options import QUALITY_CHOICES, build_options
from core.palette import ACCENT, BG, BORDER, FG, MUTED
from core.playlist import expand_playlist_jobs, parse_item_range
from core.settings import DEFAULTS
from core.source_info import PlaylistInfo, PlaylistItem
from luckytwitch_engine import Job, JobOptions, fmt_hms
from qt_ui import dialogs
from qt_ui.icons import icon
from qt_ui.widgets import Card, ComboBox, Toggle

THUMB_W = 64
THUMB_H = 36
CONFIRM_THRESHOLD = 50


class DialogThumbLoader(QObject):
    """Background loader for playlist dialog entry thumbnails."""

    loaded = Signal(int, str)  # (row, path)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.jobs: queue.Queue = queue.Queue()
        self.threads: list[threading.Thread] = []
        self._stopped = False
        self._lock = threading.Lock()

    def submit(self, row: int, url: str) -> None:
        if not url:
            return
        with self._lock:
            if self._stopped:
                return
            if not self.threads:
                for _ in range(4):
                    t = threading.Thread(target=self._work, daemon=True)
                    t.start()
                    self.threads.append(t)
        self.jobs.put((row, url))

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            n = len(self.threads)
        for _ in range(n):
            self.jobs.put(None)

    def _work(self) -> None:
        from luckytwitch_engine import fetch_thumbnail
        while True:
            item = self.jobs.get()
            if item is None:
                return
            row, url = item
            with self._lock:
                if self._stopped:
                    return
            try:
                path = fetch_thumbnail(url)
                if path and Path(path).is_file():
                    self.loaded.emit(row, str(path))
            except Exception:
                continue


class PlaylistPickerDialog(QDialog):
    """Dialog allowing user to select items from a playlist/channel and configure shared download options."""

    def __init__(
        self,
        playlist: PlaylistInfo,
        settings: dict | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.playlist = playlist
        self.settings = settings or {}
        self.setWindowTitle(t("Playlist items — {title}", title=playlist.title))
        self.resize(840, 620)
        self.setMinimumSize(700, 480)
        self.setModal(True)

        self._items = playlist.entries
        self._checkboxes: list[QCheckBox] = []
        self._thumb_labels: dict[int, QLabel] = {}
        self._thumb_loader = DialogThumbLoader(self)
        self._thumb_loader.loaded.connect(self._on_thumb_loaded)

        self._build_ui()
        self._populate_table()
        self._update_selection_summary()

    def _build_ui(self) -> None:
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(16, 16, 16, 16)
        root_lay.setSpacing(12)

        # Header card: Title, uploader, item count
        header = QFrame(self)
        h_lay = QVBoxLayout(header)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(4)

        t_lbl = QLabel(self.playlist.title, header)
        f_title = QFont(t_lbl.font())
        f_title.setPointSize(f_title.pointSize() + 2)
        f_title.setBold(True)
        t_lbl.setFont(f_title)
        t_lbl.setWordWrap(True)
        h_lay.addWidget(t_lbl)

        meta_parts = []
        if self.playlist.uploader:
            meta_parts.append(self.playlist.uploader)
        meta_parts.append(t("{count} items", count=len(self._items)))
        site_str = getattr(self.playlist, "site", "generic") or "generic"
        meta_parts.append(site_str.capitalize())

        sub_lbl = QLabel("  ·  ".join(meta_parts), header)
        sub_lbl.setProperty("role", "muted")
        h_lay.addWidget(sub_lbl)
        root_lay.addWidget(header)

        # Selection bar: Select all, none, range box
        sel_bar = QFrame(self)
        sb_lay = QHBoxLayout(sel_bar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(8)

        self.btn_all = QPushButton(t("Select all"), sel_bar)
        self.btn_all.setProperty("variant", "ghost")
        self.btn_all.clicked.connect(self.select_all)
        sb_lay.addWidget(self.btn_all)

        self.btn_none = QPushButton(t("Select none"), sel_bar)
        self.btn_none.setProperty("variant", "ghost")
        self.btn_none.clicked.connect(self.select_none)
        sb_lay.addWidget(self.btn_none)

        sb_lay.addSpacing(8)
        range_lbl = QLabel(t("Range:"), sel_bar)
        range_lbl.setProperty("role", "muted")
        sb_lay.addWidget(range_lbl)

        self.range_entry = QLineEdit(sel_bar)
        self.range_entry.setPlaceholderText(t("e.g. 1-10, 15, 20-25"))
        self.range_entry.returnPressed.connect(self.apply_range)
        self.range_entry.setFixedWidth(160)
        sb_lay.addWidget(self.range_entry)

        self.btn_apply_range = QPushButton(t("Apply"), sel_bar)
        self.btn_apply_range.setProperty("variant", "ghost")
        self.btn_apply_range.clicked.connect(self.apply_range)
        sb_lay.addWidget(self.btn_apply_range)

        sb_lay.addStretch(1)

        self.sel_count_lbl = QLabel("", sel_bar)
        self.sel_count_lbl.setProperty("role", "muted")
        sb_lay.addWidget(self.sel_count_lbl)
        root_lay.addWidget(sel_bar)

        # Items Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "",
            t("#"),
            t("Thumbnail"),
            t("Title"),
            t("Duration"),
            t("Uploader"),
        ])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(1, 44)
        self.table.setColumnWidth(2, 78)
        self.table.setColumnWidth(4, 76)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root_lay.addWidget(self.table, 1)

        # Options Card (Quality, format, audio-only, output directory, skip existing)
        opt_card = Card(t("Download options"))
        opt_container = QWidget(opt_card)
        opt_lay = QGridLayout(opt_container)
        opt_lay.setContentsMargins(6, 6, 6, 6)
        opt_lay.setHorizontalSpacing(10)
        opt_lay.setVerticalSpacing(8)

        # Quality
        q_lbl = QLabel(t("Quality:"), opt_card)
        q_lbl.setProperty("role", "muted")
        opt_lay.addWidget(q_lbl, 0, 0)

        self.quality_combo = ComboBox(opt_card)
        for name, key in QUALITY_CHOICES.items():
            self.quality_combo.addItem(name, key)
        def_qual = self.settings.get("default_quality", DEFAULTS["default_quality"])
        idx = self.quality_combo.findData(QUALITY_CHOICES.get(def_qual, def_qual))
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        opt_lay.addWidget(self.quality_combo, 0, 1)

        # Format / Container
        c_lbl = QLabel(t("Format:"), opt_card)
        c_lbl.setProperty("role", "muted")
        opt_lay.addWidget(c_lbl, 0, 2)

        self.container_combo = ComboBox(opt_card)
        for c in ("mp4", "mkv", "mp3", "m4a"):
            self.container_combo.addItem(c, c)
        opt_lay.addWidget(self.container_combo, 0, 3)

        # Audio only toggle
        self.audio_toggle = Toggle(False, opt_card)
        self.audio_toggle.clicked.connect(self._on_audio_toggled)
        ab_widget = QWidget(opt_card)
        ab_lay = QHBoxLayout(ab_widget)
        ab_lay.setContentsMargins(0, 0, 0, 0)
        ab_lay.setSpacing(6)
        ab_lay.addWidget(QLabel(t("Audio only"), ab_widget))
        ab_lay.addWidget(self.audio_toggle)
        opt_lay.addWidget(ab_widget, 0, 4)

        # Folder row
        f_lbl = QLabel(t("Folder:"), opt_card)
        f_lbl.setProperty("role", "muted")
        opt_lay.addWidget(f_lbl, 1, 0)

        self.folder_entry = QLineEdit(opt_card)
        def_dir = str(self.settings.get("out_dir", getattr(paths, "DOWNLOADS_DIR", "")))
        self.folder_entry.setText(def_dir)
        opt_lay.addWidget(self.folder_entry, 1, 1, 1, 3)

        self.btn_browse = QPushButton(t("Browse…"), opt_card)
        self.btn_browse.setProperty("variant", "ghost")
        self.btn_browse.clicked.connect(self._browse_folder)
        opt_lay.addWidget(self.btn_browse, 1, 4)

        # Skip existing / download archive checkbox
        self.skip_existing_check = QCheckBox(t("Skip already downloaded videos"), opt_card)
        self.skip_existing_check.setChecked(True)
        opt_lay.addWidget(self.skip_existing_check, 2, 1, 1, 4)

        opt_card.add_widget(opt_container)
        root_lay.addWidget(opt_card)

        # Bottom action bar: Cancel and Add to Queue
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 0, 0, 0)
        btn_bar.setSpacing(10)
        btn_bar.addStretch(1)

        self.btn_cancel = QPushButton(t("Cancel"), self)
        self.btn_cancel.setProperty("variant", "ghost")
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_queue = QPushButton(t("Add to Queue"), self)
        self.btn_queue.setProperty("variant", "primary")
        self.btn_queue.clicked.connect(self._on_accept)
        btn_bar.addWidget(self.btn_queue)

        root_lay.addLayout(btn_bar)

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self._items))
        self._checkboxes = []
        self._thumb_labels.clear()

        for row, item in enumerate(self._items):
            # Column 0: Checkbox widget
            cb_container = QWidget()
            cb_lay = QHBoxLayout(cb_container)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox(cb_container)
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_selection_summary)
            cb_lay.addWidget(cb)
            self._checkboxes.append(cb)
            self.table.setCellWidget(row, 0, cb_container)

            # Column 1: Index
            idx_item = QTableWidgetItem(str(item.index or (row + 1)))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, idx_item)

            # Column 2: Thumbnail widget
            thumb_container = QWidget()
            t_lay = QHBoxLayout(thumb_container)
            t_lay.setContentsMargins(4, 3, 4, 3)
            t_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(thumb_container)
            lbl.setFixedSize(THUMB_W, THUMB_H)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"background: {BG}; border-radius: 3px; border: 1px solid {BORDER};")
            t_lay.addWidget(lbl)
            self.table.setCellWidget(row, 2, thumb_container)
            self._thumb_labels[row] = lbl

            if item.thumbnail:
                if Path(item.thumbnail).is_file():
                    self._set_label_pixmap(lbl, item.thumbnail)
                else:
                    self._thumb_loader.submit(row, item.thumbnail)

            # Column 3: Title
            title_item = QTableWidgetItem(item.title)
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, title_item)

            # Column 4: Duration
            dur_str = fmt_hms(item.duration) if item.duration > 0 else "--:--"
            dur_item = QTableWidgetItem(dur_str)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 4, dur_item)

            # Column 5: Uploader
            upl_item = QTableWidgetItem(item.uploader or self.playlist.uploader)
            upl_item.setFlags(upl_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 5, upl_item)

    def _set_label_pixmap(self, lbl: QLabel, path: str) -> None:
        pm = QPixmap(path)
        if not pm.isNull():
            scaled = pm.scaled(
                THUMB_W, THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl.setPixmap(scaled)

    def _on_thumb_loaded(self, row: int, path: str) -> None:
        lbl = self._thumb_labels.get(row)
        if lbl is not None:
            self._set_label_pixmap(lbl, path)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._thumb_loader.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        self._thumb_loader.stop()
        super().reject()

    def accept(self) -> None:
        self._thumb_loader.stop()
        super().accept()

    def _update_selection_summary(self) -> None:
        selected_count = sum(1 for cb in self._checkboxes if cb.isChecked())
        total = len(self._items)
        self.sel_count_lbl.setText(t("Selected: {count} of {total}", count=selected_count, total=total))
        self.btn_queue.setText(t("Add to Queue ({count})", count=selected_count))
        self.btn_queue.setEnabled(selected_count > 0)

    def select_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(True)
        self._update_selection_summary()

    def select_none(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(False)
        self._update_selection_summary()

    def apply_range(self) -> None:
        txt = self.range_entry.text().strip()
        if not txt:
            return
        indices = parse_item_range(txt, len(self._items))
        for row, cb in enumerate(self._checkboxes, start=1):
            cb.setChecked(row in indices)
        self._update_selection_summary()

    def _on_audio_toggled(self) -> None:
        is_audio = self.audio_toggle.isChecked()
        cnt = self.container_combo.currentText().lower()
        if is_audio and cnt in ("mp4", "mkv"):
            self.container_combo.setCurrentText("mp3")
        elif not is_audio and cnt in ("mp3", "m4a"):
            self.container_combo.setCurrentText("mp4")

    def _browse_folder(self) -> None:
        init = self.folder_entry.text().strip() or str(getattr(paths, "DOWNLOADS_DIR", ""))
        d = QFileDialog.getExistingDirectory(self, t("Select download folder"), init)
        if d:
            self.folder_entry.setText(d)

    def _on_accept(self) -> None:
        selected = self.selected_items()
        if not selected:
            return

        if len(selected) >= CONFIRM_THRESHOLD:
            msg = t(
                "You have selected {count} videos to download.\nAre you sure you want to add all of them to the queue?",
                count=len(selected),
            )
            if not dialogs.ask_yes_no(self, t("Large playlist"), msg):
                return

        self.accept()

    def selected_items(self) -> list[PlaylistItem]:
        return [item for item, cb in zip(self._items, self._checkboxes) if cb.isChecked()]

    def current_quality(self) -> str:
        if self.audio_toggle.isChecked():
            return "audio"
        return str(self.quality_combo.currentData() or "best")

    def current_container(self) -> str:
        return self.container_combo.currentText().lower()

    def current_output_dir(self) -> str:
        return self.folder_entry.text().strip()

    def skip_existing(self) -> bool:
        return self.skip_existing_check.isChecked()

    def build_jobs(self) -> list[Job]:
        selected = self.selected_items()
        if not selected:
            return []

        opts = build_options(self.settings, cut_text="", quality=self.current_quality())
        from dataclasses import replace
        opts = replace(
            opts,
            quality=self.current_quality(),
            container=self.current_container(),
            out_dir=self.current_output_dir() or opts.out_dir,
            audio_format="mp3" if self.current_container() == "mp3" else "m4a",
        )

        return expand_playlist_jobs(
            self.playlist,
            selected,
            opts,
            skip_existing=self.skip_existing(),
        )
