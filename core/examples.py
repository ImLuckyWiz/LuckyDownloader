"""The live «Example:» lines under the template fields of the Options tab (no Qt, no tkinter).

Port of the ``_example_*`` methods of ``ui/options_tab.py``. They use the engine's own naming functions
(``part_stem``, ``stream_dir``, ``_SafeDict``), so an example is exactly what a job would call the file. ``source`` is
the loaded VOD (a ``SourceInfo``) or None: then a sample VOD is used.
"""

from __future__ import annotations

from core.chapters import _SafeDict
from core.finalize import part_stem, stream_dir
from core.job import JobOptions
from core.planning import Part
from core.source_info import GameSegment, SourceInfo, VideoFormat

SAMPLE_SOURCE = dict(
    url="https://www.twitch.tv/videos/123",
    id="v123",
    title="Big Stream",
    uploader="Streamer",
    duration=7200.0,
    date="2026-10-01",
    twitch_vod_id="123",
    segments=[GameSegment(0.0, 7200.0, "Just Chatting")],
    formats=[VideoFormat("1080p60", 1080, 60, 6000, False, True)],
)
SAMPLE_CLIP = {"id": "ClipId", "title": "Epic fail", "creator_name": "viewer1", "view_count": 500, "duration": 30}

_ENGINE_DEFAULTS = JobOptions(cut_text="", out_dir="")  # the engine's own default templates


def example_source(source: SourceInfo | None) -> SourceInfo:
    return source if source else SourceInfo(**SAMPLE_SOURCE)


def template(settings: dict, name: str, fallback: str) -> str:
    """The template as typed (trimmed), or ``fallback`` when it is empty."""
    value = settings.get(name, "")
    return (value.strip() if isinstance(value, str) else "") or fallback


def example_options(settings: dict) -> JobOptions:
    container = settings.get("container", "mp4")
    quality = settings.get("default_quality", "Best available")
    return JobOptions(
        cut_text="", out_dir="", container=container if isinstance(container, str) else "mp4",
        name_template=template(settings, "name_template", _ENGINE_DEFAULTS.name_template),
        folder_template=template(settings, "folder_template", _ENGINE_DEFAULTS.folder_template),
        clip_name_template=template(settings, "clip_name_template", _ENGINE_DEFAULTS.clip_name_template),
        quality=quality if isinstance(quality, str) else "Best available",
        subfolders=True)


def example_file_name(settings: dict, source: SourceInfo | None = None) -> str:
    opts = example_options(settings)
    return f"{part_stem(example_source(source), opts, Part(1, 0, 3600), 3)}.{opts.container}"


def example_folder_name(settings: dict, source: SourceInfo | None = None) -> str:
    opts = example_options(settings)
    return stream_dir(example_source(source), opts).as_posix().replace("./", "").replace("\\", "/")


def example_clip_name(settings: dict, source: SourceInfo | None = None) -> str:
    opts = example_options(settings)
    return f"{part_stem(example_source(source), opts, Part(1, 0, 30), 1, SAMPLE_CLIP)}.{opts.container}"


def example_chapter(settings: dict) -> str:
    tpl = template(settings, "title_tpl", "{title} ({creator}, {views} views)")
    data = _SafeDict(title=SAMPLE_CLIP["title"], creator=SAMPLE_CLIP["creator_name"],
                     views=SAMPLE_CLIP["view_count"], duration=SAMPLE_CLIP["duration"])
    try:
        return tpl.format_map(data)
    except (ValueError, IndexError):
        return "(the template has an unfinished {…})"
