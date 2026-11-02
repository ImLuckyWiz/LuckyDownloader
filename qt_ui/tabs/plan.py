"""The Plan tab (Phases 6 and 7): the interactive timeline strip (``qt_ui/timeline.py``), the cut points editor
with its live preview of the parts, the Clips -> chapters card, and the always-visible footer with «Add to queue» and
«Add & start».

Port of ``ui/plan_tab.py`` (``PlanTabMixin``) and the plan-tab parts of ``luckytwitch_downloader.py``. The cut text box
is the source of truth: the timeline is redrawn from it (``sync_timeline``) and every edit made on the timeline is
written back into it (``on_timeline_edit``). The five settings on this tab (``chapters``, ``min_views``,
``min_duration``, ``top_n``, ``pad_before``) are bound to the window's settings dictionary with a ``SettingsBinder``
(decision D3).
"""

from __future__ import annotations

import webbrowser
from typing import Callable, Sequence

from PySide6.QtCore import QAbstractTableModel, QEvent, QItemSelectionModel, QModelIndex, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollBar, QSizePolicy, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget,
)

from core import paths
from core.options import QUALITY_CHOICES, STRATEGIES, build_filter, build_options, flag
from core.palette import ACCENT, ACCENT_DIM, ACCENT_TEXT, BG, BG3, BORDER, ERR, FG, MUTED, OK, WARN
from core.settings import DEFAULTS
from core.i18n import N_, t, tn
from core.timeline import game_colour
from luckytwitch_engine import (
    QUALITY_BEST, EngineError, GameSegment, Range, Storyboard, clean_title, clip_start, estimate_bytes, fmt_hms,
    insert_cut_point, make_chapters, make_plan, muted_overlap, ranges_of, ranges_to_text, resolve_format, toggle_part,
)
from qt_ui import dialogs, i18n_qt
from qt_ui import timeline as timeline_module
from qt_ui.background_jobs import FramesRunner
from qt_ui.binder import SettingsBinder
from qt_ui.bridge import Bridge
from qt_ui.icons import icon
from qt_ui.theme import mono_font
from qt_ui.timeline import IDLE_HINT, Timeline
from qt_ui.widgets import Card, ComboBox, MarqueeLabel, ScrollPage, SpinBox, Toggle, WrapLabel

HEADER_HEIGHT = 34
ROW_HEIGHT = 28
WIDE_BREAKPOINT = 1100
PREVIEW_COLOURS = {"ok": OK, "err": ERR, "muted": MUTED}
CUT_HINT = N_("Boundaries in order, e.g.  0:00:00 - 0:30:00 - 1:30:00 - end   (end = end of the VOD).   "
            "To skip a section use «;» or a new line:  0:00:00 - 0:30:00 ; 2:00:00 - end")


def human_size(n: int) -> str:
    """Format bytes as human-readable decimal string (e.g. 1.4 GB, 820 MB, 0 B)."""
    if n <= 0:
        return "0 B"
    if n >= 1_000_000_000:
        return f"{i18n_qt.format_number(n / 1_000_000_000, 1)} GB"
    if n >= 1_000_000:
        return f"{int(round(n / 1_000_000))} MB"
    if n >= 1_000:
        return f"{int(round(n / 1_000))} KB"
    return f"{n} B"

STRATEGY_CHOICES = (
    ("auto", N_("Auto"), "Auto"),
    ("full", N_("Full VOD + split"), "Download full VOD, then split"),
    ("sections", N_("Only the parts"), "Download only the parts"),
)
_STRATEGY_BY_SETTING = {setting: key for key, _label, setting in STRATEGY_CHOICES}
_SETTING_BY_STRATEGY = {key: setting for key, _label, setting in STRATEGY_CHOICES}
for _key, _label, _setting in STRATEGY_CHOICES:
    _SETTING_BY_STRATEGY[_label.lower()] = _setting
    _SETTING_BY_STRATEGY[_setting.lower()] = _setting

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


def _polish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


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


