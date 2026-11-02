"""The Queue & log tab (Phase 3, redesigned in Phase 9c):
- F1. Rich rows via ``QueueRowDelegate`` (16:9 thumbnail, bold title + «n parts · strategy», coloured status chip,
  in-row progress bar for the running job, and inline «Open» button on finished rows).
- F2. Header summary banner («N done · N running · N waiting · N failed»), in-header progress bar, and grouped
  primary (Start / Cancel) vs secondary (Retry / Move up / Move down / Remove / Clear finished) actions.
- F3. Collapsible Log drawer (collapsed by default to a 1-line colour-coded preview of the latest message; opens
  automatically on the first error) with severity filter chips (All / Warnings / Errors), search box,
  «Pause autoscroll» toggle, Copy, Clear, and «Save log…» export.
- F4. Retry failed/cancelled jobs and thread-safe reordering of waiting jobs.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QObject, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget,
)

from core.files import open_in_file_manager
from core.palette import ACCENT, ACCENT_DIM, ACCENT_TEXT, BG, BG3, BORDER, BORDER_STRONG, ERR, FG, MUTED, OK, WARN, WHITE
from core.settings import DEFAULTS
from core.i18n import N_, t, tn
from qt_ui.i18n_qt import language_bus
from core.status import STATUS_COLOURS, log_kind, status_label
from luckytwitch_engine import stream_dir
from qt_ui import dialogs, notify
from qt_ui.bridge import Bridge
from qt_ui.icons import icon
from qt_ui.queue_model import COLUMNS, IID_ROLE, ITEM_ROLE, STATUS_ROLE, QueueItem, QueueModel
from qt_ui.queue_runner import QueueRunner
from qt_ui.theme import mono_font
from qt_ui.widgets import Card, Collapsible, EmptyState, ScrollFrame

HEADER_HEIGHT = 34  # the column headings; the empty-state message starts under them
ROW_HEIGHT = 44
LOG_COLOURS = {"stamp": MUTED, "muted": MUTED, "err": ERR, "warn": WARN, "ok": OK, "plain": FG}


class QueueThumbFetcher(QObject):
    """Background fetcher for queue item thumbnails."""

    thumb_ready = Signal(str, str)  # (iid, file_path)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.jobs: queue.Queue = queue.Queue()
        self.threads: list[threading.Thread] = []
        self._stopped = False
        self._lock = threading.Lock()

    def submit(self, iid: str, url: str) -> None:
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
        self.jobs.put((iid, url))

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
            iid, url = item
            with self._lock:
                if self._stopped:
                    return
            try:
                path = fetch_thumbnail(url)
                if path and Path(path).is_file():
                    self.thumb_ready.emit(iid, str(path))
            except Exception:
                continue


class QueueRowDelegate(QStyledItemDelegate):
    """Rich row delegate for the Queue table (Phase 9c, F1):
    - Column 1 (Video): 16:9 thumbnail + bold title + muted «n parts · strategy» subtitle.
    - Column 4 (Status): rounded status chip + in-row progress bar when running + «Open» pill when finished with files.
    """

    THUMB_W = 44
    THUMB_H = 25

    def __init__(self, table: QTableView, queue_tab: "QueueTab"):
        super().__init__(table)
        self.table = table
        self.queue_tab = queue_tab
        self._shimmer_phase = 0.0
        self._shimmer_timer = None

    def _ensure_shimmer(self) -> None:
        from qt_ui.motion import Motion
        if not Motion.enabled():
            if self._shimmer_timer is not None and self._shimmer_timer.isActive():
                self._shimmer_timer.stop()
            return
        if self._shimmer_timer is None:
            from PySide6.QtCore import QTimer
            self._shimmer_timer = QTimer(self.table)
            self._shimmer_timer.setInterval(40)
            def _tick():
                self._shimmer_phase = (self._shimmer_phase + 0.03) % 1.0
                if self.table.isVisible():
                    self.table.viewport().update()
            self._shimmer_timer.timeout.connect(_tick)
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), ROW_HEIGHT))

    @staticmethod
    def open_button_rect(cell_rect: QRect) -> QRect:
        w, h = 46, 20
        x = cell_rect.right() - w - 8
        y = cell_rect.top() + (cell_rect.height() - h) // 2
        return QRect(x, y, w, h)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item: QueueItem | None = index.data(ITEM_ROLE)
        col = index.column()
        if item is None or col not in (1, 4):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, QColor(ACCENT_DIM))
            if col == 0:
                painter.fillRect(QRect(option.rect.left(), option.rect.top(), 3, option.rect.height()), QColor(ACCENT))

        if col == 1:
            self._paint_video_cell(painter, option.rect, item, selected)
        elif col == 4:
            self._paint_status_cell(painter, option.rect, item, selected)

        painter.restore()

    def _paint_video_cell(self, painter: QPainter, rect: QRect, item: QueueItem, selected: bool) -> None:
        tx = rect.left() + 6
        ty = rect.top() + (rect.height() - self.THUMB_H) // 2
        thumb_rect = QRect(tx, ty, self.THUMB_W, self.THUMB_H)

        path = QPainterPath()
        path.addRoundedRect(QRectF(thumb_rect), 4.0, 4.0)
        painter.save()
        painter.setClipPath(path)
        pix = item.thumb if isinstance(item.thumb, QPixmap) and not item.thumb.isNull() else None
        if pix is not None:
            painter.fillRect(thumb_rect, QColor(BG))
            scaled = pix.scaled(
                thumb_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            px = thumb_rect.x() + (thumb_rect.width() - scaled.width()) // 2
            py = thumb_rect.y() + (thumb_rect.height() - scaled.height()) // 2
            painter.drawPixmap(px, py, scaled)
        else:
            painter.fillRect(thumb_rect, QColor(BG))
            painter.setPen(QColor(MUTED))
            f_small = QFont(painter.font())
            f_small.setPointSize(7)
            f_small.setBold(True)
            painter.setFont(f_small)
            src = getattr(getattr(item, "job", None), "source", None)
            site = getattr(src, "site", "twitch") or "twitch"
            txt = "VOD" if site == "twitch" else site.upper()[:4]
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, txt)
        painter.restore()
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRoundedRect(QRectF(thumb_rect).adjusted(0.5, 0.5, -0.5, -0.5), 4.0, 4.0)

        text_x = thumb_rect.right() + 10
        text_w = max(20, rect.right() - text_x - 6)
        top_rect = QRect(text_x, rect.top() + 5, text_w, 18)
        bot_rect = QRect(text_x, rect.top() + 22, text_w, 16)

        f_title = QFont(painter.font())
        f_title.setBold(True)
        painter.setFont(f_title)
        painter.setPen(QColor(WHITE if selected else FG))
        elided_title = painter.fontMetrics().elidedText(item.label, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(top_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        f_sub = QFont(painter.font())
        f_sub.setBold(False)
        f_sub.setPointSize(max(8, f_sub.pointSize() - 1))
        painter.setFont(f_sub)
        painter.setPen(QColor(MUTED))
        sub = f"{item.parts} part{'s' if item.parts != 1 else ''} \u00b7 {item.strategy}"
        elided_sub = painter.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(bot_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)

    def _paint_status_cell(self, painter: QPainter, rect: QRect, item: QueueItem, _selected: bool) -> None:
        colour_hex = STATUS_COLOURS.get(item.status, MUTED)
        base_col = QColor(colour_hex)
        fill_col = QColor(base_col.red(), base_col.green(), base_col.blue(), 38)

        label_text = status_label(item.shown_status)
        if item.status == "running" and item.progress > 0:
            label_text = f"{label_text} {round(item.progress * 100)}%"

        f_chip = QFont(painter.font())
        f_chip.setPointSize(max(8, f_chip.pointSize() - 1))
        f_chip.setBold(True)
        painter.setFont(f_chip)
        fm = painter.fontMetrics()

        has_open = item.status == "done" and bool(item.files)
        open_rect = self.open_button_rect(rect) if has_open else QRect()
        avail_w = (open_rect.left() - rect.left() - 12) if has_open else (rect.width() - 12)

        chip_w = min(max(fm.horizontalAdvance(label_text) + 16, 64), max(64, avail_w))
        chip_h = 20
        chip_y = rect.top() + (6 if item.status == "running" else (rect.height() - chip_h) // 2)
        chip_rect = QRect(rect.left() + 6, chip_y, chip_w, chip_h)

        painter.setBrush(fill_col)
        painter.setPen(QPen(base_col, 1))
        painter.drawRoundedRect(QRectF(chip_rect).adjusted(0.5, 0.5, -0.5, -0.5), 9.0, 9.0)
        painter.setPen(base_col)
        elided = fm.elidedText(label_text, Qt.TextElideMode.ElideRight, chip_w - 12)
        painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, elided)

        if item.status == "running":
            self._ensure_shimmer()
            bar_x = rect.left() + 6
            bar_y = rect.bottom() - 9
            bar_w = max(40, rect.width() - 14)
            bar_h = 4
            track = QRectF(bar_x, bar_y, bar_w, bar_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG))
            painter.drawRoundedRect(track, 2.0, 2.0)

            from qt_ui.motion import Motion
            if item.progress < 0 and Motion.enabled():
                chunk_w = max(14.0, bar_w * 0.35)
                slide_x = bar_x + (bar_w - chunk_w) * self._shimmer_phase
                chunk = QRectF(slide_x, bar_y, chunk_w, bar_h)
                painter.setBrush(QColor(ACCENT))
                painter.drawRoundedRect(chunk, 2.0, 2.0)
            else:
                frac = 0.35 if item.progress < 0 else max(0.0, min(1.0, item.progress))
                if frac > 0:
                    chunk = QRectF(bar_x, bar_y, max(4.0, bar_w * frac), bar_h)
                    painter.setBrush(QColor(ACCENT))
                    painter.drawRoundedRect(chunk, 2.0, 2.0)

        if has_open:
            painter.setBrush(QColor(BG3))
            painter.setPen(QPen(QColor(BORDER_STRONG), 1))
            painter.drawRoundedRect(QRectF(open_rect).adjusted(0.5, 0.5, -0.5, -0.5), 4.0, 4.0)
            painter.setPen(QColor(FG))
            painter.drawText(open_rect, Qt.AlignmentFlag.AlignCenter, t("Open"))

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if index.column() == 4 and event.type() == QEvent.Type.MouseButtonRelease:
            item: QueueItem | None = index.data(ITEM_ROLE)
            if item is not None and item.status == "done" and item.files:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if self.open_button_rect(option.rect).contains(pos):
                    self.queue_tab.open_item_folder(item.iid)
                    return True
        return super().editorEvent(event, model, option, index)


class LogView(QPlainTextEdit):
    """Read-only log: «[hh:mm:ss] » in muted grey, then the message coloured by its kind; follows the newest line.

    Phase 9c (F3): keeps ``entries`` so severity filters («all» | «warn» | «err»), substring search, and
    «Pause autoscroll» can re-render or hold position without losing the full history.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("logView")
        self.setReadOnly(True)
        self.setFont(mono_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.setMinimumHeight(8 * self.fontMetrics().lineSpacing() + 16)  # tkinter: height=8 lines
        self.resize(600, 180)  # ensures scrollbar range is valid even while drawer is collapsed
        self._formats: dict[str, QTextCharFormat] = {}
        for kind, colour in LOG_COLOURS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            self._formats[kind] = fmt

        self.entries: list[tuple[str, str, str]] = []  # (stamp, msg, kind)
        self.filter_kind: str = "all"  # all | warn | err
        self.search_query: str = ""
        self.pause_autoscroll: bool = False

    def matches(self, msg: str, kind: str) -> bool:
        if self.filter_kind == "warn" and kind != "warn":
            return False
        if self.filter_kind == "err" and kind != "err":
            return False
        if self.search_query and self.search_query.lower() not in msg.lower():
            return False
        return True

    def add_line(self, msg: str) -> tuple[str, str]:
        stamp = f"[{time.strftime('%H:%M:%S')}] "
        kind = log_kind(msg)
        self.entries.append((stamp, msg, kind))
        if self.matches(msg, kind):
            self._append_formatted(stamp, msg, kind)
        return stamp, kind

    def _append_formatted(self, stamp: str, msg: str, kind: str) -> None:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(stamp, self._formats["stamp"])
        cursor.insertText(f"{msg}\n", self._formats[kind])
        if not self.pause_autoscroll:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())

    def set_filter(self, kind: str) -> None:
        kind = kind if kind in ("all", "warn", "err") else "all"
        if kind == self.filter_kind:
            return
        self.filter_kind = kind
        self.rebuild()

    def set_search(self, query: str) -> None:
        query = query.strip()
        if query == self.search_query:
            return
        self.search_query = query
        self.rebuild()

    def set_pause_autoscroll(self, paused: bool) -> None:
        self.pause_autoscroll = bool(paused)
        if not self.pause_autoscroll:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())

    def rebuild(self) -> None:
        super().clear()
        for stamp, msg, kind in self.entries:
            if self.matches(msg, kind):
                self._append_formatted(stamp, msg, kind)

    def clear_log(self) -> None:
        self.entries.clear()
        self.clear()

    def log_text(self) -> str:
        return self.toPlainText().rstrip("\n")


