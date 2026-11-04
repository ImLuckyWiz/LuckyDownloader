"""Cut points card, strategy segmented control, part cards, and live preview for PlanTab."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from core.i18n import N_, t, tn
from core.options import QUALITY_CHOICES, build_filter, build_options, flag
from core.palette import ACCENT, ACCENT_DIM, ACCENT_TEXT, BG, BORDER, ERR, MUTED, OK, WARN
from core.settings import DEFAULTS
from core.timeline import game_colour
from luckytwitch_engine import (
    QUALITY_BEST, EngineError, clean_title, estimate_bytes, fmt_hms, make_plan, muted_overlap, ranges_of,
    resolve_format, toggle_part,
)
from qt_ui import i18n_qt
from qt_ui.icons import icon
from qt_ui.theme import mono_font
from qt_ui.widgets import Card, ComboBox, MarqueeLabel, WrapLabel

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


def _polish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


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


class PlanCropControlsMixin:
    """Mixin for PlanTab managing the cut points card, strategy chips, part cards, and preview."""

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
        self.cuts.setTabChangesFocus(True)
        line_h = self.cuts.fontMetrics().lineSpacing()
        self.cuts.setFixedHeight(3 * line_h + 18)
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
        self.preview.setFixedHeight(4 * self.preview.fontMetrics().lineSpacing() + 12)
        self._preview_formats: dict[str, QTextCharFormat] = {}
        for kind, colour in PREVIEW_COLOURS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            self._preview_formats[kind] = fmt
        self.cuts_card.add_widget(self.preview)

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
            qual = self.current_quality()
            cont = self.current_container()
            text = self.cut_text()
            if not text:
                self._sync_strategy_buttons()
                self._rebuild_part_cards(None)
                summary_str = f"1 video \u00b7 {dur_str}{audio}"
                lines = [
                    f"Full video download ({dur_str})",
                    f"Quality: {qual} \u00b7 Container: {cont}{audio}",
                    t("Leave cut points blank to download the full video, or enter cut points above to trim."),
                ]
                self.set_preview("\n".join(lines), "ok", summary_str)
                self.plan_summary_lbl.setToolTip(summary_str)
                return
            dur = self.source.duration if self.source else None
            opts = self.build_options()
            try:
                plan = make_plan(text, dur, opts.strategy, opts.full_threshold)
            except EngineError as e:
                self._sync_strategy_buttons()
                self._rebuild_part_cards(None)
                self.set_preview(f"\u26a0 {e}", "err", t("Fix the cut points to add this video"))
                self.plan_summary_lbl.setToolTip(str(e))
                return
            self._sync_strategy_buttons(resolved_strategy=plan.strategy)
            self._rebuild_part_cards(plan)
            lines = [
                t("Part {n}:  {start} → {end}   ({duration})",
                  n=p.index, start=fmt_hms(p.start), end=fmt_hms(p.end), duration=fmt_hms(p.duration))
                for p in plan.parts
            ]
            if plan.duration:
                how = (t("download the full video once, then split it") if plan.strategy == "full"
                       else t("download only these parts"))
                lines.append(t("→ {how}   (parts cover {pct}% of the video)",
                               how=how, pct=int(round(plan.coverage * 100))))
            lines.append(f"Quality: {qual} \u00b7 Container: {cont}{audio}")
            n = len(plan.parts)
            parts_count = tn("{n} part", "{n} parts", n)
            summary_str = (
                t("{count} · {duration} in total", count=parts_count, duration=fmt_hms(sum(p.duration for p in plan.parts)))
                + audio
            )
            self.set_preview("\n".join(lines), "ok", summary_str)
            if plan.duration:
                strat_desc = t("Full video + split") if plan.strategy == "full" else t("Only the parts")
                self.plan_summary_lbl.setToolTip(
                    t("{summary} · {mode} ({pct}% of video covered)",
                      summary=summary_str, mode=strat_desc, pct=int(round(plan.coverage * 100)))
                )
            else:
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
