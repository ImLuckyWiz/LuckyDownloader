"""Painting routines, canvas, and minimap widgets for the Timeline component."""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QWidget

try:
    from shiboken6 import isValid
except ImportError:
    def isValid(obj: object) -> bool:  # noqa: N802
        return True

from core.i18n import t
from core.palette import ACCENT, ACCENT_HOVER, BG, BG2, BG3, ERR, FG, MUTED, OK, UI_FONT, WHITE
from core.timeline import (
    CUT_COLOUR, EDGE_COLOUR, GAMES_H, HEIGHT, MUTED_COLOUR, MUTED_H, PADX, PARTS_H, RULER_H, THUMB_H, THUMB_W,
    Y_GAMES, Y_PARTS, Y_RULER, Y_THUMBS, game_colour, game_key, gaps_of, minimap_lens, nice_step, zone_at,
)
from luckytwitch_engine import edges_of, fmt_hms, part_index_at

PART_RADIUS = 6.0
FLAG_MIN_PX = 9.0  # clip flags closer than this merge into one counter badge
MINIMAP_H = 12
SHIMMER_MS = 40
SHIMMER_STEP = 0.03


def _motion_enabled() -> bool:
    try:
        from qt_ui.motion import Motion
        return Motion.enabled()
    except ImportError:  # pragma: no cover
        return True


