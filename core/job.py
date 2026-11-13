"""
Job and JobOptions dataclasses for LuckyTwitch Downloader.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from core.chapters import ClipFilter
from core.source_info import GameSegment, QUALITY_BEST, SourceInfo, Storyboard, VideoFormat
from core.timeline import Range
if TYPE_CHECKING:
    from core.twitch_api import TwitchClient


@dataclass
class JobOptions:
    cut_text: str
    out_dir: str
    container: str = "mp4"  # mp4 | mkv
    strategy: str = "auto"  # auto | full | sections
    full_threshold: float = 0.6
    exact: bool = False  # re-encode for frame-exact cuts (slow)
    keep_full: bool = False
    threads: int = 8
    name_template: str = "{streamer} - {date} - {id} - part{n}"
    chapters: bool = False
    clip_filter: ClipFilter = field(default_factory=ClipFilter)
    sidecar: bool = False  # write a .clips.json next to each part
    subfolders: bool = True  # out_dir/<streamer>/<stream>/parts
    provider_subfolders: bool = False  # group downloads under out_dir/<Provider>/...
    provider_out_dirs: dict[str, str] = field(default_factory=dict)
    folder_template: str = "{date} - {title} - {id}"  # name of the per-stream folder
    clip_name_template: str = "{clip_title}"  # file name when a single clip is downloaded
    generic_name_template: str = "{uploader} - {date} - {title} [{id}]"  # file name for generic (non-Twitch) downloads
    clean_title: bool = True  # strip bot commands (!links, !gsupps) and promo tags from stream titles
    premiere_xml: bool = False  # also write a Premiere Pro XML (clips as markers) next to each part
    game_markers: bool = False  # also put the game / category changes into that XML as markers ("GAME: ...")
    premiere_plugin: bool = False  # also write a .markers.json for the LuckyTwitch Premiere Pro plugin (colors, details)
    muted_markers: bool = False  # ... and put the stretches Twitch silenced into that .markers.json (kind "muted")
    chat: bool = False  # also download the chat of each part with TwitchDownloaderCLI (Twitch VODs only)
    chat_format: str = "json"  # json | txt | html
    chat_embed: bool = False  # embed emotes / badges in the chat file (bigger, but it renders offline)
    chat_render: bool = False  # also render the chat of each part as an overlay video for the editor (Twitch VODs only)
    chat_render_mode: str = "transparent"  # transparent (Animation .mov) | prores (ProRes 4444 .mov) | compact (H.264 .mp4)
    chat_render_look: str = "outline"  # outline (text with an outline, nothing behind) | panel (dark see-through panel)
    chat_render_width: int = 400  # pixels
    chat_render_height: int = 0  # pixels; 0 = the height of the video part
    chat_render_font_size: int = 18
    chat_render_fps: int = 0  # 0 = like the video (60 if it has 60 fps, else 30)
    chat_render_smooth: bool = False  # redraw on every frame (smooth scrolling, slower) instead of 5 times a second
    quality: str = QUALITY_BEST  # quality to download (Twitch VODs): "best", "720p60", "audio", etc.
    audio_format: str = "m4a"  # audio container when quality is audio-only: "m4a" | "mp3"
    rate_limit: str = ""  # optional bandwidth limit passed to yt-dlp ("--limit-rate"), e.g. "5M", "500K"
    cookies_browser: str = ""  # browser to pass cookies from ("--cookies-from-browser"), e.g. "chrome", "firefox"
    cookies_scope: str = "known_only"  # "known_only" (YouTube, TikTok, Instagram, X) or "all"
    cookies_explicit: bool | None = None  # optional per-job override for resolve_cookies_for_request()
    download_archive: str = ""  # optional path to yt-dlp download archive file ("--download-archive")


@dataclass
class Job:
    source: SourceInfo
    opts: JobOptions
    clips: list[dict] | None = None  # pre-fetched clips (otherwise fetched at run time)
    client: TwitchClient | None = None
    single_clip: dict | None = None  # set when the job only downloads this one clip


def serialize_job(job: Job) -> dict[str, Any]:
    """Serialize a Job (SourceInfo + JobOptions + clips + single_clip) into a JSON-safe dict."""
    src = job.source
    muted_serialized = None
    if src.muted is not None:
        muted_serialized = []
        for r in src.muted:
            if isinstance(r, (tuple, list)) and len(r) >= 2:
                muted_serialized.append({"start": float(r[0]), "end": float(r[1])})
            elif isinstance(r, dict):
                muted_serialized.append({"start": float(r.get("start", 0.0)), "end": float(r.get("end", 0.0))})
            else:
                muted_serialized.append({"start": float(getattr(r, "start", 0.0)), "end": float(getattr(r, "end", 0.0))})

    src_dict: dict[str, Any] = {
        "url": src.url,
        "id": src.id,
        "title": src.title,
        "uploader": src.uploader,
        "duration": float(src.duration or 0.0),
        "date": src.date,
        "twitch_vod_id": src.twitch_vod_id,
        "segments": [asdict(seg) for seg in (src.segments or [])],
        "storyboard": asdict(src.storyboard) if src.storyboard is not None else None,
        "muted": muted_serialized,
        "formats": [asdict(fmt) for fmt in (src.formats or [])],
        "thumbnail": getattr(src, "thumbnail", ""),
        "site": getattr(src, "site", "twitch"),
        "is_age_restricted": bool(getattr(src, "is_age_restricted", False)),
    }
    opts_dict = asdict(job.opts)
    return {
        "source": src_dict,
        "opts": opts_dict,
        "clips": job.clips,
        "single_clip": job.single_clip,
    }


def deserialize_job(data: dict[str, Any], client: TwitchClient | None = None) -> Job:
    """Reconstruct a Job from a dict produced by serialize_job()."""
    src_raw = dict(data.get("source") or {})
    segments = [
        GameSegment(
            start=float(s.get("start", 0.0)),
            end=float(s.get("end", 0.0)),
            title=str(s.get("title", "")),
        )
        for s in (src_raw.get("segments") or [])
        if isinstance(s, dict)
    ]
    sb_raw = src_raw.get("storyboard")
    storyboard = (
        Storyboard(
            urls=list(sb_raw.get("urls") or []),
            tile_w=int(sb_raw.get("tile_w", 0)),
            tile_h=int(sb_raw.get("tile_h", 0)),
            columns=int(sb_raw.get("columns", 1)),
            rows=int(sb_raw.get("rows", 1)),
            interval=float(sb_raw.get("interval", 1.0)),
            count=int(sb_raw.get("count", 0)),
        )
        if isinstance(sb_raw, dict)
        else None
    )
    muted_raw = src_raw.get("muted")
    muted = None
    if isinstance(muted_raw, list):
        muted = []
        for r in muted_raw:
            if isinstance(r, dict):
                muted.append((float(r.get("start", 0.0)), float(r.get("end", 0.0))))
            elif isinstance(r, (tuple, list)) and len(r) >= 2:
                muted.append((float(r[0]), float(r[1])))
    formats = [
        VideoFormat(
            format_id=str(f.get("format_id", "")),
            height=int(f.get("height", 0)),
            fps=float(f.get("fps", 0.0)),
            tbr=float(f.get("tbr", 0.0)),
            audio_only=bool(f.get("audio_only", False)),
            source=bool(f.get("source", False)),
            container=str(f.get("container", "")),
            filesize=int(f.get("filesize", 0)),
            vcodec=str(f.get("vcodec", "")),
            acodec=str(f.get("acodec", "")),
        )
        for f in (src_raw.get("formats") or [])
        if isinstance(f, dict)
    ]
    source = SourceInfo(
        url=str(src_raw.get("url", "")),
        id=str(src_raw.get("id", "")),
        title=str(src_raw.get("title", "")),
        uploader=str(src_raw.get("uploader", "")),
        duration=float(src_raw.get("duration", 0.0)),
        date=str(src_raw.get("date", "")),
        twitch_vod_id=src_raw.get("twitch_vod_id"),
        segments=segments,
        storyboard=storyboard,
        muted=muted,
        formats=formats,
        thumbnail=str(src_raw.get("thumbnail", "")),
        site=str(src_raw.get("site", "twitch")),
        is_age_restricted=bool(src_raw.get("is_age_restricted", False)),
    )

    opts_raw = dict(data.get("opts") or {})
    cf_raw = opts_raw.pop("clip_filter", None)
    clip_filter = ClipFilter(**cf_raw) if isinstance(cf_raw, dict) else ClipFilter()
    valid_opt_keys = {f.name for f in JobOptions.__dataclass_fields__.values()}
    filtered_opts = {k: v for k, v in opts_raw.items() if k in valid_opt_keys}
    filtered_opts["clip_filter"] = clip_filter
    if "cut_text" not in filtered_opts:
        filtered_opts["cut_text"] = ""
    if "out_dir" not in filtered_opts:
        filtered_opts["out_dir"] = ""
    opts = JobOptions(**filtered_opts)

    return Job(
        source=source,
        opts=opts,
        clips=data.get("clips"),
        client=client,
        single_clip=data.get("single_clip"),
    )
