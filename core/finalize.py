"""
Splitting, finalizing, path naming, and high-level job runner.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import math
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.chapters import (
    Chapter,
    _SafeDict,
    chapters_for_part,
    ffmetadata,
    fill_gaps,
    game_chapters,
    make_chapters,
    muted_chapters,
)
from core.chat import chat_files_for_part, unique_path
from core.download import (
    MP4_MOVIE_TIMESCALE,
    audio_codec_args,
    audio_only_options,
    audio_out_container,
    download_full,
    download_section,
    download_section_aligned,
    get_playlist_url,
    mp4_flags,
    mp4_movie_timescale,
    run_ffmpeg,
)
from core.errors import ArchiveSkippedError, Cancelled, DiskSpaceError, EngineError
from core.i18n import t
from core.job import Job, JobOptions
from core.providers import Capability
from core.muted import muted_from_playlist_url
from core.planning import Part, Plan, make_plan
from core.premiere_export import probe_video, write_markers_json, write_premiere_xml
from core.runtime import Ctx, find_tool, resolve_dep
from core.source_info import (
    GameSegment,
    QUALITY_BEST,
    SourceInfo,
    VideoFormat,
    describe_quality,
    resolve_format,
)
from core.timeutil import fmt_hms
from core.tools import ensure_tdcli
from core.twitch_api import fetch_clips_for_vod

_ORIG_FIND_TOOL = find_tool
_ORIG_UNIQUE_PATH = unique_path
_ORIG_RUN_FFMPEG = run_ffmpeg
_ORIG_DOWNLOAD_FULL = download_full
_ORIG_DOWNLOAD_SECTION = download_section
_ORIG_DOWNLOAD_SECTION_ALIGNED = download_section_aligned
_ORIG_GET_PLAYLIST_URL = get_playlist_url
_ORIG_MUTED_FROM_PLAYLIST_URL = muted_from_playlist_url
_ORIG_MAKE_CHAPTERS = make_chapters
_ORIG_ENSURE_TDCLI = ensure_tdcli
_ORIG_PROBE_VIDEO = probe_video
_ORIG_WRITE_PREMIERE_XML = write_premiere_xml
_ORIG_WRITE_MARKERS_JSON = write_markers_json


@dataclass
class PipelineDeps:
    """Explicit dependency container for the download and finalization pipeline."""
    find_tool: Callable[..., str | None] | None = None
    download_full: Callable[..., Path] | None = None
    download_section: Callable[..., Path] | None = None
    download_section_aligned: Callable[..., tuple[Path, float, float] | None] | None = None
    cut_exact: Callable[..., Path] | None = None
    split_copy: Callable[..., dict[int, tuple[Path, float, float]]] | None = None
    finalize_part: Callable[..., Path] | None = None
    finalize_audio_part: Callable[..., Path] | None = None
    ensure_tdcli: Callable[..., str] | None = None
    probe_video: Callable[..., tuple[float, int, int] | None] | None = None
    write_premiere_xml: Callable[..., Path] | None = None
    write_markers_json: Callable[..., Path] | None = None
    load_chapters: Callable[..., list[Chapter]] | None = None
    load_muted: Callable[..., list[Chapter]] | None = None
    unique_path: Callable[[Path], Path] | None = None
    run_ffmpeg: Callable[..., str] | None = None
    get_playlist_url: Callable[..., str] | None = None
    muted_from_playlist_url: Callable[..., list | None] | None = None
    make_chapters: Callable[..., list[Chapter]] | None = None


# --------------------------------------------------------------------------- #
# Splitting / finalizing helpers & naming
# --------------------------------------------------------------------------- #
def check_disk_space(out_dir: str | Path, required_bytes: int = 200 * 1024 * 1024) -> None:
    """Ensure destination directory has enough free space before starting download jobs."""
    try:
        usage = shutil.disk_usage(str(out_dir))
    except OSError:
        return
    if usage.free < required_bytes:
        free_mb = usage.free // (1024 * 1024)
        need_mb = required_bytes // (1024 * 1024)
        raise DiskSpaceError(
            f"Insufficient disk space in {out_dir}: {free_mb} MB free, at least {need_mb} MB required."
        )


def compute_job_workdir(src: SourceInfo, opts: JobOptions, fmt: VideoFormat | None = None, out_dir: Path | None = None) -> Path:
    """Return a deterministic temporary work directory for a job so interrupted downloads can resume."""
    base = Path(out_dir) if out_dir is not None else Path(opts.out_dir)
    id_slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(src.twitch_vod_id or src.id or "unknown"))[:64] or "unknown"
    fmt_slug = f"_{re.sub(r'[^A-Za-z0-9_-]', '_', fmt.format_id)[:40]}" if fmt else ""
    key = (
        f"{src.url}|{fmt_slug}|{opts.cut_text}|{opts.strategy}|{opts.quality}|"
        f"{opts.container}|{opts.exact}|{getattr(opts, 'keyframe_align', False)}|"
        f"{getattr(opts, 'reencode', False)}|{opts.audio_format}|{opts.keep_full}"
    )
    job_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return base / f".luckytwitch_{id_slug}{fmt_slug}_{job_hash}"


def cleanup_stale_workdirs(out_dir: str | Path, max_age_hours: float = 48.0) -> int:
    """Remove stale temporary work directories (.luckytwitch_* or .luckydownloader_work_*) older than max_age_hours."""
    base = Path(out_dir)
    if not base.is_dir():
        return 0
    cutoff = time.time() - (max_age_hours * 3600.0)
    removed = 0
    try:
        entries = list(base.iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if not (entry.name.startswith(".luckytwitch_") or entry.name.startswith(".luckydownloader_work_")):
                continue
            if (entry / ".running").exists():
                continue
            if max_age_hours <= 0 or entry.stat().st_mtime <= cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                if not entry.exists():
                    removed += 1
        except OSError:
            continue
    return removed


def clean_title(title: str) -> str:
    """Clean chat bot commands (!gsupps, !links, !clash), promo tags (#ad),
    emojis without word smushing, and dangling trailing delimiters from a stream title.
    """
    if not title:
        return ""
    # 1. Replace 4-byte Unicode characters (emojis / pictographs) with a space so adjacent words don't smush
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", " ", title)
    # 2. Strip chat bot commands that start with ! (e.g. !gsupps, !links, !clash, !discord, !merch, !drops)
    cleaned = re.sub(r"(?<!\w)!\w+", "", cleaned)
    # 3. Strip promotional hashtags / bracketed tags (e.g. #ad, #sponsored, #partner, [DROPS])
    cleaned = re.sub(r"(?<!\w)#(?:ad|sponsored|partner|drops|promo)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[(?:drops|drops enabled|!drops)\]", "", cleaned, flags=re.IGNORECASE)
    # 4. Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # 5. Clean up dangling trailing separators left behind (e.g. trailing " - ", " | ", " · ", " : ")
    cleaned = re.sub(r"[\s\-_|/·•:,]+$", "", cleaned).strip()
    return cleaned or title.strip()


_WIN_RESERVED_RE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9\xb9\xb2\xb3]|LPT[1-9\xb9\xb2\xb3])(\..*)?$",
    re.IGNORECASE,
)


def safe_name(text: str, max_len: int = 150) -> str:
    """Strip emojis / illegal characters so the name is safe everywhere."""
    text = re.sub(r"[\U00010000-\U0010ffff]", " ", text or "")
    text = re.sub(r"[^\w\s\-\.\(\)\[\]]", "", text, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", text).strip(" .")
    if max_len > 0 and len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    if _WIN_RESERVED_RE.match(s):
        s = f"_{s}"
    return s


def dominant_game(segments: list[GameSegment] | None, start: float, end: float) -> str:
    """Returns the game/category with the longest time overlap inside [start, end]."""
    if not segments or end <= start:
        return ""
    overlaps: dict[str, float] = {}
    for seg in segments:
        seg_start = getattr(seg, "start", 0.0)
        seg_end = getattr(seg, "end", 0.0)
        title = (getattr(seg, "title", "") or "").strip()
        if not title:
            continue
        overlap = max(0.0, min(end, seg_end) - max(start, seg_start))
        if overlap > 0:
            overlaps[title] = overlaps.get(title, 0.0) + overlap
    if not overlaps:
        return ""
    return max(overlaps.items(), key=lambda item: item[1])[0]


def date_components(date_str: str | None) -> tuple[str, str, str]:
    """Extract (year, month, day) from YYYY-MM-DD or empty strings if invalid."""
    if not date_str:
        return "", "", ""
    parts = date_str.strip().split("-")
    year = parts[0] if len(parts) >= 1 and len(parts[0]) == 4 and parts[0].isdigit() else ""
    month = parts[1] if len(parts) >= 2 and len(parts[1]) == 2 and parts[1].isdigit() else ""
    day = parts[2] if len(parts) >= 3 and len(parts[2]) == 2 and parts[2].isdigit() else ""
    return year, month, day


def format_duration_tag(seconds: float) -> str:
    """Format seconds into HHhMMmSSs tag string."""
    s = max(0, int(seconds))
    return f"{s // 3600:02d}h{s % 3600 // 60:02d}m{s % 60:02d}s"



GENERIC_NAME_TEMPLATE = "{uploader} - {date} - {title} [{id}]"


def format_generic_stem(src: SourceInfo, template: str | None = None, clean: bool = True) -> str:
    """Format file stem for non-Twitch jobs with uploader, date, title, id."""
    tpl = template or GENERIC_NAME_TEMPLATE
    title = clean_title(src.title) if clean else src.title
    date = src.date or datetime.now().strftime("%Y-%m-%d")
    data = _SafeDict(
        uploader=src.uploader or "video",
        author=src.uploader or "video",
        channel=src.uploader or "video",
        streamer=src.uploader or "video",
        date=date,
        stream_date=date,
        title=title,
        id=src.id or "video",
        site=getattr(src, "site", "generic"),
    )
    try:
        raw = tpl.format_map(data)
    except (KeyError, ValueError, AttributeError, TypeError, IndexError):
        raw = f"{data['uploader']} - {data['date']} - {data['title']} [{data['id']}]"

    cleaned = re.sub(r"\s+-\s+-\s+", " - ", raw)
    cleaned = safe_name(cleaned)
    return cleaned or "video"

def part_stem(src: SourceInfo, opts: JobOptions, part: Part, total: int, clip: dict | None = None) -> str:
    tag = format_duration_tag

    resolved_q = resolve_format(src.formats, getattr(opts, "quality", QUALITY_BEST)) if getattr(src, "formats", None) else None
    q_tag = resolved_q.tag if resolved_q else ""

    stream_date = src.date or ""
    year, month, day = date_components(src.date)
    download_date = datetime.now().strftime("%Y-%m-%d")
    game = dominant_game(getattr(src, "segments", None), part.start, part.end)
    duration_str = tag(max(0.0, part.end - part.start))
    site = getattr(src, "site", "twitch") or "twitch"

    data = _SafeDict(
        streamer=src.uploader or "vod",
        uploader=src.uploader or "video",
        author=src.uploader or "video",
        channel=src.uploader or "video",
        site=site,
        provider=site,
        stream_date=stream_date,
        download_date=download_date,
        date=stream_date,
        year=year,
        month=month,
        day=day,
        game=game,
        category=game,
        id=src.twitch_vod_id or src.id,
        title=src.title,
        duration=duration_str,
        n=part.index,
        total=total,
        start=tag(part.start),
        end=tag(part.end),
        quality=q_tag,
        resolution=q_tag,
    )
    is_twitch = bool(src.twitch_vod_id or getattr(src, "site", "twitch") == "twitch")
    template = getattr(opts, "generic_name_template", None) if not is_twitch else opts.name_template
    if not template:
        template = opts.name_template
    if clip:  # single clip download: the clip's own name instead of the stream's
        data.update(
            clip_title=clip.get("title") or "Clip",
            creator=clip.get("creator_name", ""),
            views=clip.get("view_count", 0),
            clip_id=clip.get("id", ""),
            clip_duration=round(clip.get("duration", 0) or 0),
        )
        template = opts.clip_name_template
    try:
        name = template.format_map(data)
    except (KeyError, ValueError, AttributeError, TypeError, IndexError):
        name = data["clip_title"] if clip else (f"{data['id']}" if total == 1 else f"{data['id']} - part{part.index}")
    name = safe_name(name)
    if clip:
        name = name[:150].strip(" .")
        return name or f"clip {data['clip_id']}".strip()

    if total == 1:
        cleaned = re.sub(r"(?i)[\s\-_]+part\s*1\b", "", name)
        cleaned = re.sub(r"(?i)\bpart\s*1[\s\-_]*", "", cleaned)
        cleaned = re.sub(r"(?i)[\s\-_]+1\s*of\s*1\b", "", cleaned)
        cleaned = re.sub(r"(?i)\b1\s*of\s*1[\s\-_]*", "", cleaned)
        cleaned = safe_name(cleaned)
        if cleaned:
            name = cleaned

    return name or f"part{part.index}"


def stream_dir(src: SourceInfo, opts: JobOptions) -> Path:
    """Where the files of this VOD go: out_dir/<streamer>/<stream>/ (or out_dir if disabled)."""
    from core.routing import resolve_provider_base_dir

    site = getattr(src, "site", "twitch") or "twitch"
    base = resolve_provider_base_dir(
        opts.out_dir,
        site_or_provider=site,
        provider_subfolders=getattr(opts, "provider_subfolders", False),
        provider_out_dirs=getattr(opts, "provider_out_dirs", None),
    )
    if not opts.subfolders:
        return base

    resolved_q = resolve_format(src.formats, getattr(opts, "quality", QUALITY_BEST)) if getattr(src, "formats", None) else None
    q_tag = resolved_q.tag if resolved_q else ""

    stream_date = src.date or ""
    year, month, day = date_components(src.date)
    download_date = datetime.now().strftime("%Y-%m-%d")
    duration_val = getattr(src, "duration", 0.0) or 0.0
    game = dominant_game(getattr(src, "segments", None), 0.0, duration_val)
    duration_str = format_duration_tag(duration_val)

    data = _SafeDict(
        streamer=src.uploader or "vod",
        uploader=src.uploader or "video",
        author=src.uploader or "video",
        channel=src.uploader or "video",
        site=site,
        provider=site,
        stream_date=stream_date,
        download_date=download_date,
        date=stream_date,
        year=year,
        month=month,
        day=day,
        game=game,
        category=game,
        id=src.twitch_vod_id or src.id,
        title=src.title,
        duration=duration_str,
        quality=q_tag,
        resolution=q_tag,
    )
    try:
        stream = opts.folder_template.format_map(data)
    except (KeyError, ValueError, AttributeError, TypeError, IndexError):
        stream = f"{data['date']} - {data['id']}"
    stream = safe_name(stream)[:100].strip(" .") or str(data["id"])
    streamer = safe_name(src.uploader)[:60].strip(" .") or "vod"
    return base / streamer / stream


def finalize_part(
    ctx: Ctx,
    src_file: Path,
    dest_stem: Path,
    container: str,
    chapters: list[Chapter],
    tags: dict[str, str],
    total: float,
    copy_instead_of_move: bool = False,
    *,
    deps: PipelineDeps | None = None,
) -> Path:
    """Put the part in its final place: add chapters / remux / rename."""
    _uniq = getattr(deps, "unique_path", None) or resolve_dep("unique_path", _ORIG_UNIQUE_PATH, unique_path)
    _run_ff = getattr(deps, "run_ffmpeg", None) or resolve_dep("run_ffmpeg", _ORIG_RUN_FFMPEG, run_ffmpeg)

    dest = _uniq(dest_stem.parent / f"{dest_stem.name}.{container}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if chapters:
        meta = src_file.with_suffix(".ffmeta")
        meta.write_text(ffmetadata(chapters, tags), encoding="utf-8")
        _run_ff(
            ctx,
            ["-i", str(src_file), "-i", str(meta), "-map", "0", "-map_metadata", "1", "-map_chapters", "1", "-c", "copy",
             *mp4_flags(container), str(dest)],
            total=total,
        )
    elif src_file.suffix.lower() == "." + container:
        ts = mp4_movie_timescale(src_file) if container.lower() == "mp4" else None
        if ts is not None and ts != MP4_MOVIE_TIMESCALE:
            # e.g. a file made by yt-dlp's own ffmpeg: rewrite the header only (stream copy), then drop the source
            _run_ff(ctx, ["-i", str(src_file), "-map", "0", "-c", "copy", *mp4_flags(container), str(dest)], total=total)
            if not copy_instead_of_move:
                src_file.unlink(missing_ok=True)
        else:
            (shutil.copy2 if copy_instead_of_move else shutil.move)(str(src_file), str(dest))
    else:
        _run_ff(ctx, ["-i", str(src_file), "-map", "0", "-c", "copy", *mp4_flags(container), str(dest)], total=total)
    return dest


def finalize_audio_part(
    ctx: Ctx,
    src_file: Path,
    dest_stem: Path,
    container: str,
    chapters: list[Chapter],
    tags: dict[str, str],
    total: float,
    copy_instead_of_move: bool = False,
    *,
    deps: PipelineDeps | None = None,
) -> Path:
    """Put an audio-only part in its final place as .m4a (copy) or .mp3 (convert)."""
    _uniq = getattr(deps, "unique_path", None) or resolve_dep("unique_path", _ORIG_UNIQUE_PATH, unique_path)
    _run_ff = getattr(deps, "run_ffmpeg", None) or resolve_dep("run_ffmpeg", _ORIG_RUN_FFMPEG, run_ffmpeg)

    dest = _uniq(dest_stem.parent / f"{dest_stem.name}.{container}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not chapters and container == "m4a" and src_file.suffix.lower() == ".m4a":
        (shutil.copy2 if copy_instead_of_move else shutil.move)(str(src_file), str(dest))
        return dest
    args = ["-i", str(src_file)]
    if chapters:
        meta = src_file.with_suffix(".ffmeta")
        meta.write_text(ffmetadata(chapters, tags), encoding="utf-8")
        args += ["-i", str(meta), "-map_metadata", "1", "-map_chapters", "1"]
    args += ["-map", "0:a:0", *audio_codec_args(container)]
    if container == "mp3":
        args += ["-id3v2_version", "3"]
    _run_ff(ctx, args + [str(dest)], total=total)
    return dest


def _write_sidecar(dest: Path, chapters: list[Chapter]) -> None:
    data = [
        {
            "start": round(ch.start, 2),
            "end": round(ch.end, 2),
            "title": ch.title,
            "clips": [
                {
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "creator": c.get("creator_name"),
                    "views": c.get("view_count"),
                    "duration": c.get("duration"),
                    "url": c.get("url"),
                }
                for c in ch.clips
            ],
        }
        for ch in chapters
    ]
    dest.with_suffix(".clips.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def split_copy(
    ctx: Ctx,
    full: Path,
    parts: list[Part],
    duration: float,
    container: str,
    workdir: Path,
    audio_only: bool = False,
    *,
    deps: PipelineDeps | None = None,
) -> dict[int, tuple[Path, float, float]]:
    """
    Single ffmpeg pass (stream copy) that cuts the full file at every boundary.
    Returns {part.index: (segment_file, real_start, real_end)} in VOD time.
    (ffmpeg normalises the input timeline to start at 0, so the times are VOD time
    even if the downloaded file's own timestamps start somewhere else.)
    Segments that are not part of any wanted part (gaps) are deleted.
    """
    _run_ff = getattr(deps, "run_ffmpeg", None) or resolve_dep("run_ffmpeg", _ORIG_RUN_FFMPEG, run_ffmpeg)

    boundaries = sorted({0.0} | {p.start for p in parts} | {p.end for p in parts if p.end < duration - 0.5})
    inner = boundaries[1:]

    if not inner:  # whole video is a single part
        return {parts[0].index: (full, 0.0, duration)}

    ctx.log(t("Splitting into {count} part(s) using stream copy…").format(count=len(parts)))
    seg_dir = workdir / "segments"
    if seg_dir.exists():
        shutil.rmtree(seg_dir)
    seg_dir.mkdir(parents=True)
    listing = seg_dir / "list.csv"
    times = ",".join(f"{b:.3f}" for b in inner)
    map_args = ["-map", "0:a:0"] if audio_only else ["-map", "0:v:0", "-map", "0:a?"]
    _run_ff(
        ctx,
        [
            "-i", str(full),
            *map_args,
            "-c", "copy",
            "-f", "segment",
            *(["-segment_format_options", f"movie_timescale={MP4_MOVIE_TIMESCALE}"] if mp4_flags(container) else []),
            *(["-segment_format", "mp4"] if audio_only else []),
            "-segment_times", times,
            "-segment_list", str(listing),
            "-segment_list_type", "csv",
            "-reset_timestamps", "1",
            str(seg_dir / f"seg_%03d.{container}"),
        ],
        total=duration,
    )
    rows = [r for r in csv.reader(listing.read_text(encoding="utf-8").splitlines()) if len(r) >= 3]
    result: dict[int, tuple[Path, float, float]] = {}
    for p in parts:
        i = boundaries.index(p.start)
        if i >= len(rows):
            raise EngineError(t("Cut point {point} is past the end of the downloaded video.").format(point=fmt_hms(p.start)))
        name, s, e = rows[i][0], float(rows[i][1]), float(rows[i][2])
        result[p.index] = (seg_dir / Path(name).name, s, e)
    return result


def cut_exact(
    ctx: Ctx,
    full: Path,
    part: Part,
    container: str,
    workdir: Path,
    offset: float | None = None,
    *,
    deps: PipelineDeps | None = None,
) -> Path:
    """
    Frame-exact cut (re-encodes video).
    `offset`: where the part starts inside `full` (default: part.start, i.e. `full` is the whole VOD).
    """
    _run_ff = getattr(deps, "run_ffmpeg", None) or resolve_dep("run_ffmpeg", _ORIG_RUN_FFMPEG, run_ffmpeg)

    out = workdir / f"exact_{part.index}.{container}"
    _run_ff(
        ctx,
        [
            "-ss", f"{part.start if offset is None else offset:.3f}", "-i", str(full), "-t", f"{part.duration:.3f}",
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            *mp4_flags(container),
            str(out),
        ],
        total=part.duration,
    )
    return out


# --------------------------------------------------------------------------- #
# Running a job
# --------------------------------------------------------------------------- #
def _load_chapters(ctx: Ctx, job: Job, *, deps: PipelineDeps | None = None) -> list[Chapter]:
    if not (job.opts.chapters or job.opts.premiere_xml or job.opts.premiere_plugin):
        return []
    clips = job.clips
    if clips is None:
        if not job.source.has_capability(Capability.TIMELINE) or not job.source.twitch_vod_id:
            ctx.log(t("Chapters: not a Twitch VOD URL, skipping."))
            return []
        if job.client is None:
            ctx.log(t("Chapters: no Twitch API credentials, skipping."))
            return []
        ctx.log(t("Fetching clips for chapters…"))
        clips = fetch_clips_for_vod(job.client, job.source.twitch_vod_id)
    _make_ch = getattr(deps, "make_chapters", None) or resolve_dep("make_chapters", _ORIG_MAKE_CHAPTERS, make_chapters)
    chapters = _make_ch(clips, job.opts.clip_filter)
    ctx.log(t("Chapters: {chapters} (from {clips} clips found)").format(chapters=len(chapters), clips=len(clips)))
    return chapters


def _load_muted(ctx: Ctx, job: Job, *, deps: PipelineDeps | None = None) -> list[Chapter]:
    """The stretches Twitch silenced, as chapters, when the .markers.json should carry them (else [])."""
    src, opts = job.source, job.opts
    if not (opts.muted_markers and opts.premiere_plugin) or job.single_clip:
        return []
    if not src.has_capability(Capability.TIMELINE):
        return []
    ranges = src.muted  # normally read at «Get info»
    _get_pl = getattr(deps, "get_playlist_url", None) or resolve_dep("get_playlist_url", _ORIG_GET_PLAYLIST_URL, get_playlist_url)
    _muted_pl = getattr(deps, "muted_from_playlist_url", None) or resolve_dep(
        "muted_from_playlist_url", _ORIG_MUTED_FROM_PLAYLIST_URL, muted_from_playlist_url
    )

    if ranges is None and src.twitch_vod_id:  # it could not be read then (or the VOD came from elsewhere): try once more
        try:
            ranges = _muted_pl(_get_pl(ctx, src.url), src.duration)
        except Cancelled:
            raise
        except EngineError:
            ranges = None
    if ranges is None:
        ctx.log(t("Muted audio: could not read which parts Twitch silenced, so no muted markers this time."))
        return []
    if ranges:
        def _dur(r):
            if isinstance(r, (tuple, list)) and len(r) >= 2:
                return float(r[1]) - float(r[0])
            if isinstance(r, dict):
                return float(r.get("end", 0.0)) - float(r.get("start", 0.0))
            if hasattr(r, "duration"):
                return float(r.duration)
            if hasattr(r, "start") and hasattr(r, "end"):
                return float(r.end) - float(r.start)
            return 0.0
        ctx.log(t("Muted audio: {count} stretch(es), {total} in total").format(count=len(ranges), total=fmt_hms(sum(_dur(r) for r in ranges))))
    return muted_chapters(ranges)


_ORIG_FINALIZE_PART = finalize_part
_ORIG_FINALIZE_AUDIO_PART = finalize_audio_part
_ORIG_SPLIT_COPY = split_copy
_ORIG_CUT_EXACT = cut_exact
_ORIG_LOAD_CHAPTERS = _load_chapters
_ORIG_LOAD_MUTED = _load_muted


def run_job(job: Job, ctx: Ctx, *, deps: PipelineDeps | None = None) -> list[Path]:
    src, opts = job.source, job.opts
    _find = getattr(deps, "find_tool", None) or resolve_dep("find_tool", _ORIG_FIND_TOOL, find_tool)
    _dl_full = getattr(deps, "download_full", None) or resolve_dep("download_full", _ORIG_DOWNLOAD_FULL, download_full)
    _dl_sec = getattr(deps, "download_section", None) or resolve_dep("download_section", _ORIG_DOWNLOAD_SECTION, download_section)
    _dl_align = getattr(deps, "download_section_aligned", None) or resolve_dep(
        "download_section_aligned", _ORIG_DOWNLOAD_SECTION_ALIGNED, download_section_aligned
    )
    _cut = getattr(deps, "cut_exact", None) or resolve_dep("cut_exact", _ORIG_CUT_EXACT, cut_exact)
    _split = getattr(deps, "split_copy", None) or resolve_dep("split_copy", _ORIG_SPLIT_COPY, split_copy)
    _fin_part = getattr(deps, "finalize_part", None) or resolve_dep("finalize_part", _ORIG_FINALIZE_PART, finalize_part)
    _fin_audio = getattr(deps, "finalize_audio_part", None) or resolve_dep(
        "finalize_audio_part", _ORIG_FINALIZE_AUDIO_PART, finalize_audio_part
    )
    _ensure_tdcli = getattr(deps, "ensure_tdcli", None) or resolve_dep("ensure_tdcli", _ORIG_ENSURE_TDCLI, ensure_tdcli)
    _probe = getattr(deps, "probe_video", None) or resolve_dep("probe_video", _ORIG_PROBE_VIDEO, probe_video)
    _write_xml = getattr(deps, "write_premiere_xml", None) or resolve_dep(
        "write_premiere_xml", _ORIG_WRITE_PREMIERE_XML, write_premiere_xml
    )
    _write_json = getattr(deps, "write_markers_json", None) or resolve_dep(
        "write_markers_json", _ORIG_WRITE_MARKERS_JSON, write_markers_json
    )
    _load_ch = getattr(deps, "load_chapters", None) or resolve_dep("_load_chapters", _ORIG_LOAD_CHAPTERS, _load_chapters)
    _load_mut = getattr(deps, "load_muted", None) or resolve_dep("_load_muted", _ORIG_LOAD_MUTED, _load_muted)
    _uniq = getattr(deps, "unique_path", None) or resolve_dep("unique_path", _ORIG_UNIQUE_PATH, unique_path)

    if not _find("ffmpeg"):
        raise EngineError(t("ffmpeg was not found. Install it and add it to PATH."))

    if not src.has_capability(Capability.TIMELINE):
        if opts.cut_text and opts.cut_text.strip():
            plan = make_plan(opts.cut_text, src.duration, opts.strategy, opts.full_threshold)
        else:
            dur = max(1.0, float(src.duration or 1.0))
            plan = Plan(parts=[Part(index=1, start=0.0, end=dur)], strategy="full", coverage=1.0, duration=src.duration or 0.0)
    else:
        plan = make_plan(opts.cut_text, src.duration, opts.strategy, opts.full_threshold)
    ctx.log(
        f"{len(plan.parts)} part(s), coverage {plan.coverage * 100:.0f}% → "
        + ("download full VOD, then split" if plan.strategy == "full" else "download only the parts")
    )
    fmt = resolve_format(src.formats, opts.quality)
    if not src.has_capability(Capability.TIMELINE):
        from core.source_info import build_generic_format_string
        fmt_str = build_generic_format_string(quality=opts.quality, audio_only=bool(fmt and fmt.audio_only))
        fmt_kw = {"format_id": fmt_str}
    else:
        fmt_kw = {"format_id": fmt.format_id} if fmt else {}
    if fmt:
        ctx.log(describe_quality(fmt, opts.quality))
    elif (opts.quality or "").strip().lower() not in ("", QUALITY_BEST):
        ctx.log(t("Quality: this video offers no choice, using the best one."))

    audio_only = bool(fmt and fmt.audio_only)
    dl_kw = {**fmt_kw, **({"audio_only": True} if audio_only else {})}
    out_container = audio_out_container(opts) if audio_only else opts.container
    if audio_only:
        opts, skipped = audio_only_options(opts)
        job = replace(job, opts=opts)  # _load_chapters reads job.opts
        if skipped:
            ctx.log("Audio only: skipped " + ", ".join(skipped) + " (they need a video track).")
    chapters_all = _load_ch(ctx, job)
    games_all = game_chapters(src.segments) if opts.game_markers and not job.single_clip and src.has_capability(Capability.SEGMENTS) else []
    muted_all = _load_mut(ctx, job)
    chat_tool: str | None = None
    if (opts.chat or opts.chat_render) and not job.single_clip:
        what = "Chat download" if opts.chat else "Chat overlay"
        if not src.has_capability(Capability.CHAT) or not src.twitch_vod_id:
            ctx.log(t("{what} skipped: it only works for Twitch VODs.").format(what=what))
        else:
            try:
                chat_tool = _ensure_tdcli(ctx)
            except Cancelled:
                raise
            except EngineError as e:
                ctx.log(t("{what} skipped (the video is still downloaded): {error}").format(what=what, error=e))

    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filesize = getattr(fmt, "filesize", 0) or 0
    if filesize > 0:
        required_bytes = int(filesize * (2.1 if len(plan.parts) > 1 else 1.1))
    else:
        required_bytes = 200 * 1024 * 1024
    check_disk_space(out_dir, required_bytes)
    final_dir = stream_dir(src, opts)
    workdir = compute_job_workdir(src, opts, fmt=fmt, out_dir=out_dir)
    if (workdir / ".running").exists():
        import uuid
        workdir = workdir.with_name(f"{workdir.name}_{os.getpid()}_{uuid.uuid4().hex[:6]}")
    workdir.mkdir(parents=True, exist_ok=True)
    lock_file = workdir / ".running"
    try:
        lock_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    if not workdir.resolve().is_relative_to(out_dir.resolve()):
        raise EngineError(t("Unsafe work directory path"))
    tags = {
        "title": src.title,
        "artist": src.uploader,
        "comment": src.url,
        "date": src.date,
    }
    total_parts = len(plan.parts)
    results: list[Path] = []

    def finish(part: Part, file: Path, real_start: float, real_end: float, copy: bool = False) -> None:
        clip_chs = chapters_for_part(chapters_all, real_start, real_end)
        n_clip_chapters = len(clip_chs) if opts.chapters else 0
        chs = fill_gaps(clip_chs, real_end - real_start, opts.clip_filter.gap_title) if opts.chapters else []
        stem = final_dir / part_stem(src, opts, part, total_parts, job.single_clip)
        media_tags = dict(tags)
        if job.single_clip:
            media_tags["title"] = job.single_clip.get("title") or src.title
            media_tags["comment"] = job.single_clip.get("url") or src.url
        elif total_parts > 1:
            media_tags["title"] = f"{src.title} (part {part.index}/{total_parts})".strip()
        else:
            media_tags["title"] = src.title.strip()
        finalize_fn = _fin_audio if audio_only else _fin_part
        dest_filename = f"{stem.name}.{out_container}"
        ctx.log(t("Saving {name}…").format(name=dest_filename))
        dest = finalize_fn(ctx, file, stem, out_container, chs, media_tags, real_end - real_start, copy)
        if opts.sidecar and n_clip_chapters:
            _write_sidecar(dest, [c for c in chs if c.clips])
        ctx.log(f"✔ {dest.name}" + (f"  ({n_clip_chapters} clip chapters)" if n_clip_chapters else ""))
        game_chs = chapters_for_part(games_all, real_start, real_end)
        muted_chs = chapters_for_part(muted_all, real_start, real_end)
        # Two separate outputs. The XML is the plain import (no colors). The JSON is for the plugin. Game markers
        # alone still give the XML, as before, unless the plugin file is on (then they go there).
        xml_clips = clip_chs if opts.premiere_xml else []
        json_clips = clip_chs if opts.premiere_plugin else []
        want_xml = opts.premiere_xml or (opts.game_markers and not opts.premiere_plugin)
        if (want_xml and (xml_clips or game_chs)) or (opts.premiere_plugin and (json_clips or game_chs or muted_chs)):
            probe = _probe(dest)
            if probe is None:
                ctx.log(t("Could not read the frame rate with ffprobe; assuming 30 fps for the Premiere markers."))
            fps, w, h = probe or (30.0, 1920, 1080)

            def marker_bits(clips: list[Chapter], muted: list[Chapter] | None = None) -> str:
                return " + ".join(([f"{len(clips)} clip markers"] if clips else [])
                                  + ([f"{len(game_chs)} game markers"] if game_chs else [])
                                  + ([f"{len(muted)} muted markers"] if muted else []))

            if want_xml and (xml_clips or game_chs):
                markers = sorted(xml_clips + game_chs, key=lambda c: (c.start, c.kind))
                xml = _write_xml(dest, markers, real_end - real_start, fps, w, h)
                ctx.log(t("✔ {name}  ({markers} for Premiere Pro, {fps:g} fps)").format(name=xml.name, markers=marker_bits(xml_clips), fps=fps))
            if opts.premiere_plugin and (json_clips or game_chs or muted_chs):
                markers = sorted(json_clips + game_chs + muted_chs, key=lambda c: (c.start, c.kind))
                prefs = {
                    "pad_before": float(getattr(opts.clip_filter, "pad_before", 0) or 0),
                    "pad_after": float(getattr(opts.clip_filter, "pad_after", 0) or 0),
                }
                mj = _write_json(dest, markers, real_end - real_start, fps, src, real_start, real_end, preferences=prefs)
                ctx.log(t("✔ {name}  ({markers} for the Premiere plugin, {fps:g} fps)").format(name=mj.name, markers=marker_bits(json_clips, muted_chs), fps=fps))
        if chat_tool:
            chat_files_for_part(ctx, chat_tool, src, opts, part, total_parts, dest, real_start, real_end, workdir)
        results.append(dest)

    rate_limit = getattr(opts, "rate_limit", "")
    rate_kw = {"rate_limit": rate_limit} if rate_limit else {}
    cookies_browser = getattr(opts, "cookies_browser", None)
    cookies_kw = {"cookies_browser": cookies_browser} if cookies_browser else {}
    download_archive = str(getattr(opts, "download_archive", "") or "").strip()

    def _supports_kw(fn, key: str) -> bool:
        try:
            params = inspect.signature(fn).parameters.values()
            return any(p.kind == inspect.Parameter.VAR_KEYWORD or p.name == key for p in params)
        except (ValueError, TypeError):
            return True

    full_archive_kw = {"download_archive": download_archive} if (download_archive and _supports_kw(_dl_full, "download_archive")) else {}
    sec_archive_kw = {"download_archive": download_archive} if (download_archive and _supports_kw(_dl_sec, "download_archive")) else {}
    full_age_kw = {"is_age_restricted": getattr(src, "is_age_restricted", False)} if _supports_kw(_dl_full, "is_age_restricted") else {}
    sec_age_kw = {"is_age_restricted": getattr(src, "is_age_restricted", False)} if _supports_kw(_dl_sec, "is_age_restricted") else {}

    if plan.strategy == "full":
        ctx.stage(0.0, 0.85, t("Downloading VOD"))
        ctx.log(t("Downloading full video…"))
        try:
            full = _dl_full(ctx, src.url, workdir, opts.threads, **fmt_kw, **rate_kw, **cookies_kw, **full_archive_kw, **full_age_kw)
        except ArchiveSkippedError as e:
            ctx.log(str(e))
            shutil.rmtree(workdir, ignore_errors=True)
            ctx.stage(1.0, 1.0, "Done")
            return results
        ctx.stage(0.85, 1.0, t("Cutting"))
        ctx.log(t("Cutting video into parts with ffmpeg…"))
        if opts.exact:
            for i, p in enumerate(plan.parts):
                ctx.stage(0.85 + 0.15 * i / total_parts, 0.85 + 0.15 * (i + 1) / total_parts, t("Re-encoding part {part}/{total}").format(part=p.index, total=total_parts))
                cut = _cut(ctx, full, p, opts.container, workdir)
                finish(p, cut, p.start, p.end)
        else:
            split_container = "m4a" if audio_only else opts.container
            split_kw = {"audio_only": True} if audio_only else {}
            segs = _split(ctx, full, plan.parts, src.duration, split_container, workdir, **split_kw)
            only_full = len(plan.parts) == 1 and segs[plan.parts[0].index][0] == full
            for i, p in enumerate(plan.parts):
                f, s, e = segs[p.index]
                ctx.stage(0.85 + 0.15 * i / total_parts, 0.85 + 0.15 * (i + 1) / total_parts, t("Finishing part {part}/{total}").format(part=p.index, total=total_parts))
                finish(p, f, s, e, copy=only_full and opts.keep_full)
        if opts.keep_full and full.exists():
            final_dir.mkdir(parents=True, exist_ok=True)
            stem = final_dir / safe_name(f"{src.uploader} - {src.date} - {src.twitch_vod_id or src.id} - FULL")
            full_suffix = ".m4a" if (audio_only and full.suffix.lower() == ".mp4") else full.suffix
            kept = _uniq(stem.parent / f"{stem.name}{full_suffix}")
            shutil.move(str(full), str(kept))
            ctx.log(t("Kept full VOD: {name}").format(name=kept.name))
    else:
        for i, p in enumerate(plan.parts):
            ctx.check_cancel()
            lo, hi = i / total_parts, (i + 1) / total_parts
            ctx.stage(lo, lo + (hi - lo) * 0.9, t("Downloading part {part}/{total}").format(part=p.index, total=total_parts))
            use_aligned = (
                getattr(src, "site", "twitch") == "twitch"
                and getattr(src, "twitch_vod_id", None)
                and src.has_capability(Capability.TIMELINE)
            )
            aligned = _dl_align(ctx, src.url, p, workdir, **dl_kw) if use_aligned else None
            if aligned:
                f, real_start, real_end = aligned
                early = p.start - real_start
                ctx.log(
                    f"Part {p.index} starts at {fmt_hms(real_start)} (asked {fmt_hms(p.start)}"
                    + (f", {early:.0f} s early" if early >= 0.5 else "")
                    + f") and ends at {fmt_hms(real_end)}"
                )
                if opts.exact:
                    ctx.stage(lo + (hi - lo) * 0.9, hi, f"Re-encoding part {p.index}/{total_parts}")
                    f = _cut(ctx, f, p, opts.container, workdir, offset=max(0.0, p.start - real_start))
                    real_start, real_end = p.start, p.end
            else:
                try:
                    f = _dl_sec(ctx, src.url, p, workdir, opts.threads, opts.exact, **fmt_kw, **rate_kw, **cookies_kw, **sec_archive_kw, **sec_age_kw)
                except ArchiveSkippedError as e:
                    ctx.log(str(e))
                    continue
                real_start, real_end = p.start, p.end
            ctx.stage(lo + (hi - lo) * 0.9, hi, f"Finishing part {p.index}/{total_parts}")
            finish(p, f, real_start, real_end)

    shutil.rmtree(workdir, ignore_errors=True)
    try:
        if lock_file.exists():
            lock_file.unlink()
    except OSError:
        pass
    ctx.stage(1.0, 1.0, "Done")
    try:
        from core import history
        vod_id = src.twitch_vod_id or src.id
        if vod_id and results:
            history.record_download({
                "vod_id": vod_id,
                "title": src.title,
                "streamer": src.uploader,
                "date": src.date,
                "parts": len(results),
                "folder": str(final_dir),
                "quality": getattr(opts, "quality", "") or "Best available",
                "site": getattr(src, "site", "twitch") or "twitch",
                "url": getattr(src, "url", "") or "",
            })
    except Exception:
        pass
    return results