class TimelineMinimap(QWidget):
    """A thin overview of the whole VOD shown while the strip is zoomed in: game colours, the parts, and a lens for
    the visible window. Click to centre the lens there, drag the lens to move along the VOD (E3)."""

    def __init__(self, timeline):
        super().__init__(timeline)
        self.tl = timeline
        self.setFixedHeight(MINIMAP_H)
        self._grab: float | None = None  # seconds between the lens start and the mouse while dragging
        self.drawn_lens: tuple[float, float] | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(t("Overview of the whole VOD: drag the highlighted window to move along it"))

    def _inner(self) -> float:
        return max(self.width() - 2 * PADX, 1.0)

    def t_at(self, x: float) -> float:
        return (x - PADX) / self._inner() * max(self.tl.duration, 1.0)

    def x_of(self, t: float) -> float:
        return PADX + self._inner() * (t / max(self.tl.duration, 1.0))

    def lens(self) -> tuple[float, float]:
        vp = self.tl.vp
        return minimap_lens(vp.start, vp.span, self.tl.duration, self.width())

    def paintEvent(self, _event) -> None:  # noqa: N802
        tl = self.tl
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        if not tl.duration:
            p.end()
            return
        track = QRectF(PADX, 2, self._inner(), self.height() - 4)
        p.fillRect(track, QColor(BG2))
        for g in tl.segments:
            x0, x1 = self.x_of(g.start), self.x_of(g.end)
            col = QColor(game_colour(g.title))
            col.setAlpha(170)
            p.fillRect(QRectF(x0, track.top(), max(x1 - x0, 1.0), track.height()), col)
        if tl.ranges:
            keep = QColor(ACCENT)
            for s, e in tl.ranges:
                p.fillRect(QRectF(self.x_of(s), track.bottom() - 2, max(self.x_of(e) - self.x_of(s), 1.0), 2), keep)
            p.setPen(QPen(QColor(CUT_COLOUR), 1))
            for edge in edges_of(tl.ranges):
                if edge.kind == "cut":
                    x = self.x_of(edge.t)
                    p.drawLine(QPointF(x, track.top()), QPointF(x, track.bottom()))
        x0, x1 = self.lens()
        self.drawn_lens = (x0, x1)
        fill = QColor(ACCENT_HOVER)
        fill.setAlpha(70)
        lens = QRectF(x0, 0.5, x1 - x0, self.height() - 1)
        p.fillRect(lens, fill)
        p.setPen(QPen(QColor(ACCENT_HOVER), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(lens, 3, 3)
        p.end()

    def _pan_to_pointer(self, x: float) -> None:
        if self._grab is None or not self.tl.duration:
            return
        self.tl.vp.pan_to(self.t_at(x) - self._grab)
        self.tl.invalidate()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self.tl.duration:
            super().mousePressEvent(event)
            return
        x = event.position().x()
        x0, x1 = self.lens()
        if x0 <= x <= x1:
            self._grab = self.t_at(x) - self.tl.vp.start
        else:
            self._grab = self.tl.vp.span / 2  # centre the lens on the click
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._pan_to_pointer(x)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._grab is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._pan_to_pointer(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._grab is not None:
            self._grab = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TimelineCanvas(QWidget):
    """The custom-painted strip inside ``Timeline``."""

    def __init__(self, timeline):
        super().__init__(timeline)
        self.tl = timeline
        self.setFixedHeight(HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        self.tl._paint_canvas(self)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.tl.invalidate()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        btn = event.button()
        mods = event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if btn == Qt.MouseButton.RightButton or (
            sys.platform == "darwin" and (
                btn == Qt.MouseButton.MiddleButton
                or (btn == Qt.MouseButton.LeftButton and bool(mods & Qt.KeyboardModifier.ControlModifier))
            )
        ):
            self.tl._on_right(pos.x(), pos.y(), event.globalPosition().toPoint())
            event.accept()
            return
        if btn == Qt.MouseButton.LeftButton:
            self.tl._on_press(pos.x(), pos.y(), shift=shift)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.tl._on_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.tl._on_double(pos.x(), pos.y(), shift=shift)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.buttons() & Qt.MouseButton.LeftButton and (self.tl._drag is not None or self.tl._pan is not None):
            self.tl._on_motion(pos.x(), pos.y())
        else:
            self.tl._on_hover(pos.x(), pos.y())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.tl._on_release()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.tl._on_leave()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.angleDelta().x()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.tl._on_wheel(event.position().x(), delta, shift=shift)
        event.accept()  # keep the ScrollPage behind from scrolling


class TimelinePaintersMixin:
    """Mixin for Timeline providing custom QPainter drawing methods, shimmer, and invalidation."""

    def invalidate(self) -> None:
        """Schedule a repaint (coalesced through Qt's update mechanism and ``_redraw_pending``)."""
        self.vp.width = self._draw_width()
        if self.duration:
            self.vp.clamp()
        self._update_scrollbar()
        self._sync_chrome()
        if not self._redraw_pending:
            self._redraw_pending = True
            if hasattr(self, "_redraw_timer"):
                self._redraw_timer.start(0)
            else:
                QTimer.singleShot(0, self._flush_redraw)
        try:
            if hasattr(self, "canvas") and isValid(self.canvas):
                self.canvas.update()
        except RuntimeError:
            pass

    def _flush_redraw(self) -> None:
        self._redraw_pending = False
        try:
            if hasattr(self, "canvas") and isValid(self.canvas):
                self.canvas.update()
        except RuntimeError:
            pass

    def _sync_shimmer(self) -> None:
        """The thumbnail placeholders shimmer only while frames load, the widget is on screen and motion is allowed."""
        want = (self.frames_state == "loading" and bool(self.duration) and self.isVisible() and _motion_enabled())
        if want and not self._shimmer_timer.isActive():
            self._shimmer_timer.start()
        elif not want and self._shimmer_timer.isActive():
            self._shimmer_timer.stop()

    def _on_shimmer(self) -> None:
        if self.frames_state != "loading":
            self._shimmer_timer.stop()
            return
        self._shimmer_phase = (self._shimmer_phase + SHIMMER_STEP) % 1.0
        self.canvas.update()

    def redraw(self) -> None:
        """Force an immediate synchronous paint/state update (useful in tests)."""
        self._redraw_pending = False
        self.vp.width = self._draw_width()
        if self.duration:
            self.vp.clamp()
        self._update_scrollbar()
        self._sync_chrome()
        pm = QPixmap(max(self.canvas.width(), 400), HEIGHT)
        self._paint_canvas(pm)
        self.canvas.update()
        if self.minimap.isVisible():
            mpm = QPixmap(max(self.minimap.width(), 400), MINIMAP_H)
            self._paint_minimap(mpm)
            self.minimap.update()

    def _paint_minimap(self, target) -> None:
        p = QPainter(target)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = target.width() if hasattr(target, "width") else self.minimap.width()
        h = target.height() if hasattr(target, "height") else self.minimap.height()
        track = QRectF(PADX, 1, max(w - 2 * PADX, 1), h - 2)
        p.fillRect(QRectF(0, 0, w, h), QColor(BG))
        p.fillRect(track, QColor(BG2))
        for g in self.segments:
            x0, x1 = self.minimap.x_of(g.start), self.minimap.x_of(g.end)
            col = QColor(game_colour(g.title))
            col.setAlpha(170)
            p.fillRect(QRectF(x0, track.top(), max(x1 - x0, 1.0), track.height()), col)
        if self.ranges:
            keep = QColor(ACCENT)
            for s, e in self.ranges:
                p.fillRect(
                    QRectF(
                        self.minimap.x_of(s),
                        track.bottom() - 2,
                        max(self.minimap.x_of(e) - self.minimap.x_of(s), 1.0),
                        2,
                    ),
                    keep,
                )
            p.setPen(QPen(QColor(CUT_COLOUR), 1))
            for edge in edges_of(self.ranges):
                if edge.kind == "cut":
                    x = self.minimap.x_of(edge.t)
                    p.drawLine(QPointF(x, track.top()), QPointF(x, track.bottom()))
        x0, x1 = self.minimap.lens()
        self.minimap.drawn_lens = (x0, x1)
        fill = QColor(ACCENT_HOVER)
        fill.setAlpha(70)
        lens = QRectF(x0, 0.5, x1 - x0, h - 1)
        p.fillRect(lens, fill)
        p.setPen(QPen(QColor(ACCENT_HOVER), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(lens, 3, 3)
        p.end()

    def _x_range(self, start: float, end: float) -> tuple[float, float] | None:
        """Pixel span of ``[start, end]``, clipped to the drawing area; None if it is not visible."""
        x0 = max(self.x_of(start), PADX)
        x1 = min(self.x_of(end), PADX + self.vp.width)
        return (x0, x1) if x1 > x0 else None

    def _paint_canvas(self, widget: QWidget) -> None:
        self.drawn_texts.clear()
        self.drawn_muted_rects.clear()
        self.drawn_skipped_rects.clear()
        self.drawn_flags.clear()
        self.drawn_thumb_count = 0
        self.drawn_hover_preview = False

        p = QPainter(widget)
        p.fillRect(widget.rect(), QColor(BG))

        if not self.duration:
            self._draw_text(
                p, QRectF(0, 0, widget.width() or 400, HEIGHT),
                t("Press «Get info» to see the VOD here."), MUTED, 10, Qt.AlignmentFlag.AlignCenter,
            )
            self._update_scrollbar()
            p.end()
            return

        self.vp.width = self._draw_width()
        self.vp.clamp()
        self._draw_ruler(p)
        self._draw_games(p)
        self._draw_muted(p)
        self._draw_thumbs(p)
        self._draw_parts(p)
        self._draw_snap_feedback(p)
        if self._hover_pos is not None:
            hx, hy, dragging = self._hover_pos
            self._draw_hover_overlay(p, hx, hy, dragging=dragging)
        self._update_scrollbar()
        p.end()

    def _draw_text(self, p: QPainter, rect: QRectF, text: str, colour: str, size_pt: int,
                   align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter) -> None:
        self.drawn_texts.append(text)
        font = QFont(UI_FONT, size_pt)
        p.setFont(font)
        p.setPen(QColor(colour))
        p.drawText(rect, int(align), text)

    def _draw_ruler(self, p: QPainter) -> None:
        vp = self.vp
        step = nice_step(vp.px_per_sec)
        t_cur = math.floor(vp.start / step) * step
        base = Y_RULER + RULER_H
        font = QFont(UI_FONT, 8)
        p.setFont(font)
        muted_col = QColor(MUTED)
        while t_cur <= vp.start + vp.span + step:
            x = self.x_of(t_cur)
            if PADX - 1 <= x <= PADX + vp.width + 1:
                p.setPen(muted_col)
                p.drawLine(QPointF(x, base - 5), QPointF(x, base))
                txt = fmt_hms(t_cur)
                self.drawn_texts.append(txt)
                p.drawText(
                    QRectF(x + 3, Y_RULER, 72, RULER_H - 2),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    txt,
                )
            t_cur += step
        ok_col = QColor(OK)
        for fx, _centre, count, _first, _last in self._flags():
            if not (PADX - 1 <= fx <= PADX + vp.width + 1):
                continue
            self.drawn_flags.append((fx, count))
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if count == 1:
                p.setPen(QPen(ok_col, 1.4))
                p.drawLine(QPointF(fx, Y_RULER + 1), QPointF(fx, Y_RULER + 11))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ok_col)
                p.drawPolygon(
                    QPolygonF([QPointF(fx, Y_RULER + 1), QPointF(fx + 8, Y_RULER + 4.5), QPointF(fx, Y_RULER + 8)])
                )
                p.restore()
            else:
                label = str(count) if count < 100 else "99+"
                w = max(16.0, 7.5 * len(label) + 8)
                badge = QRectF(fx - w / 2, Y_RULER + 1, w, 13)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ok_col)
                p.drawRoundedRect(badge, 6.5, 6.5)
                p.restore()
                self._draw_text(p, badge, label, BG, 8, Qt.AlignmentFlag.AlignCenter)

    def _draw_games(self, p: QPainter) -> None:
        if not self.segments:
            p.fillRect(QRectF(PADX, Y_GAMES, self.vp.width, GAMES_H), QColor(BG2))
            self._draw_text(
                p, QRectF(PADX + 6, Y_GAMES, self.vp.width - 12, GAMES_H),
                "No game information for this VOD", MUTED, 9,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
            return
        bg_pen = QPen(QColor(BG), 1)
        hl = self._highlight_title
        for g in self.segments:
            span = self._x_range(g.start, g.end)
            if span is None:
                continue
            x0, x1 = span
            rect = QRectF(x0, Y_GAMES, x1 - x0, GAMES_H)
            mine = hl is not None and game_key(g.title or "") == hl
            col = QColor(game_colour(g.title))
            if hl is not None and not mine:
                col.setAlpha(70)
            p.fillRect(rect, col)
            p.setPen(bg_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            if mine:
                p.setPen(QPen(QColor(WHITE), 2))
                p.drawRect(rect.adjusted(1, 1, -1, -1))
            room = int((x1 - x0 - 8) / 6.3)
            if room >= 3 and g.title:
                text = g.title if len(g.title) <= room else g.title[: room - 1] + "\u2026"
                self._draw_text(
                    p, QRectF(x0 + 4, Y_GAMES, max(0.0, x1 - x0 - 8), GAMES_H),
                    text, WHITE, 9, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )

    def _draw_muted(self, p: QPainter) -> None:
        """A thin red line along the bottom of the games bar wherever Twitch silenced the audio."""
        if not self.muted or not self.show_muted_enabled:
            return
        y0 = Y_GAMES + GAMES_H - MUTED_H
        col = QColor(MUTED_COLOUR)
        for s, e in self.muted:
            span = self._x_range(s, e)
            if span is None:
                continue
            x0, x1 = span
            w = max(x1 - x0, 2.0)
            p.fillRect(QRectF(x0, y0, w, MUTED_H), col)
            self.drawn_muted_rects.append((x0, float(y0), x0 + w, float(Y_GAMES + GAMES_H)))

    def _draw_thumbs(self, p: QPainter) -> None:
        from qt_ui import timeline as _tl_mod
        vp = self.vp
        track = QRectF(PADX, Y_THUMBS, vp.width, THUMB_H)
        p.fillRect(track, QColor(BG2))
        sb = self.storyboard
        if self.frames_state != "ready" or sb is None or _tl_mod.Image is None:
            msg = {
                "loading": "Loading thumbnails\u2026",
                "failed": "Thumbnails are not available",
                "none": "This VOD has no preview thumbnails",
            }.get(self.frames_state, "")
            if sb is not None and _tl_mod.Image is None:
                msg = "Thumbnails need Pillow (pip install pillow)"
            if self.frames_state == "loading" and _tl_mod.Image is not None:
                self._draw_shimmer(p, track)
            else:
                p.fillRect(track, QBrush(QColor(BG3), Qt.BrushStyle.BDiagPattern))
            self._draw_placeholder_label(p, track, msg)
            return
        per_frame = vp.px_per_sec * sb.interval
        step = max(1, math.ceil(THUMB_W / per_frame))
        first = max(0, int(vp.start / sb.interval) // step * step - step)
        p.save()
        p.setClipRect(QRectF(PADX, Y_THUMBS, vp.width, THUMB_H))
        for i in range(first, sb.count, step):
            x = self.x_of(sb.frame_time(i))
            if x > PADX + vp.width:
                break
            if x + THUMB_W < PADX:
                continue
            kept = self.ranges is None or part_index_at(self.ranges, sb.frame_time(i)) is not None
            pm = self._pixmap(i, dim=not kept)
            if pm is None:
                continue
            p.drawPixmap(round(x), Y_THUMBS, pm)
            self.drawn_thumb_count += 1
        p.restore()

    def _draw_shimmer(self, p: QPainter, track: QRectF) -> None:
        """Grey picture-shaped tiles with a soft light sweeping over them while the thumbnails download."""
        p.save()
        p.setClipRect(track)
        tile = QColor(BG3)
        tile.setAlpha(150)
        x = track.left() + 2
        while x < track.right():
            p.fillRect(QRectF(x, track.top() + 4, THUMB_W - 6, THUMB_H - 8), tile)
            x += THUMB_W
        band = max(120.0, track.width() * 0.25)
        cx = track.left() - band + self._shimmer_phase * (track.width() + 2 * band)
        grad = QLinearGradient(cx - band / 2, 0, cx + band / 2, 0)
        light = QColor(FG)
        clear = QColor(FG)
        clear.setAlpha(0)
        light.setAlpha(38)
        grad.setColorAt(0.0, clear)
        grad.setColorAt(0.5, light)
        grad.setColorAt(1.0, clear)
        p.fillRect(track, QBrush(grad))
        p.restore()

    def _draw_placeholder_label(self, p: QPainter, track: QRectF, msg: str) -> None:
        if not msg:
            return
        fm = QFontMetricsF(QFont(UI_FONT, 9))
        w = min(track.width() - 8, fm.horizontalAdvance(msg) + 32)
        pill = QRectF(track.center().x() - w / 2, track.center().y() - 11, w, 22)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill = QColor(BG2)
        fill.setAlpha(235)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(pill, 11, 11)
        p.restore()
        self._draw_text(p, track, msg, MUTED, 9, Qt.AlignmentFlag.AlignCenter)

    def _draw_parts(self, p: QPainter) -> None:
        vp = self.vp
        track = QRectF(PADX, Y_PARTS, vp.width, PARTS_H)
        p.fillRect(track, QColor(BG2))
        if self.ranges is None:
            self._draw_text(
                p, track,
                t("The cut points text has an error: fix it to edit here."), ERR, 9, Qt.AlignmentFlag.AlignCenter,
            )
            return
        hatch = QColor(MUTED)
        hatch.setAlpha(120)
        for s, e in gaps_of(self.ranges, self.duration):
            span = self._x_range(s, e)
            if span is None:
                continue
            x0, x1 = span
            area = QRectF(x0, Y_PARTS, x1 - x0, PARTS_H)
            p.fillRect(area, QBrush(hatch, Qt.BrushStyle.BDiagPattern))
            self.drawn_skipped_rects.append((x0, float(Y_PARTS), x1, float(Y_PARTS + PARTS_H)))
        if not self.ranges:
            self._draw_text(
                p, track,
                "No parts yet: click here to start with the whole VOD.", MUTED, 9, Qt.AlignmentFlag.AlignCenter,
            )
        bg_pen = QPen(QColor(BG), 1)
        hover_part = None
        if self._hover_pos is not None and self._drag is None:
            hx, hy, _dragging = self._hover_pos
            if zone_at(hy) == "parts":
                hover_part = part_index_at(self.ranges, self.t_at(hx))
        view_end = vp.start + vp.span
        for n, (s, e) in enumerate(self.ranges, 1):
            span = self._x_range(s, e)
            if span is None:
                continue
            x0, x1 = span
            hovered = hover_part == n - 1
            rect = QRectF(x0, Y_PARTS - (1 if hovered else 0), x1 - x0, PARTS_H)
            radius = min(PART_RADIUS, rect.width() / 2, rect.height() / 2)
            fill = QColor(ACCENT_HOVER if hovered else ACCENT)
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            p.fillPath(path, fill)
            if s < vp.start - 1e-6:
                p.fillRect(QRectF(rect.left(), rect.top(), radius, rect.height()), fill)
            if e > view_end + 1e-6:
                p.fillRect(QRectF(rect.right() - radius, rect.top(), radius, rect.height()), fill)
            p.setPen(bg_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.restore()
            dur = fmt_hms(e - s)
            width = x1 - x0
            for label in (f"Part {n} \u00b7 {dur}", f"P{n} \u00b7 {dur}"):
                if width >= len(label) * 6.5 + 10:
                    self._draw_text(p, rect, label, WHITE, 9, Qt.AlignmentFlag.AlignCenter)
                    break
            else:
                if width >= 30:
                    self._draw_text(p, rect, str(n), WHITE, 9, Qt.AlignmentFlag.AlignCenter)
        for edge in edges_of(self.ranges):
            x = self.x_of(edge.t)
            if not (PADX - 1 <= x <= PADX + vp.width + 1):
                continue
            grabbed = self._drag is not None and (edge.kind, edge.index) == (self._drag.kind, self._drag.index)
            selected = self._selected == (edge.kind, edge.index)
            colour = QColor(OK if (grabbed or selected) else (CUT_COLOUR if edge.kind == "cut" else EDGE_COLOUR))
            p.setPen(QPen(colour, 3 if selected else 2))
            p.drawLine(QPointF(x, Y_GAMES), QPointF(x, Y_PARTS + PARTS_H))
            handle = QRectF(x - 3, Y_PARTS + 5, 6, PARTS_H - 10)
            p.fillRect(handle, colour)
            p.setPen(bg_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(handle)

    def _draw_snap_feedback(self, p: QPainter) -> None:
        """While a cut sticks to something: a thin guide line and «snaps to: …» (E8)."""
        if self._snap_feedback is None:
            return
        t_snap, kind = self._snap_feedback
        x = self.x_of(t_snap)
        if not (PADX - 1 <= x <= PADX + self.vp.width + 1):
            return
        p.setPen(QPen(QColor(OK), 1))
        p.drawLine(QPointF(x, Y_GAMES), QPointF(x, Y_PARTS + PARTS_H))
        text = f"snaps to: {kind}"
        w = QFontMetricsF(QFont(UI_FONT, 8)).horizontalAdvance(text) + 14
        left = x + 6 if x + 6 + w < PADX + self.vp.width else x - 6 - w
        pill = QRectF(left, Y_THUMBS + 3, w, 17)
        p.fillRect(pill, QColor(BG3))
        p.setPen(QPen(QColor(OK), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(pill)
        self._draw_text(p, pill, text, OK, 8, Qt.AlignmentFlag.AlignCenter)
