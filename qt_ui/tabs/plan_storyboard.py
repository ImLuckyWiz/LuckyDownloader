"""Clips -> chapters card, clips table selection/actions, timeline sync & storyboard frame loading for PlanTab."""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QStyledItemDelegate,
    QTableView, QWidget,
)

from core.i18n import N_, t, tn
from core.options import flag
from core.palette import ACCENT
from luckytwitch_engine import (
    EngineError, Range, clip_start, fmt_hms, insert_cut_point, make_chapters, ranges_of, ranges_to_text,
)
from qt_ui import dialogs
from qt_ui.icons import icon
from qt_ui.widgets import Card, SpinBox, Toggle, WrapLabel

HEADER_HEIGHT = 34
ROW_HEIGHT = 28

CLIP_COLUMNS = (  # key, heading, width, alignment, stretches
    ("at", N_("At"), 80, "center", False),
    ("views", N_("Views"), 70, "center", False),
    ("dur", N_("Duration"), 75, "center", False),
    ("title", N_("Title"), 380, "w", True),
    ("creator", N_("Creator"), 140, "w", False),
    ("chap", N_("Chapter"), 108, "center", False),
)


def _alignment(kind: str) -> Qt.AlignmentFlag:
    return (Qt.AlignmentFlag.AlignHCenter if kind == "center" else Qt.AlignmentFlag.AlignLeft) | \
        Qt.AlignmentFlag.AlignVCenter


class ClipViewsDelegate(QStyledItemDelegate):
    """Paints a subtle proportional view-count bar behind the Views column (Phase 9e, D5)."""

    def __init__(self, model: ClipModel, parent: QWidget | None = None):
        super().__init__(parent)
        self._model = model

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        max_v = self._model.max_views
        val = self._model.view_value(index.row())
        if max_v > 0 and val > 0:
            ratio = min(max(val / max_v, 0.05), 1.0)
            r = option.rect.adjusted(4, 5, -4, -5)
            bar_w = max(4.0, r.width() * ratio)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(ACCENT)
            c.setAlpha(55)
            painter.setBrush(c)
            painter.drawRoundedRect(QRectF(r.right() - bar_w, r.top(), bar_w, r.height()), 3.0, 3.0)
            painter.restore()
        super().paint(painter, option, index)


