"""
Premiere Pro export: Final Cut Pro 7 XML with markers and .markers.json exchange format.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from core.chapters import MUTED_COMMENT, Chapter
from core.runtime import _NO_WINDOW, _tool_env, find_tool, resolve_dep

if TYPE_CHECKING:
    from core.source_info import SourceInfo

_ORIG_FIND_TOOL = find_tool
_ORIG_TOOL_ENV = _tool_env
_ORIG_NO_WINDOW = _NO_WINDOW


def _timebase(fps: float) -> tuple[int, bool]:
    """Frame rate -> (timebase, ntsc) the way FCP7 XML wants it: 59.94 -> (60, True)."""
    tb = max(1, round(fps))
    if abs(fps - tb) < 0.01:
        return tb, False
    if abs(fps - tb * 1000 / 1001) < 0.01:
        return tb, True
    return tb, False


def probe_video(path: Path) -> tuple[float, int, int] | None:
    """(fps, width, height) of the first video stream, or None if ffprobe is missing / fails."""
    _find = resolve_dep("find_tool", _ORIG_FIND_TOOL, find_tool)
    _env = resolve_dep("_tool_env", _ORIG_TOOL_ENV, _tool_env)
    _nw = resolve_dep("_NO_WINDOW", _ORIG_NO_WINDOW, _NO_WINDOW)

    if not _find:
        return None
    ffprobe = _find("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,width,height", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, env=_env(), creationflags=_nw, timeout=60,
        ).stdout
        st = json.loads(out)["streams"][0]
        num, _, den = str(st["r_frame_rate"]).partition("/")
        fps = float(num) / float(den or 1)
        if fps <= 0:
            return None
        return fps, int(st.get("width") or 1920), int(st.get("height") or 1080)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
        return None


def premiere_markers_xml(
    name: str, chapters: list[Chapter], duration: float, fps: float, width: int = 1920, height: int = 1080
) -> str:
    """
    FCP7 XML (xmeml) with one empty sequence and one sequence marker (in = chapter start, out = chapter end) per chapter.
    Game / category chapters (kind "game") are named "GAME: <game>" so they stand out from the clip markers.
    Premiere imports it through File > Import. Marker times are relative to the part.
    """
    tb, ntsc = _timebase(fps)
    real_rate = tb * 1000 / 1001 if ntsc else float(tb)
    rate = f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc></rate>"
    total = max(1, math.ceil(duration * real_rate))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE xmeml>",
        '<xmeml version="4">',
        '<sequence id="sequence-1">',
        f"<duration>{total}</duration>",
        rate,
        f"<name>{escape(name)}</name>",
        "<media><video><format><samplecharacteristics>",
        rate,
        f"<width>{width}</width><height>{height}</height>",
        "<anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance>",
        "</samplecharacteristics></format>",
        "<track><enabled>TRUE</enabled><locked>FALSE</locked></track>",
        "</video></media>",
        f"<timecode>{rate}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>",
    ]
    for ch in chapters:
        if ch.kind == "game":
            marker_name, comment = f"GAME: {ch.title}", "Game / category"
        else:
            marker_name = ch.title
            comment = " | ".join(
                f"{c.get('creator_name', '')} · {c.get('view_count', 0)} views · {c.get('url', '')}" for c in ch.clips
            )
        frame = min(max(int(round(ch.start * real_rate)), 0), total - 1)
        end = min(int(round(ch.end * real_rate)), total)  # the marker spans the whole clip
        lines += [
            "<marker>",
            f"<comment>{escape(comment)}</comment>",
            f"<name>{escape(marker_name)}</name>",
            f"<in>{frame}</in>",
            f"<out>{end if end > frame else -1}</out>",
            "</marker>",
        ]
    lines += ["</sequence>", "</xmeml>"]
    return "\n".join(lines) + "\n"


def write_premiere_xml(dest: Path, chapters: list[Chapter], duration: float, fps: float,
                       width: int = 1920, height: int = 1080) -> Path:
    """Write <part name>.markers.xml next to the part file."""
    out = dest.with_name(dest.stem + ".markers.xml")
    out.write_text(premiere_markers_xml(dest.stem, chapters, duration, fps, width, height), encoding="utf-8")
    return out


MARKERS_JSON_FORMAT = "luckytwitch-markers"
MARKERS_JSON_VERSION = 1  # bump when the layout changes in a way an older plugin cannot read; see docs/markers-format.md


def _clip_marker_comment(clips: list[dict]) -> str:
    return " | ".join(f"{c.get('creator_name', '')} · {c.get('view_count', 0)} views · {c.get('url', '')}" for c in clips)


def premiere_markers_json(
    name: str,
    chapters: list[Chapter],
    duration: float,
    fps: float,
    source: SourceInfo | None = None,
    part_start: float = 0.0,
    part_end: float | None = None,
    preferences: dict | None = None,
) -> str:
    """
    The markers of one part as JSON for the Premiere Pro plugin. Unlike the XML it keeps what each marker is
    (a clip or a game) and the numbers behind it (views...), so the plugin can choose colors and names itself.
    Times are seconds from the start of the part; part_start / part_end say where the part sits in the VOD.
    Kinds: "clip", "game" and "muted" (a stretch Twitch silenced). A plugin that does not know "muted" skips those.
    Optional `preferences` provides default padding / ripple limits for the plugin.
    """
    markers = []
    for ch in sorted(chapters, key=lambda c: (c.start, c.kind)):
        m: dict = {
            "kind": ch.kind if ch.kind in ("game", "muted") else "clip",
            "name": ch.title,
            "start": round(ch.start, 3),
            "end": round(ch.end, 3),
        }
        if ch.kind == "game":
            m["game"] = ch.title
            m["comment"] = "Game / category"
        elif ch.kind == "muted":
            m["comment"] = MUTED_COMMENT
        else:
            m["views"] = ch.views
            m["comment"] = _clip_marker_comment(ch.clips)
            m["clips"] = [
                {
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "creator": c.get("creator_name"),
                    "views": c.get("view_count"),
                    "duration": c.get("duration"),
                    "url": c.get("url"),
                }
                for c in ch.clips
            ]
        markers.append(m)
    data: dict = {
        "format": MARKERS_JSON_FORMAT,
        "version": MARKERS_JSON_VERSION,
        "name": name,
        "duration": round(duration, 3),
        "fps": round(fps, 5),
        "part": {"start": round(part_start, 3), "end": round(part_end if part_end is not None else part_start + duration, 3)},
    }
    if source is not None:
        data["source"] = {
            "url": source.url,
            "vod_id": str(getattr(source, "twitch_vod_id", "") or getattr(source, "id", "") or ""),
            "title": source.title,
            "streamer": source.uploader,
            "date": source.date,
        }
    if preferences:
        data["preferences"] = preferences
    data["markers"] = markers
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_markers_json(dest: Path, chapters: list[Chapter], duration: float, fps: float,
                       source: SourceInfo | None = None, part_start: float = 0.0,
                       part_end: float | None = None, preferences: dict | None = None) -> Path:
    """Write <part name>.markers.json next to the part file."""
    out = dest.with_name(dest.stem + ".markers.json")
    out.write_text(premiere_markers_json(dest.stem, chapters, duration, fps, source, part_start, part_end, preferences=preferences),
                   encoding="utf-8")
    return out
