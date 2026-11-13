"""System icon layer (Phase 9, A5): every icon of the app drawn in code with ``QPainterPath``.

No QtSvg, no ``.svg``/``.png`` files, no plugins: each icon is a handful of vector shapes on a 24x24 grid
(stroke-based, round caps and joins, like the Lucide/Feather family). The shapes are scaled to whatever size and
device pixel ratio is asked for, so they stay crisp at 100/125/150/200 % and on Retina, and they take any colour.

    from qt_ui.icons import icon, pixmap

    button.setIcon(icon("plus", 16, "#e6e6e6"))     # QIcon, rendered on demand at whatever size Qt asks
    label.setPixmap(pixmap("clock", 16, MUTED, dpr=self.devicePixelRatioF()))

Rules of the layer
------------------
* ``icon()`` returns a ``QIcon`` backed by a vector icon engine: ``QIcon.pixmap(size, dpr)`` and ``QIcon.paint`` render
  at the exact physical size, so a ``QPushButton`` on a 150 % screen gets 24 px of ink for a 16 px icon. Qt's
  *Disabled* mode uses the palette's ``DISABLED`` grey instead of Qt's blur-grey; *Active/Selected* keep the colour.
* ``pixmap()`` returns a ``QPixmap`` of ``round(size * dpr)`` physical pixels with ``devicePixelRatio`` set to ``dpr``.
* Results are cached by ``(name, size, colour, dpr)``. A cached ``QPixmap`` is shared: call ``.copy()`` before you
  paint on it.
* Names are case-insensitive, ``_`` equals ``-``, and a few aliases exist (``list`` -> ``queue``, ``vod`` -> ``film``,
  ``close`` -> ``x`` ...). ``available_icons()`` lists the canonical names only.
* An unknown name never crashes the UI: a "?" placeholder is drawn (and a warning logged once per name). Bad *sizes*,
  *dpr* or *colours* are programmer errors and raise ``ValueError``.
* Painting needs a ``QGuiApplication`` (it creates ``QPixmap``), the same as any Qt pixmap.

Adding an icon: write a ``_<name>()`` returning a list of ``(QPainterPath, mode)`` on the 24x24 grid, mode being
``"s"`` (stroke), ``"f"`` (fill) or ``"fs"`` (fill and stroke), and register it in ``_BUILDERS``. Keep ink inside
x/y 2..22 so the stroke never touches the edge (a test checks it), and view it in ``tools/widget_gallery.py``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

from core.i18n import t
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap, QTransform,
)

from core.palette import DISABLED, FG

__all__ = ["icon", "pixmap", "has_icon", "available_icons", "clear_cache"]

_log = logging.getLogger(__name__)

GRID = 24.0  # the drawing grid; every coordinate below is on it

Shape = tuple[QPainterPath, str]  # (path, "s" | "f" | "fs")


# --------------------------------------------------------------------------------------- #
# path helpers (all on the 24x24 grid)
# --------------------------------------------------------------------------------------- #
def _line(x1: float, y1: float, x2: float, y2: float) -> QPainterPath:
    p = QPainterPath(QPointF(x1, y1))
    p.lineTo(x2, y2)
    return p


def _poly(pts: list[tuple[float, float]], close: bool = False) -> QPainterPath:
    p = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        p.lineTo(x, y)
    if close:
        p.closeSubpath()
    return p


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(cx, cy), r, r)
    return p


def _rrect(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(x, y, w, h), r, r)
    return p


def _rpoly(pts: list[tuple[float, float]], r: float, close: bool = False) -> QPainterPath:
    """Polygon/polyline with rounded corners (quadratic bends, radius clamped to half of each edge)."""
    n = len(pts)

    def toward(a: tuple[float, float], b: tuple[float, float], d: float) -> QPointF:
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1.0
        d = min(d, ln / 2)
        return QPointF(a[0] + dx / ln * d, a[1] + dy / ln * d)

    p = QPainterPath()
    for i in range(n):
        cur = pts[i]
        corner = close or 0 < i < n - 1
        if not corner:
            if i == 0:
                p.moveTo(*cur)
            else:
                p.lineTo(*cur)
            continue
        prev, nxt = pts[(i - 1) % n], pts[(i + 1) % n]
        a, b = toward(cur, prev, r), toward(cur, nxt, r)
        if i == 0:
            p.moveTo(a)
        else:
            p.lineTo(a)
        p.quadTo(QPointF(*cur), b)
    if close:
        p.closeSubpath()
    return p


def _svgish(d: str) -> QPainterPath:
    """Tiny path parser: absolute ``M L H V C Z`` only (numbers separated by spaces)."""
    tok = d.replace(",", " ").split()
    p = QPainterPath()
    i = 0
    cx = cy = 0.0
    while i < len(tok):
        c = tok[i]
        i += 1
        if c == "M":
            cx, cy = float(tok[i]), float(tok[i + 1])
            i += 2
            p.moveTo(cx, cy)
        elif c == "L":
            cx, cy = float(tok[i]), float(tok[i + 1])
            i += 2
            p.lineTo(cx, cy)
        elif c == "H":
            cx = float(tok[i])
            i += 1
            p.lineTo(cx, cy)
        elif c == "V":
            cy = float(tok[i])
            i += 1
            p.lineTo(cx, cy)
        elif c == "C":
            v = [float(t) for t in tok[i:i + 6]]
            i += 6
            p.cubicTo(v[0], v[1], v[2], v[3], v[4], v[5])
            cx, cy = v[4], v[5]
        elif c == "Z":
            p.closeSubpath()
        else:
            raise ValueError(f"unsupported path command {c!r}")
    return p


def _mirror(p: QPainterPath) -> QPainterPath:
    """Flip left-right inside the grid."""
    return QTransform(-1, 0, 0, 1, GRID, 0).map(p)


def _place(p: QPainterPath, x: float, y: float, deg: float) -> QPainterPath:
    t = QTransform()
    t.translate(x, y)
    t.rotate(deg)
    return t.map(p)


def _arrow_head(tip: tuple[float, float], direction: tuple[float, float], size: float = 4.2,
                spread: float = 42.0) -> QPainterPath:
    """Open chevron whose point is ``tip`` and that points along ``direction``."""
    ang = math.atan2(direction[1], direction[0]) + math.pi  # back along the shaft
    a1, a2 = ang + math.radians(spread), ang - math.radians(spread)
    return _poly([(tip[0] + size * math.cos(a1), tip[1] + size * math.sin(a1)), tip,
                  (tip[0] + size * math.cos(a2), tip[1] + size * math.sin(a2))])


def _dot(x: float, y: float, r: float = 1.1) -> Shape:
    return _circle(x, y, r), "f"


def _gear_path(cx: float, cy: float, r_out: float, r_in: float, teeth: int) -> QPainterPath:
    pts: list[tuple[float, float]] = []
    step = 2 * math.pi / teeth
    w_out, w_in = step * 0.17, step * 0.26  # half-widths of a tooth at its tip and at its root
    for i in range(teeth):
        a = i * step - math.pi / 2
        for ang, r in ((a - w_in, r_in), (a - w_out, r_out), (a + w_out, r_out), (a + w_in, r_in),
                       (a + step / 2, r_in)):
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return _rpoly(pts, 0.9, close=True)


# --------------------------------------------------------------------------------------- #
# the icons
# --------------------------------------------------------------------------------------- #
def _search() -> list[Shape]:
    return [(_circle(10.5, 10.5, 6.5), "s"), (_line(15.4, 15.4, 20.5, 20.5), "s")]


def _queue() -> list[Shape]:
    return [(_line(9.5, 6, 20.5, 6), "s"), (_line(9.5, 12, 20.5, 12), "s"), (_line(9.5, 18, 20.5, 18), "s"),
            _dot(4.8, 6, 1.2), _dot(4.8, 12, 1.2), _dot(4.8, 18, 1.2)]


def _film() -> list[Shape]:
    out: list[Shape] = [(_rrect(3.5, 3.5, 17, 17, 2.5), "s"),
                        (_line(8, 3.5, 8, 20.5), "s"), (_line(16, 3.5, 16, 20.5), "s")]
    for y in (8.5, 12, 15.5):
        out.append((_line(3.5, y, 8, y), "s"))
        out.append((_line(16, y, 20.5, y), "s"))
    return out


def _gear() -> list[Shape]:
    return [(_gear_path(12, 12, 9.6, 7.4, 8), "s"), (_circle(12, 12, 3), "s")]


def _play() -> list[Shape]:
    return [(_rpoly([(7.5, 4.8), (19, 12), (7.5, 19.2)], 1.6, close=True), "fs")]


def _pause() -> list[Shape]:
    return [(_rrect(6.5, 5, 3.6, 14, 1.2), "fs"), (_rrect(13.9, 5, 3.6, 14, 1.2), "fs")]


def _stop() -> list[Shape]:
    return [(_rrect(6, 6, 12, 12, 2), "fs")]


def _scissors() -> list[Shape]:
    return [(_circle(6, 6, 3), "s"), (_circle(6, 18, 3), "s"),
            (_line(20, 4, 8.12, 15.88), "s"), (_line(14.8, 14.8, 20, 20), "s"), (_line(8.12, 8.12, 12, 12), "s")]


def _fit() -> list[Shape]:
    corners = [[(4, 9), (4, 4), (9, 4)], [(15, 4), (20, 4), (20, 9)],
               [(20, 15), (20, 20), (15, 20)], [(9, 20), (4, 20), (4, 15)]]
    return [(_rpoly(c, 1.2), "s") for c in corners] + [(_rrect(9, 9, 6, 6, 1.2), "s")]


def _undo() -> list[Shape]:
    return [(_poly([(8.5, 14), (3.5, 9), (8.5, 4)]), "s"),
            (_svgish("M 3.5 9 H 14.5 C 17.54 9 20 11.46 20 14.5 C 20 17.54 17.54 20 14.5 20 H 11"), "s")]


def _redo() -> list[Shape]:
    return [(_mirror(p), m) for p, m in _undo()]


def _plus() -> list[Shape]:
    return [(_line(12, 5, 12, 19), "s"), (_line(5, 12, 19, 12), "s")]


def _minus() -> list[Shape]:
    return [(_line(5, 12, 19, 12), "s")]


def _folder() -> list[Shape]:
    return [(_rpoly([(3, 5), (9, 5), (11.5, 8), (21, 8), (21, 19), (3, 19)], 2, close=True), "s")]


def _folder_open() -> list[Shape]:
    back = _rpoly([(3, 17), (3, 5), (9, 5), (11.2, 8), (19, 8), (19, 11.5)], 1.8)
    front = _rpoly([(2.8, 19.3), (6.2, 11.5), (21.5, 11.5), (18.6, 19.3)], 1.6, close=True)
    return [(back, "s"), (front, "s")]


def _copy() -> list[Shape]:
    back = _rpoly([(9, 15), (3.5, 15), (3.5, 3.5), (15, 3.5), (15, 9)], 1.8)
    return [(_rrect(9, 9, 11.5, 11.5, 2.2), "s"), (back, "s")]


def _trash() -> list[Shape]:
    body = _rpoly([(6, 7), (6.9, 19.8), (17.1, 19.8), (18, 7)], 1.4)
    handle = _rpoly([(9.2, 6.5), (9.2, 4), (14.8, 4), (14.8, 6.5)], 1.0)
    return [(_line(3.5, 6.5, 20.5, 6.5), "s"), (handle, "s"), (body, "s"),
            (_line(10, 10.5, 10, 16), "s"), (_line(14, 10.5, 14, 16), "s")]


def _download() -> list[Shape]:
    return [(_line(12, 4, 12, 15), "s"), (_poly([(7.5, 10.5), (12, 15), (16.5, 10.5)]), "s"),
            (_rpoly([(4, 15), (4, 19.5), (20, 19.5), (20, 15)], 1.5), "s")]


def _refresh() -> list[Shape]:
    cx = cy = 12.0
    r = 8.0
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    start = 35.0
    arc = QPainterPath()
    arc.arcMoveTo(rect, start)
    arc.arcTo(rect, start, 290.0)
    t = math.radians(start)
    tip = (cx + r * math.cos(t), cy - r * math.sin(t))
    direction = (math.sin(t), math.cos(t))  # clockwise on screen
    return [(arc, "s"), (_arrow_head(tip, direction, 4.4), "s")]


def _external_link() -> list[Shape]:
    box = _rpoly([(11, 6), (4.5, 6), (4.5, 19.5), (18, 19.5), (18, 13)], 2)
    return [(box, "s"), (_poly([(15, 4), (20, 4), (20, 9)]), "s"), (_line(11, 13, 20, 4), "s")]


def _link() -> list[Shape]:
    # two open capsules on the diagonal with a gap between their open ends, joined by a short bar
    half = QPainterPath(QPointF(0.5, -3.2))
    half.lineTo(-3.0, -3.2)
    half.arcTo(QRectF(-6.2, -3.2, 6.4, 6.4), 90.0, 180.0)
    half.lineTo(0.5, 3.2)
    d = 3.4 / math.sqrt(2)  # centre offset of each half along the diagonal
    a = _place(half, 12 - d, 12 + d, -45)
    b = _place(half, 12 + d, 12 - d, 135)
    e = 2.4 / math.sqrt(2)
    bar = _line(12 - e, 12 + e, 12 + e, 12 - e)
    return [(a, "s"), (b, "s"), (bar, "s")]


def _check() -> list[Shape]:
    return [(_poly([(4.5, 12.5), (9.5, 17.5), (19.5, 6.5)]), "s")]


def _x() -> list[Shape]:
    return [(_line(6, 6, 18, 18), "s"), (_line(18, 6, 6, 18), "s")]


def _alert() -> list[Shape]:
    return [(_rpoly([(12, 3.8), (21.5, 19.5), (2.5, 19.5)], 2.2, close=True), "s"),
            (_line(12, 9.5, 12, 14), "s"), _dot(12, 16.9, 1.05)]


def _info() -> list[Shape]:
    return [(_circle(12, 12, 9), "s"), (_line(12, 11, 12, 16.5), "s"), _dot(12, 7.9, 1.1)]


def _clock() -> list[Shape]:
    return [(_circle(12, 12, 9), "s"), (_poly([(12, 7), (12, 12), (15.6, 14.2)]), "s")]


def _eye() -> list[Shape]:
    lid = _svgish("M 2.5 12 C 5 7.5 8.3 5.5 12 5.5 C 15.7 5.5 19 7.5 21.5 12 "
                  "C 19 16.5 15.7 18.5 12 18.5 C 8.3 18.5 5 16.5 2.5 12 Z")
    return [(lid, "s"), (_circle(12, 12, 3), "s")]


def _flag() -> list[Shape]:
    cloth = _svgish("M 5 4.5 C 8.5 3 10.5 3.5 12.5 4.5 C 14.5 5.5 16.5 6 19 5 V 14 "
                    "C 16.5 15 14.5 14.5 12.5 13.5 C 10.5 12.5 8.5 12 5 13.5")
    return [(_line(5, 3.5, 5, 20.5), "s"), (cloth, "s")]


def _chevron_right() -> list[Shape]:
    return [(_poly([(9, 5.5), (15.5, 12), (9, 18.5)]), "s")]


def _chevron_left() -> list[Shape]:
    return [(_poly([(15, 5.5), (8.5, 12), (15, 18.5)]), "s")]


def _chevron_down() -> list[Shape]:
    return [(_poly([(5.5, 9), (12, 15.5), (18.5, 9)]), "s")]


def _grid() -> list[Shape]:
    s = 7.5
    return [(_rrect(x, y, s, s, 1.8), "s") for x in (3.5, 13) for y in (3.5, 13)]


def _list_view() -> list[Shape]:
    return [(_rrect(3.5, 4.5, 17, 6, 1.8), "s"), (_rrect(3.5, 13.5, 17, 6, 1.8), "s")]


def _filter() -> list[Shape]:
    return [(_rpoly([(3, 4.5), (21, 4.5), (14, 12.5), (14, 20), (10, 18), (10, 12.5)], 1.2, close=True), "s")]


def _sliders() -> list[Shape]:
    out: list[Shape] = []
    for y, kx in ((6, 9), (12, 15.5), (18, 8)):
        out.append((_line(3.5, y, kx - 2.9, y), "s"))
        out.append((_line(kx + 2.9, y, 20.5, y), "s"))
        out.append((_circle(kx, y, 2.4), "s"))
    return out


def _user() -> list[Shape]:
    shoulders = _svgish("M 4.5 20 C 4.5 15.6 8 13.5 12 13.5 C 16 13.5 19.5 15.6 19.5 20")
    return [(_circle(12, 8, 4), "s"), (shoulders, "s")]



def _window_minimize() -> list[Shape]:
    return [(_line(6, 16.5, 18, 16.5), "s")]


def _window_maximize() -> list[Shape]:
    return [(_rrect(5, 5, 14, 14, 1.5), "s")]


def _window_restore() -> list[Shape]:
    back = _poly([(8.5, 5), (19, 5), (19, 15.5)])
    front = _rrect(5, 8.5, 10.5, 10.5, 1.2)
    return [(back, "s"), (front, "s")]


def _missing() -> list[Shape]:
    q = _svgish("M 9.6 9.6 C 9.6 8 10.7 7.2 12 7.2 C 13.3 7.2 14.4 8.1 14.4 9.5 C 14.4 11.4 12 11.6 12 13.8")
    return [(_rrect(3.5, 3.5, 17, 17, 3.5), "s"), (q, "s"), _dot(12, 16.6, 1.0)]


_BUILDERS: dict[str, Callable[[], list[Shape]]] = {
    # navigation and views
    "search": _search, "queue": _queue, "film": _film, "gear": _gear,
    # playback and timeline
    "play": _play, "pause": _pause, "stop": _stop, "scissors": _scissors, "fit": _fit, "undo": _undo,
    "redo": _redo, "plus": _plus, "minus": _minus,
    # actions and files
    "folder": _folder, "folder-open": _folder_open, "copy": _copy, "trash": _trash, "download": _download,
    "refresh": _refresh, "external-link": _external_link, "link": _link,
    # status and feedback
    "check": _check, "x": _x, "alert": _alert, "info": _info, "clock": _clock, "eye": _eye, "flag": _flag,
    # ui controls
    "chevron-right": _chevron_right, "chevron-left": _chevron_left, "chevron-down": _chevron_down, "grid": _grid, "list-view": _list_view,
    "filter": _filter, "sliders": _sliders, "user": _user,
    "window-minimize": _window_minimize, "window-maximize": _window_maximize, "window-restore": _window_restore,
}

_ALIASES = {
    "list": "queue", "vod": "film", "video": "film", "settings": "gear", "cog": "gear", "zoom-fit": "fit",
    "add": "plus", "remove": "minus", "close": "x", "cross": "x", "warning": "alert", "tick": "check",
    "open-folder": "folder-open", "external": "external-link", "open-external": "external-link",
    "reload": "refresh", "save": "download", "delete": "trash", "cut": "scissors", "views": "eye",
    "clip": "flag", "person": "user", "account": "user", "options": "sliders", "arrow-right": "chevron-right",
    "arrow-left": "chevron-left", "arrow-down": "chevron-down", "list-ui": "list-view", "time": "clock", "duration": "clock",
    "minimize": "window-minimize", "maximize": "window-maximize", "restore": "window-restore",
}

_MISSING = "?"  # internal key of the placeholder (not a legal public name)
_shape_cache: dict[str, list[Shape]] = {}
_warned: set[str] = set()


def _canonical(name: str) -> str | None:
    key = name.strip().lower().replace("_", "-").replace(" ", "-")
    key = _ALIASES.get(key, key)
    return key if key in _BUILDERS else None


def _shapes(key: str) -> list[Shape]:
    shapes = _shape_cache.get(key)
    if shapes is None:
        shapes = _shape_cache[key] = _missing() if key == _MISSING else _BUILDERS[key]()
    return shapes


# --------------------------------------------------------------------------------------- #
# painting
# --------------------------------------------------------------------------------------- #
def _stroke_width(logical_size: float) -> float:
    """Stroke on the 24 grid: heavier when small so a 16 px icon keeps a visible 1.3 px line."""
    if logical_size <= 18:
        return 2.0
    if logical_size <= 32:
        return 1.75
    return 1.5


def _paint(p: QPainter, key: str, rect: QRectF, color: QColor, logical_size: float) -> None:
    p.save()
    try:
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(rect.topLeft())
        side = min(rect.width(), rect.height())
        p.translate((rect.width() - side) / 2, (rect.height() - side) / 2)
        p.scale(side / GRID, side / GRID)
        pen = QPen(color, _stroke_width(logical_size), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        for path, mode in _shapes(key):
            p.setPen(pen if "s" in mode else Qt.PenStyle.NoPen)
            p.setBrush(color if "f" in mode else Qt.BrushStyle.NoBrush)
            p.drawPath(path)
    finally:
        p.restore()


# --------------------------------------------------------------------------------------- #
# arguments and caches
# --------------------------------------------------------------------------------------- #
_PIXMAP_LIMIT = 1024
_pixmap_cache: dict[tuple[str, int, str, float], QPixmap] = {}
_icon_cache: dict[tuple[str, int, str], QIcon] = {}


def _color(value: str | QColor) -> QColor:
    c = QColor(value)
    if not c.isValid():
        raise ValueError(f"not a colour: {value!r}")
    return c


def _hex(c: QColor) -> str:
    return c.name(QColor.NameFormat.HexArgb)


def _key_for(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError(f"icon name must be a str, not {type(name).__name__}")
    key = _canonical(name)
    if key is not None:
        return key
    if name not in _warned:
        _warned.add(name)
        _log.warning(t("unknown icon {name!r} (available: {avail})", name=name, avail=", ".join(available_icons())))
    return _MISSING


def _check_size(size: int) -> int:
    if isinstance(size, bool) or not isinstance(size, (int, float)) or size < 1:
        raise ValueError(f"icon size must be a number >= 1, got {size!r}")
    return int(round(size))


def _render(key: str, size: int, color: QColor, dpr: float) -> QPixmap:
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        _paint(p, key, QRectF(0, 0, px, px), color, size)
    finally:
        p.end()
    pm.setDevicePixelRatio(dpr)  # after painting: we drew in device pixels
    return pm


def _cached_pixmap(key: str, size: int, color: QColor, dpr: float) -> QPixmap:
    ck = (key, size, _hex(color), round(dpr, 4))
    pm = _pixmap_cache.get(ck)
    if pm is None:
        if len(_pixmap_cache) >= _PIXMAP_LIMIT:
            _pixmap_cache.pop(next(iter(_pixmap_cache)))  # drop the oldest
        pm = _pixmap_cache[ck] = _render(key, size, color, dpr)
    return pm


# --------------------------------------------------------------------------------------- #
# the QIcon engine
# --------------------------------------------------------------------------------------- #
class _VectorIconEngine(QIconEngine):
    """Renders the shapes at the size/dpr Qt asks for; Disabled mode uses the palette's DISABLED grey."""

    def __init__(self, key: str, color: QColor, nominal: int):
        super().__init__()
        self._key = key
        self._color = QColor(color)
        self._nominal = nominal

    def _mode_color(self, mode: QIcon.Mode) -> QColor:
        if mode == QIcon.Mode.Disabled:
            c = QColor(DISABLED)
            c.setAlphaF(min(c.alphaF(), self._color.alphaF()))
            return c
        return self._color

    def paint(self, painter: QPainter, rect, mode, state) -> None:  # noqa: D401 (Qt override)
        _paint(painter, self._key, QRectF(rect), self._mode_color(mode), min(rect.width(), rect.height()))

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:
        side = max(1, min(size.width(), size.height()))
        return _cached_pixmap(self._key, side, self._mode_color(mode), float(scale) or 1.0)

    def actualSize(self, size: QSize, mode, state) -> QSize:
        side = max(1, min(size.width(), size.height()))
        return QSize(side, side)

    def availableSizes(self, mode=QIcon.Mode.Normal, state=QIcon.State.Off) -> list[QSize]:
        return [QSize(self._nominal, self._nominal)]

    def clone(self) -> QIconEngine:
        return _VectorIconEngine(self._key, self._color, self._nominal)

    def key(self) -> str:
        return "luckytwitch-vector"