class ClipModel(QAbstractTableModel):
    """The clips table of the Plan tab (decision D5): At, Views, Duration, Title, Creator, Chapter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[str, str, str, str, str, str]] = []
        self.max_views: int = 0

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(CLIP_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(CLIP_COLUMNS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return t(CLIP_COLUMNS[section][1])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(_alignment(CLIP_COLUMNS[section][3]))
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(_alignment(CLIP_COLUMNS[index.column()][3]))
        return None

    def view_value(self, row: int) -> int:
        if not 0 <= row < len(self.rows):
            return 0
        try:
            return int(self.rows[row][1])
        except (ValueError, TypeError):
            return 0

    def set_rows(self, rows: list[tuple[str, str, str, str, str, str]]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        views = []
        for r in self.rows:
            try:
                views.append(int(r[1]))
            except (ValueError, TypeError):
                pass
        self.max_views = max(views, default=0)
        self.endResetModel()


class PlanStoryboardMixin:
    """Mixin for PlanTab managing clips -> chapters table, timeline sync, and storyboard frames."""

    def _adjust_clip_columns(self) -> None:
        """Adapt the Title column width to absorb available table width without horizontal overflow."""
        if not hasattr(self, "tree"):
            return
        head = self.tree.horizontalHeader()
        title_col = -1
        fixed_w = 0
        for col, (_key, _text, width, _anchor, stretch) in enumerate(CLIP_COLUMNS):
            if stretch:
                title_col = col
            else:
                fixed_w += width
        if title_col < 0:
            return
        avail = self.tree.viewport().width()
        if avail <= 0:
            avail = self.tree.width()
        if avail > 0:
            title_w = max(140, avail - fixed_w)
            head.resizeSection(title_col, title_w)

    def _build_clips_card(self) -> None:
        self.clips_card = Card(t("Clips → chapters"), t("Optional: put the VOD's clips in the files as chapters."))
        self.clips_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lower_layout.addWidget(self.clips_card, 1)

        self.chapters_row = self.clips_card.add_row(
            t("Add clips as chapters"), t("Each clip that passes the filter becomes a chapter."),
            info=t("Needs the Twitch API sign-in (the «Twitch API…» button). Chapters are written into the video "
                   "files; the Premiere Pro outputs (Options → Premiere Pro) have their own switches."))
        self.chapters_toggle = Toggle()
        self.binder.bind("chapters", self.chapters_toggle)
        self.chapters_toggle.clicked.connect(self.refresh_clips)
        self.chapters_row.add_control(self.chapters_toggle)

        frow = QWidget()
        frow.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        fgrid = QGridLayout(frow)
        fgrid.setContentsMargins(0, 0, 0, 8)
        fgrid.setHorizontalSpacing(8)
        fgrid.setVerticalSpacing(6)
        fgrid.setColumnMinimumWidth(2, 20)
        fgrid.setColumnStretch(5, 1)
        self.filter_spins: dict[str, SpinBox] = {}
        self.filter_labels: dict[str, QLabel] = {}

        def add_filter_field(row: int, col: int, label: str, name: str, width: int = 5) -> None:
            lbl = QLabel(label)
            lbl.setProperty("role", "muted")
            sp = SpinBox(0, 1_000_000, width)
            self.binder.bind(name, sp)
            sp.valueChanged.connect(self._on_filter_spin)
            c_label = 0 if col == 0 else 3
            c_spin = 1 if col == 0 else 4
            fgrid.addWidget(lbl, row, c_label, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            fgrid.addWidget(sp, row, c_spin, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.filter_spins[name] = sp
            self.filter_labels[name] = lbl

        add_filter_field(0, 0, t("Min views"), "min_views", 5)
        add_filter_field(0, 1, t("Min duration (s)"), "min_duration", 5)
        add_filter_field(1, 0, t("Top N (0 = all)"), "top_n", 5)
        add_filter_field(1, 1, t("Lead-in (s)"), "pad_before", 5)
        self.clips_card.add_widget(frow)

        # D4: Multi-select toolbar above the clips table
        sel_bar = QWidget()
        sel_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sblay = QHBoxLayout(sel_bar)
        sblay.setContentsMargins(0, 0, 0, 4)
        sblay.setSpacing(6)
        self.sel_lbl = QLabel(t("Selection:"))
        self.sel_lbl.setProperty("role", "muted")
        sblay.addWidget(self.sel_lbl)

        self.select_all_clips_btn = QPushButton(t("Select all"))
        self.select_all_clips_btn.setProperty("variant", "chip")
        self.select_all_clips_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.select_all_clips_btn.clicked.connect(self.select_all_clips)
        sblay.addWidget(self.select_all_clips_btn)

        self.invert_clips_btn = QPushButton(t("Invert"))
        self.invert_clips_btn.setProperty("variant", "chip")
        self.invert_clips_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.invert_clips_btn.clicked.connect(self.invert_clip_selection)
        sblay.addWidget(self.invert_clips_btn)

        self.clear_clips_btn = QPushButton(t("Clear"))
        self.clear_clips_btn.setProperty("variant", "chip")
        self.clear_clips_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_clips_btn.clicked.connect(self.clear_clip_selection)
        sblay.addWidget(self.clear_clips_btn)
        sblay.addStretch(1)
        self.clips_card.add_widget(sel_bar)

        self.clip_model = ClipModel(self)
        self.tree = QTableView()
        self.tree.setObjectName("clipsTable")
        self.tree.setModel(self.clip_model)
        self.views_delegate = ClipViewsDelegate(self.clip_model, self.tree)
        self.tree.setItemDelegateForColumn(1, self.views_delegate)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setShowGrid(False)
        self.tree.setWordWrap(False)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.verticalHeader().hide()
        self.tree.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        head = self.tree.horizontalHeader()
        head.setFixedHeight(HEADER_HEIGHT)
        head.setHighlightSections(False)
        head.setSectionsClickable(True)
        head.setStretchLastSection(False)
        for col, (_key, _text, width, _anchor, _stretch) in enumerate(CLIP_COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            head.resizeSection(col, width)
        self.tree.installEventFilter(self)
        self._adjust_clip_columns()
        self.tree.setMinimumHeight(HEADER_HEIGHT + 6 * ROW_HEIGHT + 2)
        self.tree.doubleClicked.connect(self.open_clip)
        self.tree.selectionModel().selectionChanged.connect(self._on_clip_selection_changed)
        self.clips_card.add_widget(self.tree)
        self.clips_card.body_layout.setStretchFactor(self.tree, 1)

        self.clips_label = WrapLabel("")
        self.clips_label.setProperty("role", "muted")
        self.clips_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.clips_label.setContentsMargins(0, 8, 0, 0)
        self.clips_card.add_widget(self.clips_label)

        brow = QWidget()
        brow.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        blay = QHBoxLayout(brow)
        blay.setContentsMargins(0, 8, 0, 0)
        blay.setSpacing(6)
        self.split_btn = QPushButton(t("Split at selected clip"))
        self.split_btn.setIcon(icon("scissors", 16))
        self.split_btn.clicked.connect(self.split_at_clip)
        self.download_clips_btn = QPushButton(t("Download only selected clip"))
        self.download_clips_btn.setIcon(icon("download", 16))
        self.download_clips_btn.clicked.connect(self.download_clips)
        blay.addWidget(self.split_btn)
        blay.addWidget(self.download_clips_btn)
        blay.addStretch(1)
        self.clips_card.add_widget(brow)

    def _on_filter_spin(self, _value: int) -> None:
        if not self.binder._loading:
            self.refresh_clips()

    # ---------------------------- clips table ---------------------------- #
    def refresh_clips(self) -> None:
        flt = self.build_filter()
        chapters = make_chapters(self.clips, flt)
        included = {c.get("id") for ch in chapters for c in ch.clips}
        rows: list[tuple[str, str, str, str, str, str]] = []
        for c in self.clips:
            off = clip_start(c)
            mark = "?" if off is None else ("\u2713" if c.get("id") in included else "\u2014")
            rows.append((
                fmt_hms(off), str(c.get("view_count", 0)), f"{round(c.get('duration', 0))}s",
                str(c.get("title", "")), str(c.get("creator_name", "")), mark,
            ))
        self.clip_model.set_rows(rows)
        self._update_clip_action_buttons()
        if not self.clips:
            msg = (t("No clips loaded (sign in with the Twitch API… button, optional).")
                   if not self.clips_loaded else t("This VOD has no clips."))
        else:
            placed = sum(1 for c in self.clips if clip_start(c) is not None)
            msg = t("{included} of {total} clips pass the filter → {chapters} chapters",
                    included=len(included), total=len(self.clips), chapters=len(chapters))
            if placed < len(self.clips):
                msg += t("  ({n} can't be placed: no offset)", n=len(self.clips) - placed)
            if not (flag(self.settings, "chapters") or flag(self.settings, "premiere_xml")
                    or flag(self.settings, "premiere_plugin")):
                msg += t("  [chapters are OFF]")
        self.clips_label.setText(msg)
        self._push_clip_marks()
        self._adjust_clip_columns()

    def _on_clip_selection_changed(self, *_args) -> None:
        self._update_clip_action_buttons()

    def _update_clip_action_buttons(self) -> None:
        n = len(self.selected_clip_rows()) if hasattr(self, "tree") and self.tree.selectionModel() else 0
        if n <= 0:
            self.download_clips_btn.setText(t("Download only selected clip"))
        else:
            self.download_clips_btn.setText(tn("Download {n} clip", "Download {n} clips", n))

    def selected_clip_rows(self) -> list[int]:
        return sorted(idx.row() for idx in self.tree.selectionModel().selectedRows())

    def select_clips(self, *rows: int) -> None:
        sel = self.tree.selectionModel()
        sel.clearSelection()
        for r in rows:
            if 0 <= r < self.clip_model.rowCount():
                sel.select(self.clip_model.index(r, 0),
                           QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self._update_clip_action_buttons()

    def select_all_clips(self) -> None:
        count = self.clip_model.rowCount()
        if count > 0:
            self.select_clips(*range(count))

    def invert_clip_selection(self) -> None:
        count = self.clip_model.rowCount()
        current = set(self.selected_clip_rows())
        inverted = [r for r in range(count) if r not in current]
        self.select_clips(*inverted)

    def clear_clip_selection(self) -> None:
        self.select_clips()

    def open_clip(self, _index=None) -> None:
        sel = self.selected_clip_rows()
        if sel:
            webbrowser.open(self.clips[sel[0]].get("url", ""))

    def split_at_clip(self) -> None:
        sel = self.selected_clip_rows()
        if not sel:
            dialogs.info(self, t("Select a clip"), t("Select a clip in the table first."))
            return
        if len(sel) > 1:
            dialogs.info(self, t("Select one clip"), t("Splitting works with a single clip: select just one."))
            return
        if not self.source:
            dialogs.info(self, t("No VOD"), t("Press «Get info» first."))
            return
        off = clip_start(self.clips[sel[0]])
        if off is None:
            dialogs.info(self, t("No offset"), t("That clip has no position in the VOD."))
            return
        t_pos = max(0, off - self.build_filter().pad_before)
        text = self.cut_text() or "0:00:00 - end"
        try:
            new = insert_cut_point(text, t_pos, self.source.duration)
        except EngineError as e:
            dialogs.info(self, t("Can't split here"), str(e))
            return
        self.set_cut_text(new)
        self.update_preview()

    def download_clips(self) -> None:
        self.clip_download_requested.emit()

    # ---------------------------- timeline ---------------------------- #
    def _clip_times(self) -> list[float]:
        return [t for t in (clip_start(c) for c in self.clips) if t is not None]

    def _push_clip_marks(self) -> None:
        """Give the timeline the clip moments (flags and snap points) with the tooltip text of each (E5)."""
        details: dict[float, str] = {}
        for c in self.clips:
            t_val = clip_start(c)
            if t_val is None:
                continue
            parts = [str(c.get("title", "")).strip() or t("Untitled clip")]
            if c.get("creator_name"):
                parts.append(t("by {creator}", creator=c.get("creator_name")))
            parts.append(t("{views} views", views=c.get("view_count", 0)))
            details[float(t_val)] = " \u00b7 ".join(parts)
        self.timeline.set_clip_marks(self._clip_times(), details)

    def sync_timeline(self) -> None:
        """Show the current VOD and the parts the cut text describes (called after every change of either)."""
        src = self.source
        from qt_ui.motion import DURATION_NORMAL, QWIDGETSIZE_MAX, Motion, animate_height
        want_onboard = (src is None)
        if not Motion.enabled() or not self.isVisible():
            self.onboarding_card.setMaximumHeight(QWIDGETSIZE_MAX if want_onboard else 0)
            self.onboarding_card.setVisible(want_onboard)
        else:
            if self.onboarding_card.isVisible() != want_onboard:
                if want_onboard:
                    self.onboarding_card.setMaximumHeight(0)
                    self.onboarding_card.setVisible(True)
                    target = max(self.onboarding_card.sizeHint().height(), 40)
                    animate_height(
                        self.onboarding_card, 0, target, DURATION_NORMAL,
                        on_finished=lambda: self.onboarding_card.setMaximumHeight(QWIDGETSIZE_MAX),
                    )
                else:
                    start = max(self.onboarding_card.height(), 1)
                    animate_height(
                        self.onboarding_card, start, 0, DURATION_NORMAL,
                        on_finished=lambda: (
                            self.onboarding_card.setVisible(False),
                            self.onboarding_card.setMaximumHeight(QWIDGETSIZE_MAX),
                        ),
                    )
        if src is not self._timeline_src:
            self._timeline_src = src
            if src is None:
                self.timeline.set_source(0)
            else:
                self.timeline.set_source(src.duration, src.segments, src.storyboard)
                self.timeline.set_muted(src.muted)
                self._load_frames(src)
            self._push_clip_marks()
        text = self.cut_text()
        if not text or src is None:
            self.timeline.set_ranges([] if src is not None else None)
            return
        try:
            self.timeline.set_ranges(ranges_of(text, src.duration))
        except EngineError:
            self.timeline.set_ranges(None)

    def on_timeline_edit(self, ranges: list[Range]) -> None:
        """The user changed the parts on the timeline: write them into the cut text."""
        dur = self.source.duration if self.source else None
        self.set_cut_text(ranges_to_text(ranges, dur))
        self.update_preview()

    def _load_frames(self, src) -> None:
        """Download the preview frames of ``src`` in the background; they arrive on ``Bridge.frames``."""
        if getattr(src, "storyboard", None) is None:
            return
        from qt_ui.tabs import plan as _plan_mod
        if _plan_mod.timeline_module.Image is None:
            self.timeline.set_frames(None)
            return
        self.frames_runner.start(src)

    def on_frames(self, src, frames) -> None:
        if src is self.source:
            self.timeline.set_frames(frames)
