"""
Splitting, finalizing, path naming, and high-level job runner.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

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
from core.errors import Cancelled, EngineError
from core.i18n import t
from core.job import Job, JobOptions
from core.providers import Capability
from core.muted import muted_from_playlist_url
from core.planning import Part, Plan, make_plan
from core.premiere_export import probe_video, write_markers_json, write_premiere_xml
from core.runtime import Ctx, find_tool
from core.source_info import (
    GameSegment,
    QUALITY_BEST,
    SourceInfo,
    describe_quality,
    resolve_format,
)
from core.timeutil import fmt_hms
from core.tools import ensure_tdcli
from core.twitch_api import fetch_clips_for_vod


# --------------------------------------------------------------------------- #
# Splitting / finalizing helpers & naming
# --------------------------------------------------------------------------- #
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


def safe_name(text: str) -> str:
    """Strip emojis / illegal characters so the name is safe everywhere."""
    text = re.sub(r"[\U00010000-\U0010ffff]", " ", text)
    text = re.sub(r"[^\w\s\-\.\(\)\[\]]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip(" .")


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
    except (ValueError, IndexError):
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
    except (ValueError, IndexError):
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
    except (ValueError, IndexError):
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
) -> Path:
    """Put the part in its final place: add chapters / remux / rename."""
    eng = sys.modules.get("luckytwitch_engine")
    _uniq = getattr(eng, "unique_path", unique_path) if eng else unique_path
    _run_ff = getattr(eng, "run_ffmpeg", run_ffmpeg) if eng else run_ffmpeg

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
) -> Path:
    """Put an audio-only part in its final place as .m4a (copy) or .mp3 (convert)."""
    eng = sys.modules.get("luckytwitch_engine")
    _uniq = getattr(eng, "unique_path", unique_path) if eng else unique_path
    _run_ff = getattr(eng, "run_ffmpeg", run_ffmpeg) if eng else run_ffmpeg

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
    ctx: Ctx, full: Path, parts: list[Part], duration: float, container: str, workdir: Path, audio_only: bool = False
) -> dict[int, tuple[Path, float, float]]:
    """
    Single ffmpeg pass (stream copy) that cuts the full file at every boundary.
    Returns {part.index: (segment_file, real_start, real_end)} in VOD time.
    (ffmpeg normalises the input timeline to start at 0, so the times are VOD time
    even if the downloaded file's own timestamps start somewhere else.)
    Segments that are not part of any wanted part (gaps) are deleted.
    """
    eng = sys.modules.get("luckytwitch_engine")
    _run_ff = getattr(eng, "run_ffmpeg", run_ffmpeg) if eng else run_ffmpeg

    boundaries = sorted({0.0} | {p.start for p in parts} | {p.end for p in parts if p.end < duration - 0.5})
    inner = boundaries[1:]

    if not inner:  # whole video is a single part
        return {parts[0].index: (full, 0.0, duration)}

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


def cut_exact(ctx: Ctx, full: Path, part: Part, container: str, workdir: Path, offset: float | None = None) -> Path:
    """
    Frame-exact cut (re-encodes video).
    `offset`: where the part starts inside `full` (default: part.start, i.e. `full` is the whole VOD).
    """
    eng = sys.modules.get("luckytwitch_engine")
    _run_ff = getattr(eng, "run_ffmpeg", run_ffmpeg) if eng else run_ffmpeg

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
def _load_chapters(ctx: Ctx, job: Job) -> list[Chapter]:
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
    eng = sys.modules.get("luckytwitch_engine")
    _make_ch = getattr(eng, "make_chapters", make_chapters) if eng else make_chapters
    chapters = _make_ch(clips, job.opts.clip_filter)
    ctx.log(t("Chapters: {chapters} (from {clips} clips found)").format(chapters=len(chapters), clips=len(clips)))
    return chapters


def _load_muted(ctx: Ctx, job: Job) -> list[Chapter]:
    """The stretches Twitch silenced, as chapters, when the .markers.json should carry them (else [])."""
    src, opts = job.source, job.opts
    if not (opts.muted_markers and opts.premiere_plugin) or job.single_clip:
        return []
    if not src.has_capability(Capability.TIMELINE):
        return []
    ranges = src.muted  # normally read at «Get info»
    eng = sys.modules.get("luckytwitch_engine")
    _get_pl = getattr(eng, "get_playlist_url", get_playlist_url) if eng else get_playlist_url
    _muted_pl = getattr(eng, "muted_from_playlist_url", muted_from_playlist_url) if eng else muted_from_playlist_url

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
        ctx.log(t("Muted audio: {count} stretch(es), {total} in total").format(count=len(ranges), total=fmt_hms(sum(e - s for s, e in ranges))))
    return muted_chapters(ranges)


def run_job(job: Job, ctx: Ctx) -> list[Path]:
    src, opts = job.source, job.opts
    eng = sys.modules.get("luckytwitch_engine")
    import core.tools
    _find = find_tool if find_tool is not getattr(core.tools, "find_tool", None) else (getattr(eng, "find_tool", find_tool) if eng else find_tool)
    _dl_full = getattr(eng, "download_full", download_full) if eng else download_full
    _dl_sec = getattr(eng, "download_section", download_section) if eng else download_section
    _dl_align = getattr(eng, "download_section_aligned", download_section_aligned) if eng else download_section_aligned
    _cut = getattr(eng, "cut_exact", cut_exact) if eng else cut_exact
    _split = getattr(eng, "split_copy", split_copy) if eng else split_copy
    _fin_part = getattr(eng, "finalize_part", finalize_part) if eng else finalize_part
    _fin_audio = getattr(eng, "finalize_audio_part", finalize_audio_part) if eng else finalize_audio_part
    _ensure_tdcli = getattr(eng, "ensure_tdcli", ensure_tdcli) if eng else ensure_tdcli
    _probe = getattr(eng, "probe_video", probe_video) if eng else probe_video
    _write_xml = getattr(eng, "write_premiere_xml", write_premiere_xml) if eng else write_premiere_xml
    _write_json = getattr(eng, "write_markers_json", write_markers_json) if eng else write_markers_json
    _load_ch = getattr(eng, "_load_chapters", _load_chapters) if eng else _load_chapters
    _load_mut = getattr(eng, "_load_muted", _load_muted) if eng else _load_muted
    _uniq = getattr(eng, "unique_path", unique_path) if eng else unique_path

    if not _find("ffmpeg"):
        raise EngineError(t("ffmpeg was not found. Install it and add it to PATH."))

    if not src.has_capability(Capability.TIMELINE):
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
    final_dir = stream_dir(src, opts)
    workdir = out_dir / (
        f".luckytwitch_{src.twitch_vod_id or src.id}"
        + (f"_{fmt.format_id}" if fmt else "")
    )
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

    if plan.strategy == "full":
        ctx.stage(0.0, 0.85, "Downloading VOD")
        full = _dl_full(ctx, src.url, workdir, opts.threads, **fmt_kw, **rate_kw, **cookies_kw)
        ctx.stage(0.85, 1.0, "Cutting")
        if opts.exact:
            for i, p in enumerate(plan.parts):
                ctx.stage(0.85 + 0.15 * i / total_parts, 0.85 + 0.15 * (i + 1) / total_parts, f"Re-encoding part {p.index}/{total_parts}")
                cut = _cut(ctx, full, p, opts.container, workdir)
                finish(p, cut, p.start, p.end)
        else:
            split_container = "m4a" if audio_only else opts.container
            split_kw = {"audio_only": True} if audio_only else {}
            segs = _split(ctx, full, plan.parts, src.duration, split_container, workdir, **split_kw)
            only_full = len(plan.parts) == 1 and segs[plan.parts[0].index][0] == full
            for i, p in enumerate(plan.parts):
                f, s, e = segs[p.index]
                ctx.stage(0.85 + 0.15 * i / total_parts, 0.85 + 0.15 * (i + 1) / total_parts, f"Finishing part {p.index}/{total_parts}")
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
            ctx.stage(lo, lo + (hi - lo) * 0.9, f"Downloading part {p.index}/{total_parts}")
            aligned = _dl_align(ctx, src.url, p, workdir, **dl_kw)
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
                f = _dl_sec(ctx, src.url, p, workdir, opts.threads, opts.exact, **fmt_kw, **rate_kw)
                real_start, real_end = p.start, p.end
            ctx.stage(lo + (hi - lo) * 0.9, hi, f"Finishing part {p.index}/{total_parts}")
            finish(p, f, real_start, real_end)

    shutil.rmtree(workdir, ignore_errors=True)
    ctx.stage(1.0, 1.0, "Done")
    try:
        from core import history
        vod_id = src.twitch_vod_id or src.id
        if vod_id:
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