class QueueTab(QWidget):
    status_message = Signal(str)
    plan_requested = Signal()
    show_requested = Signal()

    def __init__(self, bridge: Bridge | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("QueueTab")
        self.bridge = bridge if bridge is not None else Bridge(self)
        self.model = QueueModel(self)
        self.runner = QueueRunner(self.bridge, self)
        self.blocked_reason = lambda: ""
        self.output_dir = lambda: DEFAULTS["out_dir"]
        self.cancel_other = lambda: False  # the window cancels what it runs itself (a chat overlay); True if it did

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = ScrollFrame(8, self)  # scrolls when the window is too short, like the tkinter ScrollFrame
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # nothing decorative in the Tab order (found in Phase 4)
        self.scroll.body_layout.setSpacing(10)
        outer.addWidget(self.scroll)
        self._build_queue_card()
        self._build_log_card()

        self.bridge.log.connect(self.log)
        self.bridge.item.connect(self.set_item_status)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.queue_done.connect(self.on_queue_done)
        self._thumb_fetcher = QueueThumbFetcher(self)
        self._thumb_fetcher.thumb_ready.connect(self._on_thumb_ready)
        self.refresh_summary()
        language_bus().changed.connect(self.refresh_language)

    # ---------------------------- building ---------------------------- #
    def _build_queue_card(self) -> None:
        self.queue_card = Card(t("Queue"))
        self.scroll.body_layout.addWidget(self.queue_card, 1)

        # F2 Header summary banner: real-time counters + existing summary_label + in-card progress bar
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 8)
        header_row.setSpacing(12)

        self.counter_label = QLabel("")
        self.counter_label.setObjectName("queueCounterBanner")
        self.counter_label.setProperty("role", "rowtitle")
        header_row.addWidget(self.counter_label)

        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "muted")
        header_row.addWidget(self.summary_label, 1)

        self.queue_progress = QProgressBar()
        self.queue_progress.setObjectName("queueHeaderProgress")
        self.queue_progress.setRange(0, 100)
        self.queue_progress.setValue(0)
        self.queue_progress.setTextVisible(False)
        self.queue_progress.setFixedHeight(6)
        self.queue_progress.setMaximumWidth(180)
        self.queue_progress.setVisible(False)
        header_row.addWidget(self.queue_progress)
        self.queue_card.body_layout.addLayout(header_row)

        self.table = QTableView()
        self.table.setObjectName("queueTable")
        self.table.setModel(self.model)
        self.delegate = QueueRowDelegate(self.table, self)
        self.table.setItemDelegate(self.delegate)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.installEventFilter(self)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        head = self.table.horizontalHeader()
        head.setFixedHeight(HEADER_HEIGHT)
        head.setHighlightSections(False)
        head.setSectionsClickable(False)
        for col, (_key, _text, width, _anchor, stretch) in enumerate(COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch if stretch else QHeaderView.ResizeMode.Fixed)
            if not stretch:
                head.resizeSection(col, width)
        self.table.setMinimumHeight(HEADER_HEIGHT + 5 * ROW_HEIGHT + 2)
        self.queue_card.add_widget(self.table)
        self.empty = EmptyState(self.table, top=HEADER_HEIGHT)  # under the column headings
        self.queue_card.body_layout.setStretchFactor(self.table, 1)

        # F2 & F4 Grouped action buttons: primary execution vs secondary queue management
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 10, 0, 0)
        buttons.setSpacing(6)

        # Primary group: Start queue / Cancel current
        self.start_btn = QPushButton(t("Start queue"))
        self.start_btn.setIcon(icon("play", 15, ACCENT_TEXT))
        self.start_btn.setProperty("variant", "accent")
        self.start_btn.clicked.connect(self.start_queue)
        self.cancel_btn = QPushButton(t("Cancel current"))
        self.cancel_btn.setIcon(icon("stop", 15))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_current)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)

        sep = QFrame()
        sep.setObjectName("divider")
        sep.setFixedSize(1, 22)
        buttons.addSpacing(4)
        buttons.addWidget(sep)
        buttons.addSpacing(4)

        # Secondary group: Retry / Move up / Move down / Remove selected / Clear finished
        self.retry_btn = QPushButton(t("Retry"))
        self.retry_btn.setIcon(icon("refresh", 15))
        self.retry_btn.setToolTip(t("Retry failed or cancelled jobs"))
        self.retry_btn.clicked.connect(self.retry_failed_or_selected)
        self.move_up_btn = QPushButton("\u2191")
        self.move_up_btn.setProperty("variant", "ghost")
        self.move_up_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.move_up_btn.setToolTip(t("Move selected waiting job up"))
        self.move_up_btn.clicked.connect(lambda: self.move_selected(-1))
        self.move_down_btn = QPushButton("\u2193")
        self.move_down_btn.setProperty("variant", "ghost")
        self.move_down_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.move_down_btn.setToolTip(t("Move selected waiting job down"))
        self.move_down_btn.clicked.connect(lambda: self.move_selected(1))
        self.remove_btn = QPushButton(t("Remove selected"))
        self.remove_btn.setIcon(icon("trash", 15))
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton(t("Clear finished"))
        self.clear_btn.setIcon(icon("check", 15))
        self.clear_btn.clicked.connect(self.clear_finished)
        self.clear_all_btn = QPushButton(t("Clear queue"))
        self.clear_all_btn.setIcon(icon("x", 15))
        self.clear_all_btn.setToolTip(t("Clear all jobs from the queue"))
        self.clear_all_btn.clicked.connect(self.clear_all_jobs)

        for b in (self.retry_btn, self.move_up_btn, self.move_down_btn, self.remove_btn, self.clear_btn, self.clear_all_btn):
            buttons.addWidget(b)

        from core.ui_state import load_ui_state, save_ui_state
        from qt_ui.widgets import ComboBox

        st = load_ui_state()
        self.max_concurrent_jobs = getattr(st, "max_concurrent_jobs", 1) or 1
        self.rate_limit = getattr(st, "rate_limit", "") or ""

        self.concurrency_combo = ComboBox()
        self.concurrency_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.concurrency_combo.addItems([t("1 job"), t("2 parallel jobs"), t("3 parallel jobs"), t("4 parallel jobs")])
        self.concurrency_combo.setToolTip(t("How many queue jobs can run at the same time"))
        self.concurrency_combo.setCurrentIndex(max(0, min(3, self.max_concurrent_jobs - 1)))

        def _on_concurrency_changed(idx: int):
            self.max_concurrent_jobs = idx + 1
            self.runner.max_concurrent = self.max_concurrent_jobs
            s = load_ui_state()
            s.max_concurrent_jobs = self.max_concurrent_jobs
            save_ui_state(s)

        self.concurrency_combo.currentIndexChanged.connect(_on_concurrency_changed)
        buttons.addWidget(self.concurrency_combo)

        self._speed_limit_choices = [
            (N_("Unlimited speed"), ""),
            ("1 MB/s", "1M"),
            ("2 MB/s", "2M"),
            ("5 MB/s", "5M"),
            ("10 MB/s", "10M"),
            ("20 MB/s", "20M"),
        ]
        self.speed_limit_combo = ComboBox()
        self.speed_limit_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label, _val in self._speed_limit_choices:
            self.speed_limit_combo.addItem(t(label))
        self.speed_limit_combo.setToolTip(t("Bandwidth limit passed to yt-dlp (--limit-rate)"))
        current_speed_idx = next(
            (i for i, (_l, val) in enumerate(self._speed_limit_choices) if val == self.rate_limit), 0
        )
        self.speed_limit_combo.setCurrentIndex(current_speed_idx)

        def _on_speed_changed(idx: int):
            self.rate_limit = self._speed_limit_choices[idx][1]
            s = load_ui_state()
            s.rate_limit = self.rate_limit
            save_ui_state(s)

        self.speed_limit_combo.currentIndexChanged.connect(_on_speed_changed)
        buttons.addWidget(self.speed_limit_combo)

        buttons.addStretch(1)
        self.folder_btn = QPushButton(t("Open folder"))
        self.folder_btn.setIcon(icon("folder-open", 15))
        self.folder_btn.clicked.connect(self.open_queue_folder)
        buttons.addWidget(self.folder_btn)
        self.queue_card.body_layout.addLayout(buttons)

    def _build_log_card(self) -> None:
        self.log_card = Card(t("Log"))
        self.scroll.body_layout.addWidget(self.log_card, 1)

        # Integrated console toolbar: filters & search on left, autoscroll & actions on right
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 8)
        toolbar.setSpacing(6)

        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in (("all", "All"), ("warn", "Warnings"), ("err", "Errors")):
            btn = QPushButton(t(label))
            btn.setProperty("variant", "chip")
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _checked=False, k=key: self.set_log_filter(k))
            toolbar.addWidget(btn)
            self.filter_buttons[key] = btn

        self.log_search_entry = QLineEdit()
        self.log_search_entry.setPlaceholderText(t("Filter log lines…"))
        self.log_search_entry.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.log_search_entry.setMaximumWidth(240)
        self.log_search_entry.textChanged.connect(self._on_log_search)
        toolbar.addWidget(self.log_search_entry)

        toolbar.addStretch(1)

        self.autoscroll_btn = QPushButton(t("Pause autoscroll"))
        self.autoscroll_btn.setProperty("variant", "chip")
        self.autoscroll_btn.setCheckable(True)
        self.autoscroll_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.autoscroll_btn.toggled.connect(self._on_autoscroll_toggled)
        toolbar.addWidget(self.autoscroll_btn)

        self.save_log_btn = QPushButton(t("Save log…"))
        self.save_log_btn.setIcon(icon("download", 14))
        self.save_log_btn.clicked.connect(self.save_log)
        toolbar.addWidget(self.save_log_btn)

        self.copy_btn = QPushButton(t("Copy log"))
        self.copy_btn.setIcon(icon("copy", 14))
        self.copy_btn.clicked.connect(self.copy_log)
        toolbar.addWidget(self.copy_btn)

        self.clear_log_btn = QPushButton(t("Clear log"))
        self.clear_log_btn.setIcon(icon("trash", 14))
        self.clear_log_btn.clicked.connect(self.clear_log)
        toolbar.addWidget(self.clear_log_btn)

        self.log_card.body_layout.addLayout(toolbar)

        # Embedded console terminal
        self.log_view = LogView()
        self.log_view.setMinimumHeight(180)
        self.log_card.body_layout.addWidget(self.log_view, 1)

        # Backward-compatibility stubs
        self.log_preview_label = QLabel()

    # ---------------------------- the log (F3) ---------------------------- #
    def log(self, msg: str) -> None:
        stamp, kind = self.log_view.add_line(msg)
        colour = LOG_COLOURS.get(kind, FG)
        self.log_preview_label.setText(f"{stamp}{msg}")
        self.log_preview_label.setStyleSheet(f"color: {colour};")

    def set_log_filter(self, kind: str) -> None:
        for k, btn in self.filter_buttons.items():
            btn.setChecked(k == kind)
        self.log_view.set_filter(kind)

    def _on_log_search(self, text: str) -> None:
        self.log_view.set_search(text)

    def _on_autoscroll_toggled(self, paused: bool) -> None:
        self.log_view.set_pause_autoscroll(paused)

    def clear_log(self) -> None:
        self.log_view.clear_log()
        self.log_preview_label.setText(t("No log messages yet."))
        self.log_preview_label.setStyleSheet(f"color: {MUTED};")

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.log_text())
        self.status_message.emit(t("Log copied to the clipboard."))

    def save_log(self, target_path: str | Path | None = None) -> bool:
        """Export the visible log text to a file (Phase 9c, F3)."""
        path = str(target_path) if target_path else dialogs.save_file(
            self, t("Save log"), "luckytwitch_log.txt", t("Text files (*.txt);;All files (*.*)")
        )
        if not path:
            return False
        try:
            Path(path).write_text(self.log_view.log_text(), encoding="utf-8")
            self.status_message.emit(t("Log saved to {name}.", name=Path(path).name))
            notify.success(self, t("Log saved"), str(Path(path).name))
            return True
        except OSError as e:
            dialogs.error(self, t("Save log"), str(e))
            return False

    # ---------------------------- the queue (F1, F2, F4) ---------------------------- #
    @property
    def items(self) -> list[QueueItem]:
        return self.model.items

    def refresh_summary(self) -> None:
        """Update the F2 real-time counter banner, legacy summary_label, retry button, and empty state."""
        self.summary_label.setText(self.model.summary())
        self.counter_label.setText(self.model.header_summary())
        has_retryable = any(it.status in ("failed", "cancelled") for it in self.items)
        self.retry_btn.setEnabled(has_retryable)
        if self.items:
            self.empty.hide_message()
        else:
            self.empty.show_message(
                t("Nothing in the queue yet"),
                t("Set your cut points in the Plan tab and press «Add to queue»."),
                button=(t("Go to the Plan tab"), self.plan_requested.emit),
            )

    def enqueue(self, job: object, label: str, n_parts: int, strat: str, thumb: object = None) -> QueueItem:
        item = self.model.add(job, label, n_parts, strat, thumb=thumb)
        self.refresh_summary()
        language_bus().changed.connect(self.refresh_language)
        self.log(f"Queued: {label} ({n_parts} parts, {strat})")
        if thumb is None:
            self._ensure_thumbnail(item)
        return item

    def _ensure_thumbnail(self, item: QueueItem) -> None:
        src = getattr(getattr(item, "job", None), "source", None)
        thumb_val = getattr(src, "thumbnail", "") or ""
        if not thumb_val:
            return
        if Path(thumb_val).is_file():
            pm = QPixmap(str(thumb_val))
            if not pm.isNull():
                self.model.set_thumbnail(item.iid, pm)
        elif str(thumb_val).startswith("http"):
            self._thumb_fetcher.submit(item.iid, str(thumb_val))

    def _on_thumb_ready(self, iid: str, path: str) -> None:
        pm = QPixmap(path)
        if not pm.isNull():
            self.model.set_thumbnail(iid, pm)

    def set_item_status(self, iid: str, status: str) -> None:
        self.model.set_status(iid, status)
        self.refresh_summary()
        language_bus().changed.connect(self.refresh_language)

    def _on_progress(self, frac: float, text: str) -> None:
        self.model.set_running_progress(frac, text)
        if frac < 0:
            self.queue_progress.setRange(0, 0)
            self.queue_progress.setVisible(True)
        else:
            self.queue_progress.setRange(0, 100)
            pct = round(frac * 100)
            self.queue_progress.setValue(pct)
            self.queue_progress.setVisible(pct > 0 or self.runner.is_running())

    set_running_progress = _on_progress

    def selected_iids(self) -> list[str]:
        if not self.table.selectionModel():
            return []
        rows = self.table.selectionModel().selectedRows()
        iids: list[str] = []
        for idx in rows:
            iid = self.model.index(idx.row(), 0).data(IID_ROLE)
            if iid and iid not in iids:
                iids.append(iid)
        return iids

    def selected_iid(self) -> str | None:
        iids = self.selected_iids()
        return iids[0] if iids else None

    def select_item(self, iid: str) -> None:
        row = self.model.row_of(iid)
        if row >= 0:
            self.table.selectionModel().select(
                self.model.index(row, 0),
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
            )
            self.table.setCurrentIndex(self.model.index(row, 0))

    def move_selected(self, delta: int) -> bool:
        """Move the selected waiting («queued») item up (``delta = -1``) or down (``delta = 1``) (F4)."""
        iid = self.selected_iid()
        if iid is None:
            return False
        ok = self.model.move_item(iid, delta)
        if ok:
            self.select_item(iid)
        return ok

    def retry_item(self, iid: str) -> QueueItem | None:
        """Reset a single failed or cancelled item to «queued» at the end of the queue (F4)."""
        item = self.model.retry_item(iid)
        if item is not None:
            self.refresh_summary()
            self.log(f"Retrying: {item.label}")
        return item

    def retry_failed_or_selected(self) -> list[QueueItem]:
        """If the selected item is failed/cancelled, retry it; otherwise retry all failed/cancelled items (F4)."""
        sel = self.selected_iid()
        if sel is not None:
            it = self.model.find(sel)
            if it is not None and it.status in ("failed", "cancelled"):
                retried = self.retry_item(sel)
                return [retried] if retried else []
        target_iids = [it.iid for it in self.items if it.status in ("failed", "cancelled")]
        out: list[QueueItem] = []
        for iid in target_iids:
            r = self.retry_item(iid)
            if r is not None:
                out.append(r)
        return out

    def remove_selected(self) -> None:
        iids = self.selected_iids()
        if not iids:
            return
        running = [iid for iid in iids if (it := self.model.find(iid)) and it.status == "running"]
        if len(running) == len(iids):
            dialogs.info(self, t("Running"), t("Cancel the running job first."))
            return
        for iid in iids:
            if iid not in running:
                self.model.remove(iid)
        self.refresh_summary()
        if self.table.selectionModel():
            self.table.selectionModel().clearSelection()
        language_bus().changed.connect(self.refresh_language)

    def clear_finished(self) -> None:
        self.model.clear_finished()
        self.refresh_summary()
        language_bus().changed.connect(self.refresh_language)

    def clear_all_jobs(self) -> None:
        if not self.model.items:
            return
        running = self.model.running_item()
        msg = (
            t("Are you sure you want to clear the entire queue?\nThe running job will be stopped.")
            if running is not None
            else t("Are you sure you want to clear all jobs from the queue?")
        )
        if not dialogs.ask_yes_no(self, t("Clear queue"), msg):
            return
        if running is not None:
            self.runner.cancel()
        self.model.clear_all(keep_running=False)
        self.refresh_summary()
        self.status_message.emit(t("Queue cleared."))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.remove_selected()
                return True
        return super().eventFilter(watched, event)

    def shutdown(self) -> None:
        self._thumb_fetcher.stop()

    # ---------------------------- running ---------------------------- #
    def set_running(self, running: bool) -> None:
        """«Start queue» is off and «Cancel current» on while something runs (a job, or a saved-chat overlay)."""
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.queue_progress.setVisible(running)

    def start_queue(self) -> None:
        if self.runner.is_running():
            return
        reason = self.blocked_reason()
        if reason:
            self.status_message.emit(reason)
            return
        todo = [it for it in self.items if it.status == "queued"]
        if not todo:
            self.status_message.emit(t("Nothing queued."))
            return
        self.show_requested.emit()
        self.set_running(True)
        max_c = getattr(self, "max_concurrent_jobs", 1)
        r_lim = getattr(self, "rate_limit", "")
        if r_lim:
            for it in todo:
                if hasattr(it.job, "opts") and not getattr(it.job.opts, "rate_limit", ""):
                    it.job.opts.rate_limit = r_lim
        self.runner.start(todo, model=self.model, max_concurrent=max_c)

    def cancel_current(self) -> None:
        sel_idx = self.table.selectionModel().currentIndex() if self.table.selectionModel() else None
        if sel_idx and sel_idx.isValid():
            it = sel_idx.data(ITEM_ROLE)
            if it is not None and it.status == "running" and it.iid in self.runner.active_contexts:
                self.runner.cancel(it.iid)
                self.status_message.emit(t("Cancelling {name}…", name=it.label))
                return
        if self.runner.cancel() or self.cancel_other():
            self.status_message.emit(t("Cancelling…"))

    def on_queue_done(self) -> None:
        self.set_running(False)
        self.queue_progress.setRange(0, 100)
        self.queue_progress.setValue(0)
        self.queue_progress.setVisible(False)
        self.runner.finish()
        self.refresh_summary()
        language_bus().changed.connect(self.refresh_language)

    # ---------------------------- folders ---------------------------- #
    def open_output_folder(self, path: Path | None = None, select: bool = False) -> None:
        """Open the output folder (created if missing), or ``path`` when given."""
        target = Path(path) if path else Path(str(self.output_dir()).strip() or DEFAULTS["out_dir"])
        try:
            if not select:
                target.mkdir(parents=True, exist_ok=True)
            open_in_file_manager(target, select)
        except OSError as e:
            dialogs.info(self, t("Open folder"), t("Could not open:\n{target}\n\n{error}", target=target, error=e))

    def open_item_folder(self, iid: str) -> None:
        """Open the folder for a specific queue item ``iid`` (used by the inline «Open» button on finished rows)."""
        item = self.model.find(iid)
        if item is not None:
            self._open_for_item(item)
        else:
            self.open_output_folder()

    def open_queue_folder(self) -> None:
        """Open where the selected queue item was saved (highlighting its first file); else the last finished item;
        else the output folder."""
        sel = self.selected_iid()
        item = self.model.find(sel) if sel else None
        if item is None:
            item = next((i for i in reversed(self.items) if i.files), None)
        if item:
            self._open_for_item(item)
            return
        self.open_output_folder()

    def _open_for_item(self, item: QueueItem) -> None:
        files = [Path(f) for f in item.files if Path(f).exists()]
        if files:
            self.open_output_folder(files[0], select=True)
            return
        try:  # not finished yet: its stream folder if it exists
            folder = stream_dir(item.job.source, item.job.opts)
            if folder.is_dir():
                self.open_output_folder(folder)
                return
        except Exception:  # noqa: BLE001
            pass
        self.open_output_folder(Path(item.job.opts.out_dir))

    def refresh_language(self) -> None:
        """Update QueueTab text labels dynamically when language changes."""
        self.start_btn.setText(t("Start queue"))
        self.cancel_btn.setText(t("Cancel current"))
        self.retry_btn.setText(t("Retry"))
        self.retry_btn.setToolTip(t("Retry failed or cancelled jobs"))
        self.move_up_btn.setToolTip(t("Move selected waiting job up"))
        self.move_down_btn.setToolTip(t("Move selected waiting job down"))
        self.remove_btn.setText(t("Remove selected"))
        self.clear_btn.setText(t("Clear finished"))
        self.folder_btn.setText(t("Open folder"))
        self.copy_btn.setText(t("Copy log"))
        self.save_log_btn.setText(t("Save log…"))
        self.clear_log_btn.setText(t("Clear log"))
        self.autoscroll_btn.setText(t("Pause autoscroll"))
        self.log_search_entry.setPlaceholderText(t("Filter log lines…"))
        if hasattr(self, "log_card") and getattr(self.log_card, "title_label", None):
            self.log_card.title_label.setText(t("Log"))
        if hasattr(self, "queue_card") and getattr(self.queue_card, "title_label", None):
            self.queue_card.title_label.setText(t("Queue"))
        cur_concurrency = self.concurrency_combo.currentIndex()
        self.concurrency_combo.blockSignals(True)
        self.concurrency_combo.clear()
        self.concurrency_combo.addItems([t("1 job"), t("2 parallel jobs"), t("3 parallel jobs"), t("4 parallel jobs")])
        self.concurrency_combo.setCurrentIndex(cur_concurrency)
        self.concurrency_combo.setToolTip(t("How many queue jobs can run at the same time"))
        self.concurrency_combo.blockSignals(False)
        cur_speed = self.speed_limit_combo.currentIndex()
        self.speed_limit_combo.blockSignals(True)
        self.speed_limit_combo.clear()
        for label, _val in self._speed_limit_choices:
            self.speed_limit_combo.addItem(t(label))
        self.speed_limit_combo.setCurrentIndex(cur_speed)
        self.speed_limit_combo.setToolTip(t("Bandwidth limit passed to yt-dlp (--limit-rate)"))
        self.speed_limit_combo.blockSignals(False)
        if hasattr(self, "filter_buttons"):
            labels = {"all": "All", "warn": "Warnings", "err": "Errors"}
            for k, btn in self.filter_buttons.items():
                if k in labels:
                    btn.setText(t(labels[k]))
        if hasattr(self, "model"):
            self.model.refresh_language()
        self.refresh_summary()
        self.table.viewport().update()
