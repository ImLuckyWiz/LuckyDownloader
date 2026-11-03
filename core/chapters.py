"""
Clips to chapters, game chapters, muted chapters, and ffmetadata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.errors import PlanError
from core.i18n import t
from core.timeline import Range
from core.timeutil import fmt_hms
from core.twitch_api import clip_end, clip_start

if TYPE_CHECKING:
    from luckytwitch_engine import GameSegment


@dataclass
class ClipFilter:
    min_views: int = 0
    min_duration: float = 0  # seconds
    top_n: int = 0  # 0 = no limit; otherwise keep the N most viewed
    pad_before: float = 3  # seconds added before the clip start
    pad_after: float = 0
    title_template: str = "{title} ({creator}, {views} views)"
    gap_title: str = "Stream"  # fills the space between clips; "" = no filler (MKV only)


@dataclass
class Chapter:
    start: float  # seconds, absolute VOD time
    end: float
    title: str
    views: int = 0
    clips: list[dict] = field(default_factory=list)
    kind: str = "clip"  # "clip" (a Twitch clip), "game" (a game / category change) or "muted" (silenced by Twitch)


class _SafeDict(dict):
    def __missing__(self, key):  # unknown {tokens} stay as they are
        return "{" + key + "}"


def filter_clips(clips: list[dict], flt: ClipFilter) -> list[dict]:
    """Keep only the clips that pass the filter (and can be placed in the VOD)."""
    kept = [
        c
        for c in clips
        if clip_start(c) is not None
        and c.get("view_count", 0) >= flt.min_views
        and c.get("duration", 0) >= flt.min_duration
    ]
    if flt.top_n > 0:
        kept.sort(key=lambda c: (-c.get("view_count", 0), clip_start(c)))
        kept = kept[: flt.top_n]
    kept.sort(key=clip_start)
    return kept


def _chapter_title(clip: dict, tpl: str) -> str:
    data = _SafeDict(
        title=clip.get("title", "") or "Clip",
        creator=clip.get("creator_name", ""),
        views=clip.get("view_count", 0),
        duration=round(clip.get("duration", 0)),
    )
    try:
        return tpl.format_map(data)
    except (KeyError, ValueError, AttributeError, TypeError, IndexError):
        return data["title"]


def clip_cut_text(
    clip: dict, duration: float | None, pad_before: float = 3, pad_after: float = 3
) -> str:
    """Cut text ('H:MM:SS - H:MM:SS') that covers just one clip (plus a little context)."""
    clip_s = clip_start(clip)
    if clip_s is None:
        raise PlanError(t("That clip has no position in the VOD."))
    start = max(0.0, clip_s - pad_before)
    end = float(clip["vod_offset"]) + pad_after
    if duration:
        end = min(end, duration)
    a, b = math.floor(start), math.ceil(end)
    if b <= a:
        raise PlanError(t("That clip is outside the VOD."))
    return f"{fmt_hms(a)} - {fmt_hms(b)}"


def make_chapters(clips: list[dict], flt: ClipFilter) -> list[Chapter]:
    """Filtered clips -> chapters in absolute VOD time. Overlapping clips are merged."""
    chapters: list[Chapter] = []
    for c in filter_clips(clips, flt):
        ch = Chapter(
            start=max(0.0, clip_start(c) - flt.pad_before),
            end=clip_end(c) + flt.pad_after,
            title=_chapter_title(c, flt.title_template),
            views=c.get("view_count", 0),
            clips=[c],
        )
        if chapters and ch.start <= chapters[-1].end:
            prev = chapters[-1]
            best = ch if ch.views > prev.views else prev
            n = len(prev.clips) + 1
            prev.title = best.title.split("  (+")[0] + f"  (+{n - 1} more)"
            prev.views = best.views
            prev.end = max(prev.end, ch.end)
            prev.clips.append(c)
        else:
            chapters.append(ch)
    return chapters


def chapters_for_part(chapters: list[Chapter], start: float, end: float) -> list[Chapter]:
    """Chapters that fall in [start, end], with times relative to the part."""
    out = []
    for ch in chapters:
        if ch.end <= start or ch.start >= end:
            continue
        s, e = max(ch.start, start) - start, min(ch.end, end) - start
        if e - s < 1:
            continue
        out.append(Chapter(s, e, ch.title, ch.views, ch.clips, ch.kind))
    return out


def game_chapters(segments: list[Any]) -> list[Chapter]:
    """The game / category changes of a VOD as chapters of kind "game" (absolute VOD time)."""
    return [Chapter(g.start, g.end, g.title or "(no category)", kind="game") for g in segments]


MUTED_TITLE = "Muted audio"
MUTED_COMMENT = "Silenced by Twitch (usually copyrighted audio)"


def muted_chapters(ranges: list[Range] | None) -> list[Chapter]:
    """The stretches Twitch silenced as chapters of kind "muted" (absolute VOD time)."""
    return [Chapter(s, e, MUTED_TITLE, kind="muted") for s, e in (ranges or [])]


def fill_gaps(chapters: list[Chapter], total: float, title: str) -> list[Chapter]:
    """
    MP4 chapters are contiguous (each one lasts until the next starts, the first
    one starts at 0), so gaps between clips are filled with a neutral chapter.
    """
    if not chapters or not title:
        return chapters
    out: list[Chapter] = []
    pos = 0.0
    for ch in chapters:
        if ch.start - pos >= 1:
            out.append(Chapter(pos, ch.start, title))
        out.append(ch)
        pos = ch.end
    if total - pos >= 1:
        out.append(Chapter(pos, total, title))
    return out


def _ffmeta_escape(text: str) -> str:
    for ch in ("\\", "=", ";", "#", "\n"):
        text = text.replace(ch, "\\" + ch)
    return text


def ffmetadata(chapters: list[Chapter], tags: dict[str, str] | None = None) -> str:
    lines = [";FFMETADATA1"]
    for k, v in (tags or {}).items():
        if v:
            lines.append(f"{k}={_ffmeta_escape(v)}")
    for ch in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(ch.start * 1000)}",
            f"END={int(ch.end * 1000)}",
            f"title={_ffmeta_escape(ch.title)}",
        ]
    return "\n".join(lines) + "\n"
