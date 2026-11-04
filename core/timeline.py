"""Pure geometry, snapping and undo-history helpers for the timeline widget."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

from core.planning import parse_cut_points
from core.timeutil import fmt_hms

if TYPE_CHECKING:
    from core.source_info import GameSegment

# --- range and slice editing --- #
Range = tuple[float, float]
MIN_PART = 1.0  # seconds: the shortest part an edit can create


@dataclass(frozen=True)
class Edge:
    """Something on the timeline that can be dragged: kind is "cut" (shared by two touching parts, `index`
    is the left one), or "start" / "end" (the border of part `index` next to a skipped section)."""

    kind: str
    index: int
    t: float


def ranges_of(text: str, duration: float | None) -> list[Range]:
    """Cut text -> ranges in whole seconds (the text is written back that way anyway). Raises PlanError like
    parse_cut_points. A part that is shorter than a second once rounded is left out."""
    out = [(round(p.start), round(p.end)) for p in parse_cut_points(text, duration)]
    return [(s, e) for s, e in out if e - s >= MIN_PART]


def ranges_to_text(ranges: list[Range], duration: float | None) -> str:
    """Ranges -> cut text: touching parts in one line ("a - b - c"), skipped sections start a new line."""
    def tok(t: float, last: bool = False) -> str:
        return "end" if last and duration and t >= duration - 0.5 else fmt_hms(t)

    groups: list[list[str]] = []
    prev_end: float | None = None
    for s, e in ranges:
        if groups and prev_end is not None and abs(prev_end - s) < 1e-6:
            groups[-1].append(tok(e, True))
        else:
            groups.append([fmt_hms(s), tok(e, True)])
        prev_end = e
    return "\n".join(" - ".join(g) for g in groups)


def edges_of(ranges: list[Range]) -> list[Edge]:
    out: list[Edge] = []
    for i, (s, e) in enumerate(ranges):
        if not (i > 0 and abs(ranges[i - 1][1] - s) < 1e-6):  # a touching start is the previous part's "cut"
            out.append(Edge("start", i, s))
        touches = i + 1 < len(ranges) and abs(ranges[i + 1][0] - e) < 1e-6
        out.append(Edge("cut" if touches else "end", i, e))
    return out


def nearest_edge(ranges: list[Range], t: float, tolerance: float) -> Edge | None:
    """The edge closest to time `t`, if it is within `tolerance` seconds."""
    best = min(edges_of(ranges), key=lambda ed: abs(ed.t - t), default=None)
    return best if best is not None and abs(best.t - t) <= tolerance else None


def part_index_at(ranges: list[Range], t: float) -> int | None:
    for i, (s, e) in enumerate(ranges):
        if s <= t < e:
            return i
    return None


def add_cut(ranges: list[Range], t: float) -> list[Range] | None:
    """Split the part that contains `t`. None = nothing to do (skipped section, or too close to an edge)."""
    t = round(t)
    for i, (s, e) in enumerate(ranges):
        if s + MIN_PART <= t <= e - MIN_PART:
            return ranges[:i] + [(s, t), (t, e)] + ranges[i + 1:]
    return None


def move_edge(ranges: list[Range], edge: Edge, t: float, duration: float) -> list[Range]:
    """Drag an edge to `t` (clamped so no part gets shorter than MIN_PART and parts never overlap)."""
    t = round(t)
    r = list(ranges)
    i = edge.index
    if edge.kind == "cut":
        t = min(max(t, r[i][0] + MIN_PART), r[i + 1][1] - MIN_PART)
        r[i], r[i + 1] = (r[i][0], t), (t, r[i + 1][1])
    elif edge.kind == "start":
        lo = r[i - 1][1] if i > 0 else 0
        t = min(max(t, lo), r[i][1] - MIN_PART)
        r[i] = (t, r[i][1])
    else:
        hi = r[i + 1][0] if i + 1 < len(r) else duration
        t = min(max(t, r[i][0] + MIN_PART), hi)
        r[i] = (r[i][0], t)
    return r


def remove_cut(ranges: list[Range], index: int) -> list[Range]:
    """Merge part `index` with the next one (they must touch: use it for "cut" edges)."""
    return ranges[:index] + [(ranges[index][0], ranges[index + 1][1])] + ranges[index + 2:]


def toggle_part(ranges: list[Range], t: float, duration: float) -> list[Range] | None:
    """Skip the part at `t`, or bring back the skipped section at `t`. None = not possible
    (the last remaining part cannot be skipped)."""
    i = part_index_at(ranges, t)
    if i is not None:
        return ranges[:i] + ranges[i + 1:] if len(ranges) > 1 else None
    prev_end = max((e for s, e in ranges if e <= t), default=0)
    next_start = min((s for s, e in ranges if s > t), default=duration)
    if next_start - prev_end < MIN_PART:
        return None
    pos = sum(1 for s, e in ranges if e <= t)
    return ranges[:pos] + [(prev_end, next_start)] + ranges[pos:]


def isolate_span(ranges: list[Range], a: float, b: float, duration: float, only: bool = False) -> list[Range]:
    """Make [a, b] its own part(s): cut at a and b, and keep everything in between (skipped sections inside
    it are brought back). only=True: drop everything else and keep just [a, b]."""
    a, b = max(0, round(a)), min(duration, round(b))
    if b - a < MIN_PART:
        return list(ranges)
    if only:
        return [(a, b)]
    pieces: list[Range] = []
    for s, e in ranges:
        pts = [s] + [x for x in (a, b) if s + MIN_PART <= x <= e - MIN_PART] + [e]
        pieces += list(zip(pts, pts[1:]))
    inside = sorted(p for p in pieces if p[0] >= a and p[1] <= b)
    outside = [p for p in pieces if not (p[0] >= a and p[1] <= b)]
    filled: list[Range] = []
    cursor = a
    for s, e in inside:
        if s > cursor:
            filled.append((cursor, s))
        filled.append((s, e))
        cursor = e
    if b > cursor:
        filled.append((cursor, b))
    return sorted(outside + filled)


# --- geometry (pixels) --- #
THUMB_W, THUMB_H = 100, 56
PADX = 8  # room left and right so the first / last cut line is not clipped
RULER_H, GAMES_H, PARTS_H, GAP = 20, 22, 26, 3
Y_RULER = 0
Y_GAMES = Y_RULER + RULER_H + GAP
Y_THUMBS = Y_GAMES + GAMES_H + GAP
Y_PARTS = Y_THUMBS + THUMB_H + GAP
HEIGHT = Y_PARTS + PARTS_H + 4
EDGE_TOL_PX = 6  # how close to a cut line the mouse has to be to grab it
SNAP_PX = 6  # cuts snap to game changes and clips this close
PREVIEW_MAX_W = 160

GAME_COLOURS = ["#3b5b8c", "#8c3b6e", "#3b8c6a", "#8c6a3b", "#6a3b8c", "#3b7f8c", "#8c4a3b", "#5d8c3b"]
CUT_COLOUR = "#ffffff"
EDGE_COLOUR = "#d2b8ff"
MUTED_COLOUR = "#ff4d4d"  # Twitch-silenced stretches (the plugin shows them red in Premiere too)
MUTED_H = 4  # height of the red line along the bottom of the games bar
IDLE_HINT = ("Click the thumbnails to cut \u00b7 click a part to skip it \u00b7 drag a cut line to move it \u00b7 "
             "right-click a cut line to remove it \u00b7 wheel = zoom")

_TIME_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600]


class Viewport:
    """Which stretch of the VOD is visible and how it maps to pixels (x = 0 is the left end of the drawing area)."""

    def __init__(self, duration: float = 1.0, width: int = 1):
        self.duration = max(float(duration), 1.0)
        self.width = max(int(width), 1)
        self.start = 0.0
        self.span = self.duration

    @property
    def min_span(self) -> float:
        return min(30.0, self.duration)

    @property
    def px_per_sec(self) -> float:
        return self.width / self.span

    @property
    def zoomed(self) -> bool:
        return self.span < self.duration - 1e-6

    def t2x(self, t: float) -> float:
        return (t - self.start) * self.px_per_sec

    def x2t(self, x: float) -> float:
        return self.start + x / self.px_per_sec

    def clamp(self) -> None:
        self.span = min(max(self.span, self.min_span), self.duration)
        self.start = min(max(self.start, 0.0), self.duration - self.span)

    def zoom(self, factor: float, anchor_x: float) -> None:
        """factor > 1 zooms in, < 1 zooms out; the moment under ``anchor_x`` stays under it."""
        anchor_t = self.x2t(anchor_x)
        frac = min(max(anchor_x / self.width, 0.0), 1.0)
        self.span = min(max(self.span / factor, self.min_span), self.duration)
        self.start = anchor_t - frac * self.span
        self.clamp()

    def pan_to(self, start: float) -> None:
        self.start = start
        self.clamp()

    def fit(self) -> None:
        self.start, self.span = 0.0, self.duration


def nice_step(px_per_sec: float, min_px: float = 80.0) -> int:
    """Smallest "round" time step (seconds) whose marks are at least ``min_px`` apart."""
    return next((s for s in _TIME_STEPS if s * px_per_sec >= min_px), _TIME_STEPS[-1])


def game_colour(title: str) -> str:
    """Same game, same colour, in every VOD and every run (crc32, not Python's randomised hash)."""
    return GAME_COLOURS[zlib.crc32(title.strip().lower().encode("utf-8")) % len(GAME_COLOURS)]


def zone_at(y: float) -> str:
    if y < Y_GAMES:
        return "ruler"
    if y < Y_THUMBS:
        return "games"
    if y < Y_PARTS:
        return "thumbs"
    return "parts"


def y_of(zone: str) -> int:
    """A y coordinate that lies inside the given row (``ruler``, ``games``, ``thumbs``, ``parts``)."""
    return {"ruler": Y_RULER + RULER_H // 2, "games": Y_GAMES + GAMES_H // 2,
            "thumbs": Y_THUMBS + THUMB_H // 2, "parts": Y_PARTS + PARTS_H // 2}[zone]


def build_snap_points(duration: float, segments: Iterable[GameSegment] = (),
                      clip_marks: Iterable[float] = (), muted: Iterable[Range] = (),
                      show_muted: bool = True) -> list[float]:
    """Sorted moments (seconds) that cuts and dragged edges snap to."""
    pts: set[float] = {0.0, float(duration)}
    for g in segments:
        pts.update((float(g.start), float(g.end)))
    pts.update(float(t) for t in clip_marks)
    if show_muted:
        for s, e in muted:
            pts.update((float(s), float(e)))
    return sorted(pts)


def snap_time(t: float, snap_points: Sequence[float], px_per_sec: float, snap_px: float = SNAP_PX) -> int:
    """Snap ``t`` to the closest point in ``snap_points`` if within ``snap_px`` pixels, rounded to a whole second."""
    tol = snap_px / px_per_sec
    best = min(snap_points, key=lambda p: abs(p - t), default=None)
    if best is not None and abs(best - t) <= tol:
        return round(best)
    return round(t)


# --- Phase 9f helpers: snap feedback, clip flags, game legend, skipped sections, minimap --- #
SNAP_GAME, SNAP_CLIP, SNAP_MUTED, SNAP_EDGE = "Game change", "Clip", "Muted edge", "VOD edge"


def build_snap_kinds(duration: float, segments: Iterable[GameSegment] = (),
                     clip_marks: Iterable[float] = (), muted: Iterable[Range] = (),
                     show_muted: bool = True) -> dict[float, str]:
    """What each snap point is (same points as ``build_snap_points``). Where two kinds meet the stronger one wins:
    VOD edge > game change > clip > muted edge."""
    kinds: dict[float, str] = {}
    if show_muted:
        for s, e in muted:
            kinds[float(s)] = kinds[float(e)] = SNAP_MUTED
    for t in clip_marks:
        kinds[float(t)] = SNAP_CLIP
    for g in segments:
        kinds[float(g.start)] = kinds[float(g.end)] = SNAP_GAME
    kinds[0.0] = kinds[float(duration)] = SNAP_EDGE
    return kinds


def snap_target(t: float, snap_points: Sequence[float], px_per_sec: float, snap_px: float = SNAP_PX) -> float | None:
    """The snap point ``snap_time`` would use for ``t`` (None when nothing is within ``snap_px`` pixels)."""
    tol = snap_px / px_per_sec
    best = min(snap_points, key=lambda p: abs(p - t), default=None)
    return best if best is not None and abs(best - t) <= tol else None


def cluster_marks(times: Sequence[float], px_per_sec: float, min_px: float = 9.0) -> list[tuple[float, int, float, float]]:
    """Group sorted moments that would sit closer than ``min_px`` pixels to the first of their group.
    Returns ``(centre_time, count, first_time, last_time)`` per group (count 1 = a lone flag)."""
    out: list[tuple[float, int, float, float]] = []
    group: list[float] = []
    for t in sorted(times):
        if group and (t - group[0]) * px_per_sec >= min_px:
            out.append((sum(group) / len(group), len(group), group[0], group[-1]))
            group = []
        group.append(t)
    if group:
        out.append((sum(group) / len(group), len(group), group[0], group[-1]))
    return out


def game_key(title: str) -> str:
    return title.strip().lower()


def game_totals(segments: Iterable[GameSegment]) -> list[tuple[str, float]]:
    """``(title, seconds)`` per game (a game seen twice is summed), longest first; segments without a title are left out."""
    names: dict[str, str] = {}
    totals: dict[str, float] = {}
    for g in segments:
        key = game_key(g.title or "")
        if not key:
            continue
        names.setdefault(key, g.title.strip())
        totals[key] = totals.get(key, 0.0) + max(0.0, float(g.end) - float(g.start))
    return sorted(((names[k], v) for k, v in totals.items()), key=lambda kv: -kv[1])


def gaps_of(ranges: Sequence[Range], duration: float) -> list[Range]:
    """The skipped sections: what lies between the parts (and before the first / after the last)."""
    out: list[Range] = []
    cursor = 0.0
    for s, e in sorted(ranges):
        if s > cursor + 1e-6:
            out.append((cursor, float(s)))
        cursor = max(cursor, float(e))
    if duration > cursor + 1e-6:
        out.append((cursor, float(duration)))
    return out


def minimap_lens(start: float, span: float, duration: float, width: float, pad: float = PADX,
                 min_w: float = 8.0) -> tuple[float, float]:
    """Left and right x of the lens that shows the visible window on a minimap ``width`` px wide."""
    inner = max(width - 2 * pad, 1.0)
    dur = max(duration, 1.0)
    x0 = pad + inner * (start / dur)
    x1 = pad + inner * ((start + span) / dur)
    if x1 - x0 < min_w:
        x1 = x0 + min_w
    return x0, min(x1, pad + inner)