# --------------------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------------------- #
def available_icons() -> list[str]:
    """Canonical icon names, sorted."""
    return sorted(_BUILDERS)


def has_icon(name: str) -> bool:
    """True if ``name`` (or an alias of it) can be drawn. Never raises."""
    return isinstance(name, str) and _canonical(name) is not None


def pixmap(name: str, size: int = 16, color: str | QColor = FG, dpr: float = 1.0) -> QPixmap:
    """The icon as a ``QPixmap`` of ``round(size * dpr)`` physical pixels, ``devicePixelRatio`` = ``dpr``.

    Shared and cached: ``.copy()`` it before painting on it.
    """
    size = _check_size(size)
    if not isinstance(dpr, (int, float)) or isinstance(dpr, bool) or dpr <= 0:
        raise ValueError(f"dpr must be a number > 0, got {dpr!r}")
    return _cached_pixmap(_key_for(name), size, _color(color), float(dpr))


def icon(name: str, size: int = 16, color: str | QColor = FG) -> QIcon:
    """A resolution-independent ``QIcon``; ``size`` is the nominal size (Qt may ask for any other)."""
    size = _check_size(size)
    c = _color(color)
    key = _key_for(name)
    ck = (key, size, _hex(c))
    ic = _icon_cache.get(ck)
    if ic is None:
        ic = _icon_cache[ck] = QIcon(_VectorIconEngine(key, c, size))
    return ic


def clear_cache() -> None:
    """Drop every cached pixmap and icon (tests; nothing else needs it)."""
    _pixmap_cache.clear()
    _icon_cache.clear()
