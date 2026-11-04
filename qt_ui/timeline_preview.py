"""Hover preview bubble, thumbnail tile rendering, clip flags & tooltips, and game legend chips for Timeline."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QLayout, QPushButton, QWidget

from core.i18n import t, tn
from core.palette import BG, BG3, FG, MUTED
from core.timeline import (
    HEIGHT, IDLE_HINT, PADX, PREVIEW_MAX_W, RULER_H, THUMB_H, THUMB_W, Y_GAMES, Y_RULER, cluster_marks, game_colour,
    game_key, game_totals, zone_at,
)
from luckytwitch_engine import Range, fmt_hms, isolate_span, part_index_at
from qt_ui.timeline_painters import FLAG_MIN_PX

LEGEND_MAX_CHIPS = 12


def _short_dur(seconds: float) -> str:
    """``3h 10m`` / ``12m 05s`` / ``45s`` (the legend chips)."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def _pil_to_qpixmap(im) -> QPixmap | None:
    """Convert a PIL ``Image`` to a ``QPixmap`` on the GUI thread."""
    if im is None:
        return None
    rgba = im.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def _dot_icon(colour: str, size: int = 10) -> QIcon:
    """A small round colour swatch for a legend chip."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(colour))
    p.drawEllipse(0, 0, size, size)
    p.end()
    return QIcon(pm)


class _FlowLayout(QLayout):
    """Left-to-right layout that wraps onto new lines (the game legend), with a proper ``heightForWidth``."""

    def __init__(self, parent: QWidget | None = None, hspacing: int = 6, vspacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._h, self._v = hspacing, vspacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            nxt = x + hint.width()
            if nxt > area.right() + 1 and line_h > 0:
                x, y, line_h = area.x(), y + line_h + self._v, 0
                nxt = x + hint.width()
            if not test:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = nxt + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class _LegendChip(QPushButton):
    """One game of the legend: click = make it its own part, hover = light it up on the strip."""

    hovered = Signal(str)
    unhovered = Signal()

    def __init__(self, title: str, seconds: float, parent: QWidget | None = None):
        super().__init__(f"{title}  {_short_dur(seconds)}", parent)
        self.title = title
        self.seconds = seconds
        self.setProperty("variant", "chip")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(_dot_icon(game_colour(title)))
        self.setToolTip(
            t(
                "{game}: {duration} in total\nClick: make it its own part · Shift+click: keep only this game",
                game=title,
                duration=fmt_hms(seconds),
            )
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self.hovered.emit(self.title)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unhovered.emit()
        super().leaveEvent(event)


class TimelinePreviewMixin:
    """Mixin for Timeline providing hover preview bubble, thumbnail caching, clip flags, and game legend."""

    # ------------------------------------------------------------------ game legend (E4)
    def _rebuild_legend(self) -> None:
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.legend_chips = []
        totals = game_totals(self.segments)
        for title, seconds in totals[:LEGEND_MAX_CHIPS]:
            chip = _LegendChip(title, seconds, self.legend_box)
            chip.clicked.connect(lambda _=False, t_name=title: self._on_chip_clicked(t_name))
            chip.hovered.connect(self._highlight_game)
            chip.unhovered.connect(lambda: self._highlight_game(None))
            self.legend_layout.addWidget(chip)
            self.legend_chips.append(chip)
        if len(totals) > LEGEND_MAX_CHIPS:
            more = QLabel(t("+{n} more", n=len(totals) - LEGEND_MAX_CHIPS))
            more.setProperty("role", "muted")
            self.legend_layout.addWidget(more)
        self.legend_box.setVisible(bool(self.legend_chips))
        self.legend_box.updateGeometry()

    def _on_chip_clicked(self, title: str) -> None:
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.isolate_game(title, only=shift)

    def _highlight_game(self, title: str | None) -> None:
        key = game_key(title) if title else None
        if key != self._highlight_title:
            self._highlight_title = key
            self.invalidate()

    def isolate_game(self, title: str, only: bool = False) -> None:
        """Every stretch of the game ``title`` becomes its own part (``only``: keep just those stretches)."""
        if not self._ready():
            return
        if self.ranges is None:
            self._say(t("The cut points text has an error: fix it to edit here."))
            return
        key = game_key(title)
        spans = [(g.start, g.end) for g in self.segments if game_key(g.title or "") == key]
        if not spans:
            return
        if only:
            new: list[Range] = []
            for a, b in sorted(spans):
                a, b = max(0, round(a)), min(self.duration, round(b))
                if b - a < 1:
                    continue
                if new and abs(new[-1][1] - a) < 1e-6:
                    new[-1] = (new[-1][0], b)
                else:
                    new.append((a, b))
            if not new:
                return
        else:
            new = list(self.ranges)
            for a, b in spans:
                new = isolate_span(new, a, b, self.duration)
        if new != self.ranges:
            self._push_history()
            self._apply(new)
            self._say(f"{title}: " + ("kept alone" if only else "is its own part now"))

    # ------------------------------------------------------------------ clip flags (E5)
    def _flags(self) -> list[tuple[float, float, int, float, float]]:
        """The flags / counter badges the ruler shows now: ``(x, centre_time, count, first_time, last_time)``."""
        vp = self.vp
        lo, hi = vp.start - 12 / vp.px_per_sec, vp.start + vp.span + 12 / vp.px_per_sec
        visible = [t_val for t_val in self.clip_marks if lo <= t_val <= hi]
        out = []
        for centre, count, first, last in cluster_marks(visible, vp.px_per_sec, FLAG_MIN_PX):
            x = self.x_of(centre)
            if PADX - 6 <= x <= PADX + vp.width + 6:
                out.append((x, centre, count, first, last))
        return out

    def _flag_text(self, count: int, first: float, last: float) -> str:
        if count == 1:
            detail = self.clip_details.get(first, "")
            return f"{detail}\n" + t("at {time}", time=fmt_hms(first)) if detail else t("Clip at {time}", time=fmt_hms(first))
        times = [t_val for t_val in self.clip_marks if first <= t_val <= last]
        lines = [
            tn(
                "{n} clip between {start} and {end}",
                "{n} clips between {start} and {end}",
                count,
                start=fmt_hms(first),
                end=fmt_hms(last),
            )
        ]
        lines += [f"\u2022 {self.clip_details.get(t_val, fmt_hms(t_val))}" for t_val in times[:4]]
        if len(times) > 4:
            lines.append(t("… and {n} more (zoom in to see them)", n=len(times) - 4))
        return "\n".join(lines)

    def _flag_at(self, x: float, y: float) -> str:
        """The tooltip of the flag / badge under the mouse, or "" when there is none."""
        if y > Y_RULER + 14:
            return ""
        for fx, _centre, count, first, last in self._flags():
            reach = 6 if count == 1 else 9
            if abs(x - fx) <= reach:
                return self._flag_text(count, first, last)
        return ""

    # ------------------------------------------------------------------ hover
    def _on_hover(self, x: float, y: float) -> None:
        if not self._ready() or self._drag is not None or self._pan is not None:
            return
        zone = zone_at(y)
        t_pos = self.t_at(x)
        self._hover_t = max(0.0, min(t_pos, float(self.duration)))
        edge = self._edge_at(x) if zone != "ruler" else None
        seg = self._segment_at(t_pos)
        where = f"{fmt_hms(max(0, min(t_pos, self.duration)))}" + (f"  \u00b7  {seg.title}" if seg and seg.title else "")
        mu = self._muted_at(t_pos)
        if mu is not None:
            where += "  \u00b7  " + t("muted by Twitch ({start} → {end})", start=fmt_hms(mu[0]), end=fmt_hms(mu[1]))
        tip = self._flag_at(x, y) if zone == "ruler" else ""
        if edge is not None:
            what = t("drag to move, right-click to remove") if edge.kind == "cut" else t("drag to move")
            cursor = Qt.CursorShape.SizeHorCursor
        elif tip:
            what, cursor = t("clip flag"), Qt.CursorShape.PointingHandCursor
        elif zone == "ruler":
            what, cursor = t("drag to move along the VOD"), Qt.CursorShape.SizeAllCursor
        elif zone == "games":
            what, cursor = t("double-click: make this game its own part (Shift: only this game)"), Qt.CursorShape.ArrowCursor
        elif zone == "thumbs":
            what, cursor = t("click to cut here (or press S)"), Qt.CursorShape.CrossCursor
        else:
            kept = self.ranges is not None and part_index_at(self.ranges, t_pos) is not None
            what, cursor = (
                (t("click to skip this part") if kept else t("click to keep this section")),
                Qt.CursorShape.PointingHandCursor,
            )
        if self.canvas.toolTip() != tip:
            self.canvas.setToolTip(tip)
        self.canvas.setCursor(cursor)
        self._say(f"{where}  \u00b7  {what}")
        self._hover_pos = (x, y, False)
        self.invalidate()

    def _on_leave(self) -> None:
        self._hover_pos = None
        self._hover_t = None
        self.canvas.setToolTip("")
        self.canvas.unsetCursor()
        if self._drag is None:
            self.hint_label.setText(t(IDLE_HINT))
        self.invalidate()

    # ------------------------------------------------------------------ images
    def _frame_image(self, idx: int):
        if not self.frames or not (0 <= idx < len(self.frames)):
            return None
        return self.frames[idx]

    def _pixmap(self, idx: int, dim: bool) -> QPixmap | None:
        from qt_ui import timeline as _tl_mod
        key = (idx, dim)
        if key not in self._pixmaps:
            im = self._frame_image(idx)
            if im is None or _tl_mod.Image is None:
                return None
            im = im.resize((THUMB_W, THUMB_H))
            if dim and _tl_mod.ImageEnhance is not None:
                im = _tl_mod.ImageEnhance.Brightness(im).enhance(0.35)
            pm = _pil_to_qpixmap(im)
            if pm is None:
                return None
            self._pixmaps[key] = pm
        return self._pixmaps[key]

    def _preview_pixmap(self, idx: int) -> QPixmap | None:
        from qt_ui import timeline as _tl_mod
        if idx not in self._preview_pixmaps:
            im = self._frame_image(idx)
            if im is None or _tl_mod.Image is None:
                return None
            if im.width > PREVIEW_MAX_W:
                im = im.resize((PREVIEW_MAX_W, round(im.height * PREVIEW_MAX_W / im.width)))
            pm = _pil_to_qpixmap(im)
            if pm is None:
                return None
            self._preview_pixmaps[idx] = pm
        return self._preview_pixmaps[idx]

    def _draw_hover_overlay(self, p: QPainter, x: float, _y: float, dragging: bool = False) -> None:
        from qt_ui import timeline as _tl_mod
        if not self.duration or not (PADX <= x <= PADX + self.vp.width):
            return
        t_cur = max(0.0, min(self.t_at(x), self.duration))
        dash_pen = QPen(QColor(MUTED), 1, Qt.PenStyle.DashLine)
        p.setPen(dash_pen)
        p.drawLine(QPointF(x, 0), QPointF(x, HEIGHT))
        label = fmt_hms(t_cur)
        tx = min(max(x, PADX + 26), PADX + self.vp.width - 26)
        badge = QRectF(tx - 26, 2, 52, RULER_H - 5)
        p.fillRect(badge, QColor(BG3))
        self._draw_text(p, badge, label, FG, 9, Qt.AlignmentFlag.AlignCenter)
        if dragging or self.frames_state != "ready" or _tl_mod.Image is None or self.storyboard is None:
            return
        idx = self.storyboard.frame_index_at(t_cur)
        pm = self._preview_pixmap(idx)
        if pm is None:
            return
        w, h = pm.width(), pm.height()
        left = x + 14 if x + 14 + w < PADX + self.vp.width else x - 14 - w
        top = Y_GAMES
        box = QRectF(left - 2, top - 2, w + 4, h + 4)
        p.fillRect(box, QColor(BG))
        p.setPen(QPen(QColor(FG), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.drawPixmap(round(left), round(top), pm)
        self.drawn_hover_preview = True