class PartCard(QFrame):
    """Visual part chip/card (Phase 9e, D2): ``P1 · 0:00:00 → 0:30:00 · 0:30:00`` with game-colour stripe and skip button."""

    skip_requested = Signal(int)

    def __init__(
        self,
        part_index: int,
        start: float,
        end: float,
        duration: float,
        muted_seconds: float = 0.0,
        game_name: str = "",
        color: str = ACCENT,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.part_index = part_index
        self.start = start
        self.end = end
        self.duration = duration
        self.muted_seconds = muted_seconds
        self.game_name = game_name
        self.color = color
        self.setObjectName("partCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#partCard {{ background-color: {BG}; border: 1px solid {BORDER}; border-radius: 6px; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)

        self.stripe = QFrame(self)
        self.stripe.setFixedWidth(4)
        self.stripe.setStyleSheet(
            f"background-color: {color}; border-top-left-radius: 5px; border-bottom-left-radius: 5px;"
        )
        lay.addWidget(self.stripe)

        self.badge_lbl = QLabel(f"P{part_index}", self)
        self.badge_lbl.setStyleSheet(
            f"background-color: {ACCENT_DIM}; color: {ACCENT_TEXT}; font-weight: bold; "
            f"padding: 1px 6px; border-radius: 4px;"
        )
        lay.addWidget(self.badge_lbl)

        self.span_lbl = QLabel(f"{fmt_hms(start)} \u2192 {fmt_hms(end)}", self)
        self.span_lbl.setFont(mono_font())
        lay.addWidget(self.span_lbl)

        self.dur_lbl = QLabel(f"({fmt_hms(duration)})", self)
        self.dur_lbl.setProperty("role", "muted")
        lay.addWidget(self.dur_lbl)

        if game_name:
            self.game_lbl = MarqueeLabel(game_name, self)
            lay.addWidget(self.game_lbl, 1)
        else:
            self.game_lbl = None

        if muted_seconds >= 1:
            self.muted_lbl = QLabel(t("· {time} muted", time=fmt_hms(muted_seconds)), self)
            self.muted_lbl.setStyleSheet(f"color: {WARN}; font-weight: bold;")
            lay.addWidget(self.muted_lbl)
        else:
            self.muted_lbl = None

        if not game_name:
            lay.addStretch(1)

        self.skip_btn = QPushButton(self)
        self.skip_btn.setIcon(icon("x", 12, MUTED))
        self.skip_btn.setProperty("variant", "ghost")
        self.skip_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_btn.setFixedSize(22, 22)
        self.skip_btn.setToolTip(t("Skip Part {n}", n=part_index))
        self.skip_btn.clicked.connect(lambda: self.skip_requested.emit(self.part_index))
        lay.addWidget(self.skip_btn)


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


TimelinePlaceholder = Timeline  # backward-compatible alias


class PlanTab(ScrollPage):
    add_requested = Signal(bool)  # False = «Add to queue», True = «Add & start»
    search_requested = Signal()
    paste_requested = Signal()
    strategy_changed = Signal(str)
    title_changed = Signal(str)
    quality_changed = Signal(str)
    generic_thumb_loaded = Signal(str)

    def __init__(self, settings: dict | None = None, bridge: Bridge | None = None, parent: QWidget | None = None):
        super().__init__(8, parent)
        self.setObjectName("PlanTab")
        self.settings = settings if settings is not None else {}
        self.bridge = bridge if bridge is not None else Bridge(self)
        self.binder = SettingsBinder(self.settings, self)
        self.frames_runner = FramesRunner(self.bridge)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body_layout.setSpacing(10)

        self.source = None
        self._raw_title: str = ""
        self.clips: list[dict] = []
        self.clips_loaded = False
        self._timeline_src = None
        self.preview_kind = "muted"
        self.part_cards: list[PartCard] = []
        self.last_plan = None

        self.mode_timeline = True
        self._build_onboarding_card()
        self._build_timeline_card()
        self._build_generic_card()
        self.lower_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.lower_layout.setContentsMargins(0, 0, 0, 0)
        self.lower_layout.setSpacing(10)
        self.body_layout.addLayout(self.lower_layout, 1)
        self._build_cuts_card()
        self._build_clips_card()
        self._build_footer()
        self.update_responsive_layout()

        self.bridge.frames.connect(self.on_frames)
        self.generic_thumb_loaded.connect(self._on_generic_thumb_file)
        i18n_qt.language_bus().changed.connect(self.refresh_language)
        self.update_preview()
        self.refresh_clips()

    # ---------------------------- responsive 2-column layout (D1) ---------------------------- #
    def _effective_width(self) -> int:
        win = self.window()
        if win is not None and win is not self and win.width() > 0:
            return win.width()
        return self.width()

    def is_two_column(self) -> bool:
        return self.lower_layout.direction() == QBoxLayout.Direction.LeftToRight

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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is getattr(self, "tree", None) and event.type() == QEvent.Type.Resize:
            self._adjust_clip_columns()
        return super().eventFilter(watched, event)

    def update_responsive_layout(self) -> None:
        wide = self._effective_width() >= WIDE_BREAKPOINT
        target = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        if self.lower_layout.direction() != target:
            self.lower_layout.setDirection(target)
            self._adjust_clip_columns()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update_responsive_layout()
        self._adjust_clip_columns()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.update_responsive_layout()
        self._adjust_clip_columns()

    # ---------------------------- building ---------------------------- #
    def _build_onboarding_card(self) -> None:
        """First-run / empty-state teaching banner shown when no VOD is loaded (Phase 9b, B10)."""
        self.onboarding_card = QFrame(self.body)
        self.onboarding_card.setObjectName("onboardingCard")
        self.onboarding_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        olay = QHBoxLayout(self.onboarding_card)
        olay.setContentsMargins(14, 10, 14, 10)
        olay.setSpacing(12)

        self.onboarding_steps = WrapLabel(
            t("1. Paste a link or search a streamer   ·   2. Mark where to cut   ·   3. Add to queue"),
            self.onboarding_card,
        )
        self.onboarding_steps.setProperty("role", "muted")
        olay.addWidget(self.onboarding_steps, 1)

        self.onboard_search_btn = QPushButton(t("Search streamers"), self.onboarding_card)
        self.onboard_search_btn.setIcon(icon("search", 16))
        self.onboard_search_btn.setProperty("variant", "ghost")
        self.onboard_search_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.onboard_search_btn.clicked.connect(self.search_requested.emit)
        olay.addWidget(self.onboard_search_btn)

        self.onboard_paste_btn = QPushButton(t("Paste from clipboard"), self.onboarding_card)
        self.onboard_paste_btn.setIcon(icon("copy", 16))
        self.onboard_paste_btn.setProperty("variant", "ghost")
        self.onboard_paste_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.onboard_paste_btn.clicked.connect(self.paste_requested.emit)
        olay.addWidget(self.onboard_paste_btn)

        self.body_layout.addWidget(self.onboarding_card)

    def _build_timeline_card(self) -> None:
        self.timeline_card = Card(t("Timeline"))
        self.body_layout.addWidget(self.timeline_card)
        well = QWidget()
        well.setObjectName("timelineWell")
        well.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        wlay = QVBoxLayout(well)
        wlay.setContentsMargins(8, 8, 8, 8)
        self.timeline = Timeline(on_edit=self.on_timeline_edit, parent=well)
        wlay.addWidget(self.timeline)
        self.timeline_card.add_widget(well)


    def _build_generic_card(self) -> None:
        self.generic_card = Card(t("Video details"))
        self.generic_card.setVisible(False)
        self.body_layout.addWidget(self.generic_card)

        content_row = QWidget()
        c_lay = QHBoxLayout(content_row)
        c_lay.setContentsMargins(4, 4, 4, 4)
        c_lay.setSpacing(16)

        self.generic_thumb_label = QLabel()
        self.generic_thumb_label.setFixedSize(220, 124)
        self.generic_thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generic_thumb_label.setStyleSheet(
            f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 6px; font-weight: bold; color: {MUTED};"
        )
        self.generic_thumb_label.setText(t("Video"))
        self.generic_thumb_label.setScaledContents(False)
        c_lay.addWidget(self.generic_thumb_label, 0, Qt.AlignmentFlag.AlignTop)

        right_col = QWidget()
        r_lay = QVBoxLayout(right_col)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(8)

        t_row = QWidget()
        t_lay = QHBoxLayout(t_row)
        t_lay.setContentsMargins(0, 0, 0, 0)
        t_lay.setSpacing(6)
        t_lbl = QLabel(t("Title:"))
        t_lbl.setProperty("role", "muted")
        t_lay.addWidget(t_lbl)

        self.generic_title_entry = QLineEdit()
        self.generic_title_entry.setPlaceholderText(t("Video title…"))
        self.generic_title_entry.textChanged.connect(self._on_generic_title_edited)
        t_lay.addWidget(self.generic_title_entry, 1)

        self.generic_reset_title_btn = QPushButton(t("Reset"))
        self.generic_reset_title_btn.setProperty("variant", "ghost")
        self.generic_reset_title_btn.clicked.connect(self.reset_title)
        t_lay.addWidget(self.generic_reset_title_btn)
        r_lay.addWidget(t_row)

        meta_row = QWidget()
        m_lay = QHBoxLayout(meta_row)
        m_lay.setContentsMargins(0, 0, 0, 0)
        m_lay.setSpacing(12)

        self.generic_uploader_lbl = QLabel("")
        self.generic_uploader_lbl.setProperty("role", "muted")
        m_lay.addWidget(self.generic_uploader_lbl)

        self.generic_duration_lbl = QLabel("")
        self.generic_duration_lbl.setProperty("role", "muted")
        m_lay.addWidget(self.generic_duration_lbl)

        self.generic_date_lbl = QLabel("")
        self.generic_date_lbl.setProperty("role", "muted")
        m_lay.addWidget(self.generic_date_lbl)
        m_lay.addStretch(1)
        r_lay.addWidget(meta_row)

        r_lay.addSpacing(4)

        opts_grid = QGridLayout()
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setHorizontalSpacing(10)
        opts_grid.setVerticalSpacing(8)

        q_lbl = QLabel(t("Quality:"))
        q_lbl.setProperty("role", "muted")
        opts_grid.addWidget(q_lbl, 0, 0)

        self.generic_quality_combo = ComboBox()
        self.generic_quality_combo.activated.connect(self._on_generic_quality_activated)
        opts_grid.addWidget(self.generic_quality_combo, 0, 1)

        c_lbl = QLabel(t("Format:"))
        c_lbl.setProperty("role", "muted")
        opts_grid.addWidget(c_lbl, 0, 2)

        self.generic_container_combo = ComboBox()
        for c in ("mp4", "mkv", "mp3", "m4a"):
            self.generic_container_combo.addItem(c, c)
        opts_grid.addWidget(self.generic_container_combo, 0, 3)

        self.generic_audio_toggle = Toggle()
        self.generic_audio_toggle.clicked.connect(self._on_generic_audio_toggled)
        audio_box = QWidget()
        ab_lay = QHBoxLayout(audio_box)
        ab_lay.setContentsMargins(0, 0, 0, 0)
        ab_lay.setSpacing(6)
        ab_lay.addWidget(QLabel(t("Audio only")))
        ab_lay.addWidget(self.generic_audio_toggle)
        opts_grid.addWidget(audio_box, 0, 4)

        self.generic_cookies_toggle = Toggle()
        self.generic_cookies_box = QWidget()
        cb_lay = QHBoxLayout(self.generic_cookies_box)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        cb_lay.setSpacing(6)
        self.generic_cookies_label = QLabel(t("Cookies"))
        cb_lay.addWidget(self.generic_cookies_label)
        cb_lay.addWidget(self.generic_cookies_toggle)
        opts_grid.addWidget(self.generic_cookies_box, 0, 5)

        f_lbl = QLabel(t("Folder:"))
        f_lbl.setProperty("role", "muted")
        opts_grid.addWidget(f_lbl, 1, 0)

        self.generic_folder_entry = QLineEdit()
        self.generic_folder_entry.setText(str(self.settings.get("out_dir", getattr(paths, "DOWNLOADS_DIR", ""))))
        opts_grid.addWidget(self.generic_folder_entry, 1, 1, 1, 4)

        self.generic_browse_btn = QPushButton(t("Browse…"))
        self.generic_browse_btn.setProperty("variant", "ghost")
        self.generic_browse_btn.clicked.connect(self._browse_generic_folder)
        opts_grid.addWidget(self.generic_browse_btn, 1, 5)

        r_lay.addLayout(opts_grid)
        c_lay.addWidget(right_col, 1)
        self.generic_card.add_widget(content_row)

    def _on_generic_title_edited(self, text: str) -> None:
        clean = text.strip()
        if self.source:
            self.source.title = clean
        self.title_changed.emit(clean)

    def _on_generic_audio_toggled(self) -> None:
        is_audio = self.generic_audio_toggle.isChecked()
        current = self.generic_container_combo.currentText().lower()
        if is_audio and current in ("mp4", "mkv"):
            self.generic_container_combo.setCurrentText("mp3")
        elif not is_audio and current in ("mp3", "m4a"):
            self.generic_container_combo.setCurrentText("mp4")
        self.update_preview()

    def _browse_generic_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        initial = self.generic_folder_entry.text().strip() or str(getattr(paths, "DOWNLOADS_DIR", ""))
        d = QFileDialog.getExistingDirectory(self, t("Select download folder"), initial)
        if d:
            self.generic_folder_entry.setText(d)

    def _on_generic_quality_activated(self, _index: int = 0) -> None:
        data = self.generic_quality_combo.currentData()
        for i in range(self.quality_combo.count()):
            if self.quality_combo.itemData(i) == data:
                self.quality_combo.setCurrentIndex(i)
                break
        self.update_preview()
        self.quality_changed.emit(self.current_quality())

    def set_mode(self, has_timeline: bool) -> None:
        self.mode_timeline = bool(has_timeline)
        self.timeline_card.setVisible(self.mode_timeline)
        self.cuts_card.setVisible(self.mode_timeline)
        self.clips_card.setVisible(self.mode_timeline)
        self.generic_card.setVisible(not self.mode_timeline)
        if not self.mode_timeline:
            self.onboarding_card.setVisible(False)
        self.update_preview()

    def update_generic_card(self, source) -> None:
        if source is None:
            return
        self.generic_title_entry.setText(source.title or "")
        site_str = getattr(source, "site", "video") or "video"
        uploader = source.uploader or site_str.capitalize()
        self.generic_uploader_lbl.setText(f"{uploader}")
        self.generic_duration_lbl.setText(f"{fmt_hms(source.duration)}")
        self.generic_date_lbl.setText(f"{source.date or ''}")

        self.generic_thumb_label.setPixmap(QPixmap())
        self.generic_thumb_label.setText(site_str.upper()[:4])
        thumb_url = getattr(source, "thumbnail", "")
        if thumb_url:
            self._fetch_generic_thumbnail(thumb_url)

        # Smart cookie toggle default
        browser = str(self.settings.get("cookies_from_browser", "None")).strip()
        has_browser = browser.lower() not in ("none", "disabled", "")
        if has_browser and hasattr(self, "generic_cookies_box"):
            self.generic_cookies_box.setVisible(True)
            self.generic_cookies_label.setText(t("Cookies ({browser})", browser=browser))
            self.generic_cookies_box.setToolTip(t("Send cookies from {browser} for this download", browser=browser))
            from core.cookie_scope import is_cookie_eligible
            scope = str(self.settings.get("cookies_scope", "known_only"))
            eligible = is_cookie_eligible(getattr(source, "url", ""), scope_mode=scope)
            self.generic_cookies_toggle.setChecked(eligible)
        elif hasattr(self, "generic_cookies_box"):
            self.generic_cookies_box.setVisible(False)
            self.generic_cookies_toggle.setChecked(False)

    def _fetch_generic_thumbnail(self, url: str) -> None:
        import threading
        def work():
            try:
                from pathlib import Path
                from luckytwitch_engine import fetch_thumbnail
                p = fetch_thumbnail(url)
                if p and Path(p).is_file():
                    self.generic_thumb_loaded.emit(str(p))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_generic_thumb_file(self, path_str: str) -> None:
        pm = QPixmap(path_str)
        if not pm.isNull():
            scaled = pm.scaled(self.generic_thumb_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.generic_thumb_label.setPixmap(scaled)
            self.generic_thumb_label.setText("")

    def card_title(self) -> str:
        if not getattr(self, "mode_timeline", True):
            return self.generic_title_entry.text().strip()
        return self.title_entry.text().strip()

    def current_container(self) -> str:
        if hasattr(self, "generic_container_combo"):
            return self.generic_container_combo.currentText()
        return "mp4"

    def is_audio_only(self) -> bool:
        if hasattr(self, "generic_audio_toggle"):
            return self.generic_audio_toggle.isChecked()
        return False

    def is_cookies_enabled(self) -> bool:
        if hasattr(self, "generic_cookies_toggle") and hasattr(self, "generic_cookies_box"):
            return not self.generic_cookies_box.isHidden() and self.generic_cookies_toggle.isChecked()
        return False

    def current_output_dir(self) -> str:
        if hasattr(self, "generic_folder_entry"):
            return self.generic_folder_entry.text().strip()
        return ""

    def _build_cuts_card(self) -> None:
        self.cuts_card = Card(t("Cut points"))
        self.cuts_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lower_layout.addWidget(self.cuts_card, 1)

        # Stream title row
        self.title_row = QWidget()
        trlay = QHBoxLayout(self.title_row)
        trlay.setContentsMargins(0, 0, 0, 6)
        trlay.setSpacing(6)
        self.title_lbl = QLabel(t("Title:"))
        self.title_lbl.setProperty("role", "muted")
        trlay.addWidget(self.title_lbl)

        self.title_entry = QLineEdit(self.title_row)
        self.title_entry.setPlaceholderText(t("Stream title…"))
        self.title_entry.setEnabled(False)
        self.title_entry.textChanged.connect(self._on_title_edited)
        trlay.addWidget(self.title_entry, 1)

        self.reset_title_btn = QPushButton(t("Reset"), self.title_row)
        self.reset_title_btn.setProperty("variant", "ghost")
        self.reset_title_btn.setToolTip(t("Reset to original Twitch title"))
        self.reset_title_btn.setEnabled(False)
        self.reset_title_btn.clicked.connect(self.reset_title)
        trlay.addWidget(self.reset_title_btn)

        self.cuts_card.add_widget(self.title_row)

        self.cuts = QPlainTextEdit()
        self.cuts.setObjectName("cutPoints")
        font = mono_font()
        font.setPointSize(11)
        self.cuts.setFont(font)
        self.cuts.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.cuts.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.cuts.setTabChangesFocus(True)  # Tab moves to the next control instead of typing a tab character
        line_h = self.cuts.fontMetrics().lineSpacing()
        self.cuts.setFixedHeight(3 * line_h + 18)  # tkinter: height=3 lines
        self.cuts.textChanged.connect(self.update_preview)
        self.cuts_card.add_widget(self.cuts)

        self.cuts_hint = WrapLabel(t(CUT_HINT))
        self.cuts_hint.setProperty("role", "muted")
        self.cuts_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.cuts_hint.setContentsMargins(0, 6, 0, 8)
        self.cuts_card.add_widget(self.cuts_hint)

        # D3: Strategy segmented control + coverage bar
        self.strategy_row = QWidget()
        self.strategy_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        srlay = QHBoxLayout(self.strategy_row)
        srlay.setContentsMargins(0, 0, 0, 6)
        srlay.setSpacing(6)
        self.strat_lbl = QLabel(t("Strategy:"))
        self.strat_lbl.setProperty("role", "muted")
        srlay.addWidget(self.strat_lbl)

        self.strategy_bar = QFrame(self.strategy_row)
        self.strategy_bar.setObjectName("strategySegmented")
        sblay = QHBoxLayout(self.strategy_bar)
        sblay.setContentsMargins(0, 0, 0, 0)
        sblay.setSpacing(4)
        self.strategy_buttons: dict[str, QPushButton] = {}
        for key, label, _setting in STRATEGY_CHOICES:
            btn = QPushButton(t(label), self.strategy_bar)
            btn.setProperty("variant", "chip")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self.set_strategy(k))
            sblay.addWidget(btn)
            self.strategy_buttons[key] = btn
        srlay.addWidget(self.strategy_bar)
        srlay.addStretch(1)

        self.coverage_badge = QLabel("")
        self.coverage_badge.setProperty("role", "muted")
        srlay.addWidget(self.coverage_badge)
        self.cuts_card.add_widget(self.strategy_row)

        # Quality row (hidden until a VOD with formats is loaded)
        self.quality_row = QWidget()
        self.quality_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        qrlay = QHBoxLayout(self.quality_row)
        qrlay.setContentsMargins(0, 0, 0, 6)
        qrlay.setSpacing(6)
        self.qual_lbl = QLabel(t("Quality:"))
        self.qual_lbl.setProperty("role", "muted")
        qrlay.addWidget(self.qual_lbl)
        self.quality_combo = ComboBox(self.quality_row)
        self.quality_combo.activated.connect(self._on_quality_activated)
        qrlay.addWidget(self.quality_combo)
        qrlay.addStretch(1)
        self.quality_note = QLabel("")
        self.quality_note.setProperty("role", "muted")
        qrlay.addWidget(self.quality_note)
        self.quality_row.setVisible(False)
        self.cuts_card.add_widget(self.quality_row)

        self.coverage_bar = QProgressBar()
        self.coverage_bar.setObjectName("coverageBar")
        self.coverage_bar.setRange(0, 100)
        self.coverage_bar.setValue(0)
        self.coverage_bar.setTextVisible(False)
        self.coverage_bar.setFixedHeight(6)
        self.coverage_bar.setVisible(False)
        self.cuts_card.add_widget(self.coverage_bar)

        # D2: Visual part cards container
        self.part_cards_box = QWidget()
        self.part_cards_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.part_cards_layout = QVBoxLayout(self.part_cards_box)
        self.part_cards_layout.setContentsMargins(0, 6, 0, 6)
        self.part_cards_layout.setSpacing(4)
        self.part_cards_box.setVisible(False)
        self.cuts_card.add_widget(self.part_cards_box)

        self.preview = QPlainTextEdit()
        self.preview.setObjectName("planPreview")
        self.preview.setReadOnly(True)
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.preview.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.preview.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.preview.setFixedHeight(4 * self.preview.fontMetrics().lineSpacing() + 12)  # tkinter: height=4 lines
        self._preview_formats: dict[str, QTextCharFormat] = {}
        for kind, colour in PREVIEW_COLOURS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            self._preview_formats[kind] = fmt
        self.cuts_card.add_widget(self.preview)

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
        for col, (_key, _text, width, _anchor, stretch) in enumerate(CLIP_COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            head.resizeSection(col, width)
        self.tree.installEventFilter(self)
        self._adjust_clip_columns()
        self.tree.setMinimumHeight(HEADER_HEIGHT + 6 * ROW_HEIGHT + 2)  # tkinter: height=6 rows
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

    def _build_footer(self) -> None:
        self.plan_summary_lbl = QLabel("")
        self.plan_summary_lbl.setProperty("role", "muted")
        self.footer_layout.addWidget(self.plan_summary_lbl, 1)
        self.queue_btn = QPushButton(t("Add to queue"))
        self.queue_btn.setIcon(icon("plus", 16))
        self.queue_btn.clicked.connect(self._on_add_to_queue)
        self.start_btn = QPushButton(t("Add && start"))
        self.start_btn.setIcon(icon("play", 16, "#ffffff"))
        self.start_btn.setProperty("variant", "accent")
        self.start_btn.clicked.connect(self._on_add_and_start)
        self.footer_layout.addWidget(self.queue_btn)
        self.footer_layout.addSpacing(8)
        self.footer_layout.addWidget(self.start_btn)

    def _on_add_to_queue(self) -> None:
        self.add_requested.emit(False)

    def _on_add_and_start(self) -> None:
        self.add_requested.emit(True)

    def _on_filter_spin(self, _value: int) -> None:
        if not self.binder._loading:
            self.refresh_clips()

    # ---------------------------- strategy segmented control (D3) ---------------------------- #
    def current_strategy_key(self) -> str:
        raw = str(self.settings.get("strategy", DEFAULTS["strategy"]))
        return _STRATEGY_BY_SETTING.get(raw, "auto")

    def set_strategy(self, mode: str) -> None:
        """Set strategy by key (``auto`` | ``full`` | ``sections``), label, or setting name."""
        key_clean = mode.strip().lower()
        setting_val = _SETTING_BY_STRATEGY.get(mode) or _SETTING_BY_STRATEGY.get(key_clean)
        if setting_val is None:
            return
        self.settings["strategy"] = setting_val
        self._sync_strategy_buttons()
        self.update_preview()
        self.strategy_changed.emit(setting_val)

    def _sync_strategy_buttons(self, resolved_strategy: str | None = None) -> None:
        active_key = self.current_strategy_key()
        for key, btn in self.strategy_buttons.items():
            selected = key == active_key
            btn.setChecked(selected)
            btn.setProperty("selected", "true" if selected else "false")
            if selected:
                btn.setStyleSheet(
                    f"background-color: {ACCENT}; color: #ffffff; font-weight: bold; "
                    f"padding: 3px 10px; border-radius: 10px;"
                )
            elif active_key == "auto" and resolved_strategy == key:
                btn.setStyleSheet(
                    f"background-color: {ACCENT_DIM}; color: {ACCENT_TEXT}; border: 1px solid {ACCENT}; "
                    f"padding: 3px 10px; border-radius: 10px;"
                )
            else:
                btn.setStyleSheet("")
            _polish(btn)

    # ---------------------------- part cards (D2) ---------------------------- #
    def _dominant_game_for_span(self, start: float, end: float) -> tuple[str, str]:
        segments = getattr(self.source, "segments", None) if self.source is not None else None
        if not segments:
            return "", ACCENT
        best_title = ""
        best_overlap = 0.0
        for seg in segments:
            ov = max(0.0, min(end, seg.end) - max(start, seg.start))
            if ov > best_overlap and getattr(seg, "title", ""):
                best_overlap = ov
                best_title = seg.title
        if best_title:
            return best_title, game_colour(best_title)
        return "", ACCENT

    def _clear_part_cards(self) -> None:
        for card in self.part_cards:
            self.part_cards_layout.removeWidget(card)
            card.deleteLater()
        self.part_cards.clear()

    def _rebuild_part_cards(self, plan) -> None:
        self._clear_part_cards()
        self.last_plan = plan
        if plan is None or not plan.parts:
            self.part_cards_box.setVisible(False)
            self.coverage_bar.setVisible(False)
            self.coverage_badge.setText("")
            return

        muted = self.source.muted if self.source else None
        for p in plan.parts:
            m_sec = muted_overlap(muted, p.start, p.end)
            g_name, g_col = self._dominant_game_for_span(p.start, p.end)
            card = PartCard(
                part_index=p.index,
                start=p.start,
                end=p.end,
                duration=p.duration,
                muted_seconds=m_sec,
                game_name=g_name,
                color=g_col,
                parent=self.part_cards_box,
            )
            card.skip_requested.connect(self.skip_part)
            self.part_cards_layout.addWidget(card)
            self.part_cards.append(card)

        self.part_cards_box.setVisible(True)
        if plan.duration:
            pct = int(round(plan.coverage * 100))
            from qt_ui.motion import DURATION_FAST, Motion, animate_value
            if Motion.enabled() and self.isVisible():
                animate_value(
                    self.coverage_bar,
                    start_val=float(self.coverage_bar.value()),
                    end_val=float(pct),
                    duration_ms=DURATION_FAST,
                    on_update=lambda v: self.coverage_bar.setValue(int(round(v))),
                )
            else:
                self.coverage_bar.setValue(min(max(pct, 0), 100))
            self.coverage_bar.setVisible(True)
            full_cov = plan.coverage >= 0.995
            self.coverage_badge.setText(t("100% of VOD") if full_cov else t("{pct}% of VOD", pct=pct))
            self.coverage_badge.setStyleSheet(
                f"color: {OK}; font-weight: bold;" if full_cov else f"color: {MUTED};"
            )
        else:
            self.coverage_bar.setVisible(False)
            self.coverage_badge.setText("")

    def skip_part(self, part_index: int) -> None:
        """Skip/remove a part card by index, updating the cut text and timeline."""
        if self.last_plan is None:
            return
        target = next((p for p in self.last_plan.parts if p.index == part_index), None)
        if target is None:
            return
        dur = self.source.duration if self.source else None
        try:
            current_ranges = ranges_of(self.cut_text(), dur)
        except EngineError:
            return
        mid = (target.start + target.end) / 2.0
        new_ranges = toggle_part(current_ranges, mid, dur or target.end)
        self.on_timeline_edit(new_ranges)

    # ---------------------------- cut points & preview ---------------------------- #
    def cut_text(self) -> str:
        return self.cuts.toPlainText().strip()

    def set_title(self, title: str, raw_title: str | None = None) -> None:
        if raw_title is not None:
            self._raw_title = raw_title
        elif not getattr(self, "_raw_title", ""):
            self._raw_title = title
        has_val = bool(title or self._raw_title)
        self.title_entry.setEnabled(has_val)
        self.reset_title_btn.setEnabled(has_val)
        self.title_entry.blockSignals(True)
        self.title_entry.setText(title)
        self.title_entry.blockSignals(False)
        if hasattr(self, "generic_title_entry"):
            self.generic_title_entry.setEnabled(has_val)
            self.generic_reset_title_btn.setEnabled(has_val)
            self.generic_title_entry.blockSignals(True)
            self.generic_title_entry.setText(title)
            self.generic_title_entry.blockSignals(False)

    def _on_title_edited(self, text: str) -> None:
        clean = text.strip()
        if self.source:
            self.source.title = clean
        self.title_changed.emit(clean)

    def reset_title(self) -> None:
        raw = getattr(self, "_raw_title", "")
        if not raw:
            return
        if flag(self.settings, "clean_title"):
            new_title = clean_title(raw)
        else:
            new_title = raw
        self.set_title(new_title)
        if self.source:
            self.source.title = new_title
        self.title_changed.emit(new_title)

    def set_cut_text(self, text: str) -> None:
        """Replace the cut points box without firing ``update_preview`` twice when callers follow with their own call."""
        self.cuts.blockSignals(True)
        try:
            self.cuts.setPlainText(text)
        finally:
            self.cuts.blockSignals(False)

    def set_formats(self, formats: list, default_setting: str) -> None:
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        if hasattr(self, "generic_quality_combo"):
            self.generic_quality_combo.blockSignals(True)
            self.generic_quality_combo.clear()
        if not formats:
            self.quality_combo.blockSignals(False)
            if hasattr(self, "generic_quality_combo"):
                self.generic_quality_combo.blockSignals(False)
            self.quality_row.setVisible(False)
            return

        best = resolve_format(formats, QUALITY_BEST)
        best_label = best.label if best else "best"
        self.quality_combo.addItem(t("Best available ({quality})", quality=best_label), QUALITY_BEST)
        if hasattr(self, "generic_quality_combo"):
            self.generic_quality_combo.addItem(t("Best available ({quality})", quality=best_label), QUALITY_BEST)
        for fmt in formats:
            self.quality_combo.addItem(fmt.label, fmt.format_id)
            if hasattr(self, "generic_quality_combo"):
                self.generic_quality_combo.addItem(fmt.label, fmt.format_id)

        wanted = QUALITY_CHOICES.get(default_setting, "best")
        if wanted == "best":
            self.quality_combo.setCurrentIndex(0)
            if hasattr(self, "generic_quality_combo"):
                self.generic_quality_combo.setCurrentIndex(0)
        else:
            chosen = resolve_format(formats, wanted)
            idx = 0
            if chosen:
                for i in range(self.quality_combo.count()):
                    if self.quality_combo.itemData(i) == chosen.format_id:
                        idx = i
                        break
            self.quality_combo.setCurrentIndex(idx)
            if hasattr(self, "generic_quality_combo"):
                self.generic_quality_combo.setCurrentIndex(idx)

        self.quality_combo.blockSignals(False)
        if hasattr(self, "generic_quality_combo"):
            self.generic_quality_combo.blockSignals(False)
        self.quality_row.setVisible(True)
        self.update_preview()

    def current_quality(self) -> str:
        if not getattr(self, "mode_timeline", True):
            if hasattr(self, "generic_quality_combo") and self.generic_quality_combo.count() > 0:
                data = self.generic_quality_combo.currentData()
                return str(data) if data is not None else QUALITY_BEST
            return QUALITY_BEST
        if self.quality_combo.count() > 0:
            data = self.quality_combo.currentData()
            return str(data) if data is not None else QUALITY_BEST
        return QUALITY_BEST

    def _on_quality_activated(self, _index: int = 0) -> None:
        self.update_preview()
        self.quality_changed.emit(self.current_quality())

    def build_options(self):
        return build_options(self.settings, self.cut_text(), quality=self.current_quality())

    def build_filter(self):
        return build_filter(self.settings)

    def set_preview(self, text: str, kind: str, summary: str = "") -> None:
        """``kind``: ok | err | muted. ``summary`` is the short line in the bar at the bottom of the tab."""
        self.preview_kind = kind
        self.plan_summary_lbl.setText(summary)
        role = "err" if kind == "err" else "muted"
        if self.plan_summary_lbl.property("role") != role:
            self.plan_summary_lbl.setProperty("role", role)
            _polish(self.plan_summary_lbl)
        self.preview.clear()
        cursor = QTextCursor(self.preview.document())
        cursor.insertText(text, self._preview_formats[kind])

    def preview_text(self) -> str:
        return self.preview.toPlainText().rstrip("\n")

    def update_preview(self) -> None:
        self._render_preview()
        if getattr(self, "mode_timeline", True):
            self.sync_timeline()

    def _render_preview(self) -> None:
        if not getattr(self, "mode_timeline", True):
            dur_str = fmt_hms(self.source.duration) if self.source else "0:00:00"
            audio = " (Audio only)" if self.is_audio_only() else ""
            summary_str = f"1 video \u00b7 {dur_str}{audio}"
            qual = self.current_quality()
            cont = self.current_container()
            lines = [
                f"Full video download ({dur_str})",
                f"Quality: {qual} \u00b7 Container: {cont}{audio}",
            ]
            self.set_preview("\n".join(lines), "ok", summary_str)
            self.plan_summary_lbl.setToolTip(summary_str)
            return
        text = self.cut_text()
        if not text:
            self._sync_strategy_buttons()
            self._rebuild_part_cards(None)
            self.set_preview(t("Write the cut points above (press «Get info» first so «end» works)."), "muted")
            self.plan_summary_lbl.setToolTip(t("Paste a VOD and press «Get info» first."))
            return
        dur = self.source.duration if self.source else None
        opts = self.build_options()
        try:
            plan = make_plan(text, dur, opts.strategy, opts.full_threshold)
        except EngineError as e:
            self._sync_strategy_buttons()
            self._rebuild_part_cards(None)
            self.set_preview(f"\u26a0 {e}", "err", t("Fix the cut points to add this VOD"))
            self.plan_summary_lbl.setToolTip(str(e))
            return
        self._sync_strategy_buttons(resolved_strategy=plan.strategy)
        self._rebuild_part_cards(plan)
        muted = self.source.muted if self.source else None

        def muted_note(a: float, b: float) -> str:
            m = muted_overlap(muted, a, b)
            return t("   ·  {time} muted", time=fmt_hms(m)) if m >= 1 else ""

        lines = [
            t("Part {n}:  {start} → {end}   ({duration}){silenced}",
              n=p.index, start=fmt_hms(p.start), end=fmt_hms(p.end), duration=fmt_hms(p.duration),
              silenced=muted_note(p.start, p.end))
            for p in plan.parts
        ]
        if plan.duration:
            how = (t("download the full VOD once, then split it") if plan.strategy == "full"
                   else t("download only these parts"))
            lines.append(t("→ {how}   (parts cover {pct}% of the VOD)",
                           how=how, pct=int(round(plan.coverage * 100))))
        if self.source and getattr(self.source, "formats", None):
            fmt = resolve_format(self.source.formats, self.current_quality())
            if fmt:
                if fmt.audio_only:
                    lines.append(t("Quality: {quality} · Audio only: saved as .m4a or .mp3 (Options). Video-only extras are skipped.", quality=fmt.label))
                else:
                    dl_secs = self.source.duration if plan.strategy == "full" else sum(p.duration for p in plan.parts)
                    est = estimate_bytes(fmt, dl_secs or 0)
                    size_str = t(" · about {size}", size=human_size(est)) if est > 0 else ""
                    lines.append(t("Quality: {quality}{size}", quality=fmt.label, size=size_str))
        n = len(plan.parts)
        total_muted = sum(muted_overlap(muted, p.start, p.end) for p in plan.parts)
        parts_count = tn("{n} part", "{n} parts", n)
        summary_str = (
            t("{count} · {duration} in total", count=parts_count, duration=fmt_hms(sum(p.duration for p in plan.parts)))
            + (t(" · {time} muted", time=fmt_hms(total_muted)) if total_muted >= 1 else "")
        )
        self.set_preview("\n".join(lines), "ok", summary_str)
        if plan.duration:
            strat_desc = t("Full VOD + split") if plan.strategy == "full" else t("Only the parts")
            self.plan_summary_lbl.setToolTip(
                t("{summary} · {mode} ({pct}% of VOD covered)",
                  summary=summary_str, mode=strat_desc, pct=int(round(plan.coverage * 100)))
            )
        else:
            self.plan_summary_lbl.setToolTip(summary_str)

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

    # ---------------------------- downloading selected clips ---------------------------- #
    clip_download_requested = Signal()

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
        from qt_ui.motion import DURATION_NORMAL, Motion, animate_height, QWIDGETSIZE_MAX
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
                        on_finished=lambda: (self.onboarding_card.setVisible(False), self.onboarding_card.setMaximumHeight(QWIDGETSIZE_MAX)),
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
        if timeline_module.Image is None:
            self.timeline.set_frames(None)
            return
        self.frames_runner.start(src)

    def on_frames(self, src, frames) -> None:
        if src is self.source:
            self.timeline.set_frames(frames)

    def refresh_language(self) -> None:
        """Update PlanTab text labels dynamically when language changes."""
        if hasattr(self, "timeline_card") and self.timeline_card.title_label:
            self.timeline_card.title_label.setText(t("Timeline"))
        if hasattr(self, "cuts_card") and self.cuts_card.title_label:
            self.cuts_card.title_label.setText(t("Cut points"))
        if hasattr(self, "clips_card"):
            if self.clips_card.title_label:
                self.clips_card.title_label.setText(t("Clips → chapters"))
            if self.clips_card.subtitle_label:
                self.clips_card.subtitle_label.setText(t("Optional: put the VOD's clips in the files as chapters."))
        if hasattr(self, "onboarding_steps"):
            self.onboarding_steps.setText(t("1. Paste a link or search a streamer   ·   2. Mark where to cut   ·   3. Add to queue"))
        if hasattr(self, "onboard_search_btn"):
            self.onboard_search_btn.setText(t("Search streamers"))
        if hasattr(self, "onboard_paste_btn"):
            self.onboard_paste_btn.setText(t("Paste from clipboard"))
        if hasattr(self, "title_lbl"):
            self.title_lbl.setText(t("Title:"))
        if hasattr(self, "title_entry"):
            self.title_entry.setPlaceholderText(t("Stream title…"))
        if hasattr(self, "reset_title_btn"):
            self.reset_title_btn.setText(t("Reset"))
            self.reset_title_btn.setToolTip(t("Reset to original Twitch title"))
        if hasattr(self, "cuts_hint"):
            self.cuts_hint.setText(t(CUT_HINT))
        if hasattr(self, "strat_lbl"):
            self.strat_lbl.setText(t("Strategy:"))
        for key, label, _setting in STRATEGY_CHOICES:
            if key in self.strategy_buttons:
                self.strategy_buttons[key].setText(t(label))
        if hasattr(self, "qual_lbl"):
            self.qual_lbl.setText(t("Quality:"))
        if hasattr(self, "quality_combo") and self.quality_combo.count() > 0:
            best = resolve_format(self.source.formats, QUALITY_BEST) if self.source and getattr(self.source, "formats", None) else None
            best_label = best.label if best else "best"
            self.quality_combo.setItemText(0, t("Best available ({quality})", quality=best_label))
        if hasattr(self, "chapters_row"):
            if self.chapters_row.title_label:
                self.chapters_row.title_label.setText(t("Add clips as chapters"))
            if self.chapters_row.hint_label:
                self.chapters_row.hint_label.setText(t("Each clip that passes the filter becomes a chapter."))
            if getattr(self.chapters_row, "info", None):
                info_txt = t("Needs the Twitch API sign-in (the «Twitch API…» button). Chapters are written into the video files; the Premiere Pro outputs (Options → Premiere Pro) have their own switches.")
                self.chapters_row.info.text = info_txt
                self.chapters_row.info.setAccessibleDescription(info_txt)
                if hasattr(self.chapters_row.info, "tooltip") and self.chapters_row.info.tooltip:
                    self.chapters_row.info.tooltip.text = info_txt
        filter_titles = {
            "min_views": t("Min views"),
            "min_duration": t("Min duration (s)"),
            "top_n": t("Top N (0 = all)"),
            "pad_before": t("Lead-in (s)"),
        }
        for name, lbl in getattr(self, "filter_labels", {}).items():
            if name in filter_titles:
                lbl.setText(filter_titles[name])
        if hasattr(self, "sel_lbl"):
            self.sel_lbl.setText(t("Selection:"))
        if hasattr(self, "select_all_clips_btn"):
            self.select_all_clips_btn.setText(t("Select all"))
        if hasattr(self, "invert_clips_btn"):
            self.invert_clips_btn.setText(t("Invert"))
        if hasattr(self, "clear_clips_btn"):
            self.clear_clips_btn.setText(t("Clear"))
        if hasattr(self, "split_btn"):
            self.split_btn.setText(t("Split at selected clip"))
        self._update_clip_action_buttons()
        if hasattr(self, "clip_model"):
            self.clip_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(CLIP_COLUMNS) - 1)
        if hasattr(self, "queue_btn"):
            self.queue_btn.setText(t("Add to queue"))
        if hasattr(self, "start_btn"):
            self.start_btn.setText(t("Add && start"))
        self.update_preview()
        self.refresh_clips()
