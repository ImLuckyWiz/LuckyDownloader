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

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.i18n import t
from luckytwitch_engine import QUALITY_BEST, resolve_format
from qt_ui import dialogs, i18n_qt
from qt_ui import timeline as timeline_module
from qt_ui.background_jobs import FramesRunner
from qt_ui.binder import SettingsBinder
from qt_ui.bridge import Bridge
from qt_ui.icons import icon
from qt_ui.tabs.plan_crop_controls import (
    CUT_HINT,
    PREVIEW_COLOURS,
    STRATEGY_CHOICES,
    PartCard,
    PlanCropControlsMixin,
    _polish,
    _SETTING_BY_STRATEGY,
    _STRATEGY_BY_SETTING,
    human_size,
)
from qt_ui.tabs.plan_playlist_dialog import PlanPlaylistMixin
from qt_ui.tabs.plan_storyboard import (
    CLIP_COLUMNS,
    HEADER_HEIGHT,
    ROW_HEIGHT,
    ClipModel,
    ClipViewsDelegate,
    PlanStoryboardMixin,
    _alignment,
)
from qt_ui.timeline import IDLE_HINT, Timeline
from qt_ui.widgets import Card, ScrollPage, WrapLabel

WIDE_BREAKPOINT = 1100

TimelinePlaceholder = Timeline  # backward-compatible alias

__all__ = [
    "CLIP_COLUMNS",
    "CUT_HINT",
    "ClipModel",
    "ClipViewsDelegate",
    "HEADER_HEIGHT",
    "IDLE_HINT",
    "PREVIEW_COLOURS",
    "PartCard",
    "PlanTab",
    "ROW_HEIGHT",
    "STRATEGY_CHOICES",
    "TimelinePlaceholder",
    "WIDE_BREAKPOINT",
    "dialogs",
    "human_size",
    "timeline_module",
]


class PlanTab(PlanPlaylistMixin, PlanCropControlsMixin, PlanStoryboardMixin, ScrollPage):
    add_requested = Signal(bool)  # False = «Add to queue», True = «Add & start»
    search_requested = Signal()
    paste_requested = Signal()
    strategy_changed = Signal(str)
    title_changed = Signal(str)
    quality_changed = Signal(str)
    generic_thumb_loaded = Signal(str)
    clip_download_requested = Signal()

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

    def refresh_language(self) -> None:
        """Update PlanTab text labels dynamically when language changes."""
        if hasattr(self, "timeline_card") and self.timeline_card.title_label:
            self.timeline_card.title_label.setText(t("Timeline"))
        if hasattr(self, "retranslate_generic_card"):
            self.retranslate_generic_card()
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
            if not getattr(self, "mode_timeline", True):
                self.cuts_hint.setText(
                    t("Optional: write cut points to trim or split (e.g. 1:00 - 5:00 ; 12:00 - end). Leave blank for full video.")
                )
            else:
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
