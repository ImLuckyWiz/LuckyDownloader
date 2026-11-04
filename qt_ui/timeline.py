"""Timeline (Phase 7, ``qt_ui/timeline.py``): the whole VOD on one strip, to see where the games change and to place
the cuts with the mouse.

Port of ``ui/timeline.py`` (decision D2: custom ``QWidget`` painted with ``QPainter``, reusing ``Viewport``,
``nice_step``, ``game_colour`` and ``zone_at`` from ``core/timeline.py``).

Rows, top to bottom:
    ruler    time marks (green triangles = clips). Drag to move along the VOD.
    games    one bar per game / category the streamer was in. Double-click one to make it its own part
             (Shift + double-click: keep only that game). A thin red line along its bottom edge marks the
             stretches Twitch silenced (muted audio); it can be switched off with the «Show muted» switch.
    thumbs   preview frames of the VOD. Click to cut there, drag a cut line to move it.
    parts    the parts that will be downloaded (purple); skipped sections are dark. Click a part to skip
             it, click a skipped section to bring it back.
Right-click a cut line (between two touching parts) to remove it (on macOS, Ctrl+click also removes a cut line).
Mouse wheel = zoom, Shift + wheel or the scroll bar = move. "Undo" (or Ctrl+Z / Cmd+Z) takes back the last timeline
edit.

The widget knows nothing about the rest of the app. The owner feeds it with ``set_source()`` / ``set_frames()`` /
``set_ranges()`` / ``set_clip_marks()`` / ``set_muted()`` and gets every edit back through ``on_edit(ranges)``; the cut
text is rebuilt from those ranges by the engine.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QScrollBar, QSizePolicy, QVBoxLayout, QWidget

from core.i18n import t, tn
from core.timeline import (
    CUT_COLOUR, EDGE_COLOUR, EDGE_TOL_PX, GAME_COLOURS, GAMES_H, GAP, HEIGHT, IDLE_HINT, MUTED_COLOUR, MUTED_H,
    PADX, PARTS_H, PREVIEW_MAX_W, RULER_H, SNAP_PX, THUMB_H, THUMB_W, Viewport, Y_GAMES, Y_PARTS, Y_RULER,
    Y_THUMBS, build_snap_kinds, build_snap_points, game_colour, nice_step, snap_target, snap_time, y_of, zone_at,
)
from luckytwitch_engine import (
    Edge, GameSegment, Range, Storyboard, add_cut, edges_of, fmt_hms, isolate_span, move_edge, nearest_edge,
    part_index_at, remove_cut, toggle_part,
)
from qt_ui import i18n_qt
from qt_ui.icons import icon
from qt_ui.timeline_painters import (
    FLAG_MIN_PX,
    MINIMAP_H,
    PART_RADIUS,
    SHIMMER_MS,
    SHIMMER_STEP,
    TimelineCanvas,
    TimelineMinimap,
    TimelinePaintersMixin,
    _motion_enabled,
)
from qt_ui.timeline_preview import (
    LEGEND_MAX_CHIPS,
    TimelinePreviewMixin,
    _dot_icon,
    _FlowLayout,
    _LegendChip,
    _pil_to_qpixmap,
    _short_dur,
)
from qt_ui.widgets import Toggle, WrapLabel

try:  # thumbnails are PIL images returned by the engine; everything else works without Pillow
    from PIL import Image, ImageEnhance
except ImportError:  # pragma: no cover - exercised by patching Image = None
    Image = ImageEnhance = None

__all__ = [
    "CUT_COLOUR", "EDGE_COLOUR", "EDGE_TOL_PX", "FLAG_MIN_PX", "GAME_COLOURS", "GAMES_H", "GAP", "HEIGHT",
    "IDLE_HINT", "Image", "ImageEnhance", "LEGEND_MAX_CHIPS", "MINIMAP_H", "MUTED_COLOUR", "MUTED_H", "PADX",
    "PARTS_H", "PART_RADIUS", "PREVIEW_MAX_W", "RULER_H", "SHIMMER_MS", "SHIMMER_STEP", "SNAP_PX", "THUMB_H",
    "THUMB_W", "Timeline", "TimelineCanvas", "TimelineMinimap", "Viewport", "Y_GAMES", "Y_PARTS", "Y_RULER",
    "Y_THUMBS", "_FlowLayout", "_LegendChip", "_dot_icon", "_pil_to_qpixmap", "_short_dur", "game_colour",
    "nice_step", "y_of", "zone_at",
]

SCROLL_SCALE = 10_000
NUDGE_STEP, NUDGE_SHIFT_STEP = 1, 10  # seconds per arrow key press (Shift = 10 s)
# Alt asks for 0.1 s, but cut points are whole seconds in the engine (``move_edge`` rounds), so Alt nudges by the
# smallest step there is: 1 s (MIGRATION_LOG no. 26).
NUDGE_ALT_STEP = 1


class Timeline(TimelinePaintersMixin, TimelinePreviewMixin, QWidget):
    """The full Timeline widget: toolbar, custom-painted strip, horizontal scrollbar, and wrapping hint line."""

    y_of = staticmethod(y_of)

    def __init__(self, on_edit: Callable[[list[Range]], None] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.on_edit = on_edit or (lambda ranges: None)

        # model
        self.duration: float = 0.0
        self.segments: list[GameSegment] = []
        self.storyboard: Storyboard | None = None
        self.frames: list | None = None  # PIL images (None entries = unavailable); None = not loaded yet
        self.frames_state = "none"  # none | loading | ready | failed
        self.ranges: list[Range] | None = None  # None = the cut text is invalid
        self.clip_marks: list[float] = []
        self.clip_details: dict[float, str] = {}  # moment -> "title · creator · N views" (flag tooltips)
        self.muted: list[Range] = []  # stretches Twitch silenced (VOD seconds)
        self.vp = Viewport()
        self._history: list[list[Range]] = []
        self._future: list[list[Range]] = []  # what Redo brings back
        self._drag: Edge | None = None
        self._pan: tuple[float, float] | None = None
        self._selected: tuple[str, int] | None = None  # (kind, index) of the cut line the keyboard acts on
        self._hover_t: float | None = None  # the moment under the mouse (S cuts there)
        self._last_nudge: tuple[tuple[str, int], float] | None = None
        self._highlight_title: str | None = None  # a legend chip is hovered: light that game up
        self._snap_feedback: tuple[float, str] | None = None  # (moment, what it snapped to)
        self._context_menu: QMenu | None = None
        self._pixmaps: dict[tuple[int, bool], QPixmap] = {}
        self._preview_pixmaps: dict[int, QPixmap] = {}
        self._snap_points: list[float] = []
        self._snap_kinds: dict[float, str] = {}
        self._hover_pos: tuple[float, float, bool] | None = None  # (x, y, dragging)
        self._updating_bar = False
        self._redraw_pending = False
        self._shimmer_phase = 0.0
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.timeout.connect(self._flush_redraw)
        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(SHIMMER_MS)
        self._shimmer_timer.timeout.connect(self._on_shimmer)
        self._snap_timer = QTimer(self)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.timeout.connect(self._clear_snap_feedback)

        # scene records from the last paint pass (so tests and inspectors can query drawn texts and rectangles)
        self.drawn_texts: list[str] = []
        self.drawn_muted_rects: list[tuple[float, float, float, float]] = []
        self.drawn_skipped_rects: list[tuple[float, float, float, float]] = []
        self.drawn_flags: list[tuple[float, int]] = []  # (x, how many clips) of each flag / badge in the ruler
        self.drawn_thumb_count: int = 0
        self.drawn_hover_preview: bool = False

        # layout & child widgets
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        self.btn_out = QPushButton()
        self.btn_out.setIcon(icon("minus", 16))
        self.btn_out.setToolTip(t("Zoom out  (−)"))
        self.btn_out.setAccessibleName(t("Zoom out"))
        self.btn_out.clicked.connect(self.zoom_out)
        self.btn_in = QPushButton()
        self.btn_in.setIcon(icon("plus", 16))
        self.btn_in.setToolTip(t("Zoom in  (+)"))
        self.btn_in.setAccessibleName(t("Zoom in"))
        self.btn_in.clicked.connect(self.zoom_in)
        self.btn_fit = QPushButton(t("Fit"))
        self.btn_fit.setIcon(icon("fit", 16))
        self.btn_fit.setToolTip(t("Show the whole VOD  (0)"))
        self.btn_fit.setAccessibleName(t("Fit timeline to window"))
        self.btn_fit.clicked.connect(self.zoom_fit)
        self.btn_undo = QPushButton(t("Undo"))
        self.btn_undo.setIcon(icon("undo", 16))
        self.btn_undo.setToolTip(t("Undo the last edit  (Ctrl+Z)"))
        self.btn_undo.setAccessibleName(t("Undo last cut edit"))
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton(t("Redo"))
        self.btn_redo.setIcon(icon("redo", 16))
        self.btn_redo.setToolTip(t("Redo the edit you took back  (Ctrl+Y)"))
        self.btn_redo.setAccessibleName(t("Redo last undone cut edit"))
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self.redo)
        for b in (self.btn_out, self.btn_in, self.btn_fit):
            bar.addWidget(b)
        bar.addSpacing(4)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_redo)
        bar.addSpacing(6)
        self.zoom_label = QLabel("")
        self.zoom_label.setProperty("role", "muted")
        bar.addWidget(self.zoom_label)

        self.muted_box = QWidget(self)
        mbox = QHBoxLayout(self.muted_box)
        mbox.setContentsMargins(12, 0, 0, 0)
        mbox.setSpacing(6)
        self.muted_title = QLabel(t("Show muted"))
        self.muted_title.setProperty("role", "muted")
        mbox.addWidget(self.muted_title)
        self.muted_switch = Toggle(checked=True)
        self.muted_switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.muted_switch.clicked.connect(self._toggle_muted)
        mbox.addWidget(self.muted_switch)
        self.muted_info = QLabel("")
        self.muted_info.setProperty("role", "muted")
        mbox.addWidget(self.muted_info)
        self.muted_box.hide()
        bar.addWidget(self.muted_box)
        bar.addStretch(1)
        outer.addLayout(bar)

        self.canvas = TimelineCanvas(self)
        self.canvas.setAccessibleName(t("Interactive VOD timeline"))
        self.canvas.setAccessibleDescription(t("Interactive timeline strip for cutting and isolating segments"))
        outer.addWidget(self.canvas)
        i18n_qt.language_bus().changed.connect(self.refresh_language)

        self.minimap = TimelineMinimap(self)
        self.minimap.hide()  # only while zoomed in; it replaces the scroll bar then
        outer.addWidget(self.minimap)

        self.hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self.hbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hbar.setRange(0, 0)
        self.hbar.valueChanged.connect(self._on_hbar_value)
        outer.addWidget(self.hbar)

        self.legend_box = QWidget(self)
        self.legend_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.legend_layout = _FlowLayout(self.legend_box, hspacing=6, vspacing=4)
        self.legend_layout.setContentsMargins(0, 2, 0, 2)
        self.legend_chips: list[_LegendChip] = []
        self.legend_box.hide()
        outer.addWidget(self.legend_box)

        self.hint_label = WrapLabel(IDLE_HINT, self)
        self.hint_label.setProperty("role", "muted")
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self.hint_label)

        for seq in ("Ctrl+Z", "Meta+Z"):
            sc = QShortcut(QKeySequence(seq), self.canvas)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.undo)
        for seq in ("Ctrl+Y", "Ctrl+Shift+Z", "Meta+Shift+Z"):
            sc = QShortcut(QKeySequence(seq), self.canvas)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.redo)

    # ------------------------------------------------------------------ feeding the widget
    @property
    def show_muted_enabled(self) -> bool:
        return self.muted_switch.isChecked()

    def set_show_muted(self, on: bool) -> None:
        self.muted_switch.setChecked(bool(on))
        self._toggle_muted()

    def hint_text(self) -> str:
        return self.hint_label.text()

    def set_source(self, duration: float, segments: Sequence[GameSegment] = (),
                   storyboard: Storyboard | None = None) -> None:
        """A new VOD: forget everything about the previous one."""
        self.duration = float(duration or 0)
        self.segments = list(segments)
        self.storyboard = storyboard
        self.frames = None
        if storyboard is not None and Image is None:
            self.frames_state = "failed"
        else:
            self.frames_state = "loading" if storyboard else "none"
        self.ranges = None
        self.clip_marks = []
        self.clip_details = {}
        self.set_muted(None, redraw=False)
        self._history.clear()
        self._future.clear()
        self._pixmaps.clear()
        self._preview_pixmaps.clear()
        self._drag = self._pan = None
        self._selected = self._hover_t = self._last_nudge = None
        self._highlight_title = None
        self._clear_snap_feedback(redraw=False)
        self._hover_pos = None
        self.vp = Viewport(self.duration or 1.0, self._draw_width())
        self._rebuild_snap_points()
        self._rebuild_legend()
        self._sync_buttons()
        self._sync_shimmer()
        self.hint_label.setText(IDLE_HINT)
        self.invalidate()

    def set_frames(self, frames: list | None) -> None:
        self.frames = frames
        self.frames_state = "ready" if frames and any(f is not None for f in frames) else "failed"
        self._pixmaps.clear()
        self._preview_pixmaps.clear()
        self._sync_shimmer()
        self.invalidate()

    def set_ranges(self, ranges: list[Range] | None) -> None:
        """The parts as the cut text describes them now (None = the text is invalid)."""
        new = None if ranges is None else [(s, e) for s, e in ranges]
        if new == self.ranges:
            return
        self.ranges = new
        self._selected = None
        self.invalidate()

    def set_clip_marks(self, times: Sequence[float], details: dict[float, str] | None = None) -> None:
        """The moments of the VOD's clips (flags in the ruler, snap points). ``details`` maps a moment to the text of
        its tooltip (title, creator, views)."""
        self.clip_marks = sorted(float(t_val) for t_val in times)
        self.clip_details = dict(details or {})
        self._rebuild_snap_points()
        self.invalidate()

    def set_muted(self, ranges: Sequence[Range] | None, redraw: bool = True) -> None:
        """The stretches Twitch silenced (None / empty = none, or not known). Drawn as a red line; cuts snap to them."""
        self.muted = sorted((float(s), float(e)) for s, e in (ranges or []) if e > s)
        if self.muted:
            total = sum(e - s for s, e in self.muted)
            n = len(self.muted)
            stretches_txt = tn("{n} stretch", "{n} stretches", n)
            self.muted_info.setText(t("{stretches} · {duration} silenced by Twitch", stretches=stretches_txt, duration=fmt_hms(total)))
            self.muted_switch.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.muted_box.show()
        else:
            self.muted_info.setText("")
            self.muted_switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.muted_box.hide()
        self._rebuild_snap_points()
        if redraw:
            self.invalidate()

    def _toggle_muted(self, _checked: bool = False) -> None:
        self._rebuild_snap_points()  # hidden stretches are not snapped to either
        self.invalidate()

    def _muted_at(self, t_val: float) -> Range | None:
        return next(((s, e) for s, e in self.muted if s <= t_val < e), None) if self.show_muted_enabled else None

    def _rebuild_snap_points(self) -> None:
        self._snap_points = build_snap_points(
            self.duration, self.segments, self.clip_marks, self.muted, show_muted=self.show_muted_enabled
        )
        self._snap_kinds = build_snap_kinds(
            self.duration, self.segments, self.clip_marks, self.muted, show_muted=self.show_muted_enabled
        )

    # ------------------------------------------------------------------ zoom / scroll / undo
    def zoom_in(self) -> None:
        self._zoom(1.6, self.vp.width / 2)

    def zoom_out(self) -> None:
        self._zoom(1 / 1.6, self.vp.width / 2)

    def zoom_fit(self) -> None:
        self.vp.fit()
        self.invalidate()

    def _zoom(self, factor: float, anchor_x: float) -> None:
        if self.duration:
            self.vp.zoom(factor, anchor_x)
            self.invalidate()

    def _on_hbar_value(self, value: int) -> None:
        if self._updating_bar or not self.duration:
            return
        self.vp.pan_to((value / SCROLL_SCALE) * self.vp.duration)
        self.invalidate()

    def _update_scrollbar(self) -> None:
        self._updating_bar = True
        try:
            if self.duration and self.vp.zoomed:
                page = max(1, round((self.vp.span / self.vp.duration) * SCROLL_SCALE))
                maximum = max(0, SCROLL_SCALE - page)
                val = round((self.vp.start / self.vp.duration) * SCROLL_SCALE)
                self.hbar.setPageStep(page)
                self.hbar.setSingleStep(max(1, page // 10))
                self.hbar.setRange(0, maximum)
                self.hbar.setValue(min(max(val, 0), maximum))
            else:
                self.hbar.setPageStep(SCROLL_SCALE)
                self.hbar.setRange(0, 0)
                self.hbar.setValue(0)
        finally:
            self._updating_bar = False

    def undo(self) -> None:
        if not self._history or self.ranges is None:
            return
        self._future.append(list(self.ranges))
        del self._future[:-100]
        self.ranges = self._history.pop()
        self._selected = self._last_nudge = None
        self._sync_buttons()
        self.invalidate()
        self.on_edit(list(self.ranges))

    def redo(self) -> None:
        """Bring back the edit that ``undo`` took away (any new edit forgets what could be redone)."""
        if not self._future or self.ranges is None:
            return
        self._history.append(list(self.ranges))
        del self._history[:-100]
        self.ranges = self._future.pop()
        self._selected = self._last_nudge = None
        self._sync_buttons()
        self.invalidate()
        self.on_edit(list(self.ranges))

    def _push_history(self) -> None:
        if self.ranges is not None:
            self._history.append(list(self.ranges))
            del self._history[:-100]
            self._future.clear()
            self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.btn_undo.setEnabled(bool(self._history))
        self.btn_redo.setEnabled(bool(self._future))

    def _sync_chrome(self) -> None:
        """The pieces around the strip that follow the zoom: the minimap (instead of the scroll bar) and the readout."""
        if not hasattr(self, "legend_box"):  # still being built
            return
        zoomed = bool(self.duration and self.vp.zoomed)
        self.minimap.setVisible(zoomed)
        self.hbar.setVisible(not zoomed)
        if not self.duration:
            text = ""
        elif zoomed:
            text = f"Showing {fmt_hms(self.vp.span)} of {fmt_hms(self.duration)}"
        else:
            text = f"Showing the whole VOD \u00b7 {fmt_hms(self.duration)}"
        if self.zoom_label.text() != text:
            self.zoom_label.setText(text)
        self.minimap.update()

    # ------------------------------------------------------------------ coordinates
    def _draw_width(self) -> int:
        w = self.canvas.width()
        if w <= 50:
            w = max(self.width(), 400)
        return max(w - 2 * PADX, 1)

    def x_of(self, t_val: float) -> float:
        """Canvas x of the moment ``t``."""
        return PADX + self.vp.t2x(t_val)

    def t_at(self, x: float) -> float:
        return self.vp.x2t(x - PADX)

    def _snap(self, t_val: float) -> int:
        return snap_time(t_val, self._snap_points, self.vp.px_per_sec, SNAP_PX)

    def _snap_with_kind(self, t_val: float) -> tuple[int, str | None]:
        """Like ``_snap`` and also says what the moment snapped to (None: it did not snap)."""
        target = snap_target(t_val, self._snap_points, self.vp.px_per_sec, SNAP_PX)
        if target is None:
            return round(t_val), None
        return round(target), self._snap_kinds.get(target)

    def _set_snap_feedback(self, t_val: float, kind: str | None, ttl_ms: int = 0) -> None:
        """Show the guide line and «snaps to: …» label (E8). ``ttl_ms`` > 0: remove it by itself after that long."""
        self._snap_timer.stop()
        self._snap_feedback = (float(t_val), kind) if kind else None
        if self._snap_feedback is not None and ttl_ms > 0:
            self._snap_timer.start(ttl_ms)
        self.invalidate()

    def _clear_snap_feedback(self, redraw: bool = True) -> None:
        self._snap_timer.stop()
        if self._snap_feedback is not None:
            self._snap_feedback = None
            if redraw:
                self.invalidate()

    def _segment_at(self, t_val: float) -> GameSegment | None:
        return next((g for g in self.segments if g.start <= t_val < g.end), None)

    def _edge_at(self, x: float) -> Edge | None:
        if not self.ranges:
            return None
        return nearest_edge(self.ranges, self.t_at(x), EDGE_TOL_PX / self.vp.px_per_sec)

    # ------------------------------------------------------------------ mouse & interaction
    def _ready(self) -> bool:
        return bool(self.duration)

    def _say(self, text: str) -> None:
        self.hint_label.setText(text)

    def _on_press(self, x: float, y: float, shift: bool = False) -> None:
        self.canvas.setFocus()
        if not self._ready():
            return
        zone = zone_at(y)
        if zone == "ruler":
            self._pan = (x, self.vp.start)
            return
        if self.ranges is None:
            self._say(t("The cut points text has an error: fix it to edit here."))
            return
        edge = self._edge_at(x)
        if edge is not None:
            self._push_history()
            self._drag = edge
            self._selected = (edge.kind, edge.index)
            self.invalidate()
            return
        self._selected = None
        t_pos = self.t_at(x)
        if zone == "thumbs":
            self._cut_at(t_pos)
        elif zone == "parts":
            self._toggle_part_at(t_pos)

    def _toggle_part_at(self, t_pos: float) -> None:
        if self.ranges is None:
            return
        new = toggle_part(self.ranges, t_pos, self.duration)
        if new is None:
            self._say(t("At least one part has to stay."))
            return
        self._push_history()
        self._apply(new)

    def _cut_at(self, t_pos: float, follow: bool = True) -> None:
        """Cut at ``t_pos`` (snapped). ``follow``: the new line sticks to the mouse while the button is down."""
        assert self.ranges is not None
        t_pos, kind = self._snap_with_kind(t_pos)
        new = add_cut(self.ranges, t_pos)
        if new is None:
            if part_index_at(self.ranges, t_pos) is None:
                self._say(t("That section is skipped: click it in the parts row to keep it again."))
            else:
                self._say(t("There is already a cut line there."))
            return
        self._push_history()
        self._apply(new)
        added = next((e for e in edges_of(new) if e.kind == "cut" and e.t == t_pos), None)
        self._selected = (added.kind, added.index) if added is not None else None
        if follow:
            self._drag = added  # the new line follows the mouse while the button is down
        self._set_snap_feedback(t_pos, kind, ttl_ms=0 if follow else 1500)

    def _on_double(self, x: float, y: float, shift: bool = False) -> None:
        if not self._ready() or zone_at(y) != "games":
            self._on_press(x, y, shift=shift)
            return
        if self.ranges is None:
            self._say(t("The cut points text has an error: fix it to edit here."))
            return
        self.isolate_game_at(self.t_at(x), only=shift)

    def isolate_game_at(self, t_val: float, only: bool = False) -> None:
        """The game stretch at ``t`` becomes its own part (``only``: keep just that stretch)."""
        if self.ranges is None:
            return
        seg = self._segment_at(t_val)
        if seg is None:
            return
        new = isolate_span(self.ranges, seg.start, seg.end, self.duration, only=only)
        if new != self.ranges:
            self._push_history()
            self._apply(new)

    def _on_motion(self, x: float, y: float) -> None:
        if self._pan is not None:
            x0, start0 = self._pan
            self.vp.pan_to(start0 - (x - x0) / self.vp.px_per_sec)
            self.invalidate()
        elif self._drag is not None and self.ranges is not None:
            t_cur, kind = self._snap_with_kind(self.t_at(x))
            new = move_edge(self.ranges, self._drag, t_cur, self.duration)
            if new != self.ranges:
                moved = next((e for e in edges_of(new) if e.kind == self._drag.kind and e.index == self._drag.index), None)
                self._apply(new)
                if moved is not None:
                    self._drag = moved
                    self._selected = (moved.kind, moved.index)
            self._snap_feedback = (float(t_cur), kind) if kind else None
            self._hover_pos = (x, y, True)
            self.invalidate()

    def _on_release(self) -> None:
        self._drag = None
        self._pan = None
        self._hover_pos = None
        self._clear_snap_feedback(redraw=False)
        self.invalidate()

    def _on_right(self, x: float, y: float, global_pos: QPoint | None = None) -> None:
        if not self._ready() or self.ranges is None or zone_at(y) == "ruler":
            return
        edge = self._edge_at(x)
        if edge is None:
            self._show_context_menu(self.t_at(x), global_pos)
            return
        if edge.kind != "cut":
            self._say(t("Only a cut line between two parts can be removed (click the part to skip it instead)."))
            return
        self._push_history()
        self._selected = None
        self._apply(remove_cut(self.ranges, edge.index))

    # ------------------------------------------------------------------ right-click menu (E7)
    def _build_context_menu(self, at_time: float) -> QMenu:
        """The menu for a right-click on empty timeline at moment ``at_time`` (a cut line keeps removing itself instead)."""
        at_time = max(0.0, min(at_time, float(self.duration)))
        menu = QMenu(self.canvas)
        menu.setObjectName("timelineMenu")
        ranges = self.ranges
        editable = ranges is not None
        snapped = self._snap(at_time)
        can_cut = editable and add_cut(ranges, snapped) is not None
        act = menu.addAction(icon("scissors", 16), t("Cut here  ({time})", time=fmt_hms(snapped)))
        act.setEnabled(can_cut)
        act.triggered.connect(lambda _=False, at=at_time: self._cut_at(at, follow=False))
        kept = editable and part_index_at(ranges, at_time) is not None
        act = menu.addAction(icon("x" if kept else "plus", 16), t("Skip this part") if kept else t("Keep this section"))
        act.setEnabled(editable and (not kept or len(ranges) > 1))
        act.triggered.connect(lambda _=False, at=at_time: self._toggle_part_at(at))
        seg = self._segment_at(at_time)
        name = f" ({seg.title})" if seg and seg.title else ""
        act = menu.addAction(icon("flag", 16), t("Isolate this game{name}", name=name))
        act.setEnabled(editable and seg is not None)
        act.triggered.connect(lambda _=False, at=at_time: self.isolate_game_at(at))
        menu.addSeparator()
        act = menu.addAction(icon("undo", 16), t("Undo"))
        act.setEnabled(bool(self._history))
        act.triggered.connect(self.undo)
        act = menu.addAction(icon("redo", 16), t("Redo"))
        act.setEnabled(bool(self._future))
        act.triggered.connect(self.redo)
        return menu

    def _show_context_menu(self, t_val: float, global_pos: QPoint | None) -> None:
        if self._context_menu is not None:
            self._context_menu.close()
            self._context_menu.deleteLater()
        self._context_menu = self._build_context_menu(t_val)
        if global_pos is not None:
            self._context_menu.popup(global_pos)  # popup, not exec: it must never block

    # ------------------------------------------------------------------ keyboard (E2)
    def _edge_target(self) -> Edge | None:
        """The cut line the keyboard acts on: the selected one, else the one nearest the mouse."""
        if not self.ranges:
            return None
        if self._selected is not None:
            found = next((e for e in edges_of(self.ranges) if (e.kind, e.index) == self._selected), None)
            if found is not None:
                return found
            self._selected = None
        if self._hover_t is None:
            return None
        return nearest_edge(self.ranges, self._hover_t, 40 / self.vp.px_per_sec)

    def _on_key(self, event) -> bool:
        """S cut at the mouse · Delete remove the cut · arrows nudge it · Home/End · +/-/0 zoom. Ctrl combos are
        shortcuts (undo / redo), not handled here. True = the key was used."""
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        if not self._ready():
            return False
        key = event.key()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        K = Qt.Key
        if key == K.Key_S:
            self.cut_at_hover()
        elif key in (K.Key_Delete, K.Key_Backspace):
            self.remove_selected_cut()
        elif key in (K.Key_Left, K.Key_Right):
            step = NUDGE_ALT_STEP if alt else (NUDGE_SHIFT_STEP if shift else NUDGE_STEP)
            self.nudge_edge(-1 if key == K.Key_Left else 1, step)
        elif key == K.Key_Home:
            self.vp.pan_to(0)
            self.invalidate()
        elif key == K.Key_End:
            self.vp.pan_to(self.duration - self.vp.span)
            self.invalidate()
        elif key in (K.Key_Plus, K.Key_Equal):
            self.zoom_in()
        elif key in (K.Key_Minus, K.Key_Underscore):
            self.zoom_out()
        elif key == K.Key_0:
            self.zoom_fit()
        else:
            return False
        return True

    def cut_at_hover(self) -> None:
        if self.ranges is None:
            self._say(t("The cut points text has an error: fix it to edit here."))
        elif self._hover_t is None:
            self._say(t("Move the mouse over the timeline first, then press S to cut there."))
        else:
            self._cut_at(self._hover_t, follow=False)

    def remove_selected_cut(self) -> None:
        if self.ranges is None:
            self._say(t("The cut points text has an error: fix it to edit here."))
            return
        edge = self._edge_target()
        if edge is None:
            self._say(t("Click a cut line (or hold the mouse next to it), then press Delete to remove it."))
        elif edge.kind != "cut":
            self._say(t("Only a cut line between two parts can be removed (click the part to skip it instead)."))
        else:
            self._push_history()
            self._selected = None
            self._apply(remove_cut(self.ranges, edge.index))

    def nudge_edge(self, direction: int, step: float) -> None:
        """Move the selected / nearest cut line ``step`` seconds (Left = -1, Right = +1). With none, pan instead."""
        if self.ranges is None:
            self._say(t("The cut points text has an error: fix it to edit here."))
            return
        edge = self._edge_target()
        if edge is None:
            self.vp.pan_to(self.vp.start + direction * self.vp.span * 0.1)
            self.invalidate()
            return
        new = move_edge(self.ranges, edge, edge.t + direction * step, self.duration)
        if new == self.ranges:
            return
        key = (edge.kind, edge.index)
        now = time.monotonic()
        if not (self._last_nudge and self._last_nudge[0] == key and now - self._last_nudge[1] < 0.8):
            self._push_history()  # one undo takes back a whole run of nudges
        self._last_nudge = (key, now)
        moved = next((e for e in edges_of(new) if e.kind == edge.kind and e.index == edge.index), None)
        self._apply(new)
        if moved is not None:
            self._selected = (moved.kind, moved.index)
            if not (self.vp.start <= moved.t <= self.vp.start + self.vp.span):
                self.vp.pan_to(moved.t - self.vp.span / 2)
            self._say(t("Cut line at {time}", time=fmt_hms(moved.t)))
            _, kind = self._snap_with_kind(moved.t)
            self._set_snap_feedback(moved.t, kind, ttl_ms=1500)
        self.invalidate()

    def _on_wheel(self, x: float, delta: float, shift: bool = False) -> None:
        if not self._ready() or delta == 0:
            return
        direction = 1 if delta > 0 else -1
        if shift:  # Shift: move along the VOD
            self.vp.pan_to(self.vp.start - direction * self.vp.span * 0.15)
            self.invalidate()
        else:
            self._zoom(1.25 if direction > 0 else 1 / 1.25, x - PADX)

    def _apply(self, ranges: list[Range]) -> None:
        self.ranges = ranges
        self.invalidate()
        self.on_edit(list(ranges))

    def closeEvent(self, event) -> None:  # noqa: N802
        for name in ("_redraw_timer", "_shimmer_timer", "_snap_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_shimmer()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._shimmer_timer.stop()

    def refresh_language(self) -> None:
        """Update Timeline labels and tooltips when language changes."""
        self.btn_out.setToolTip(t("Zoom out  (−)"))
        self.btn_out.setAccessibleName(t("Zoom out"))
        self.btn_in.setToolTip(t("Zoom in  (+)"))
        self.btn_in.setAccessibleName(t("Zoom in"))
        self.btn_fit.setText(t("Fit"))
        self.btn_fit.setToolTip(t("Show the whole VOD  (0)"))
        self.btn_fit.setAccessibleName(t("Fit timeline to window"))
        self.btn_undo.setText(t("Undo"))
        self.btn_undo.setToolTip(t("Undo the last edit  (Ctrl+Z)"))
        self.btn_undo.setAccessibleName(t("Undo last cut edit"))
        self.btn_redo.setText(t("Redo"))
        self.btn_redo.setToolTip(t("Redo the edit you took back  (Ctrl+Y)"))
        self.btn_redo.setAccessibleName(t("Redo last undone cut edit"))
        if hasattr(self, "muted_title"):
            self.muted_title.setText(t("Show muted"))
        self.canvas.setAccessibleName(t("Interactive VOD timeline"))
        self.canvas.setAccessibleDescription(t("Interactive timeline strip for cutting and isolating segments"))
        self.minimap.setToolTip(t("Overview of the whole VOD: drag the highlighted window to move along it"))
        if self.muted:
            total = sum(e - s for s, e in self.muted)
            n = len(self.muted)
            stretches_txt = tn("{n} stretch", "{n} stretches", n)
            self.muted_info.setText(t("{stretches} · {duration} silenced by Twitch", stretches=stretches_txt, duration=fmt_hms(total)))
        if not self.duration:
            self.hint_label.setText(t(IDLE_HINT))
        self._rebuild_legend()
        self.invalidate()
