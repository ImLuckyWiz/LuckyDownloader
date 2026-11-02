"""
VOD source information extracted via yt-dlp: formats, game segments, storyboards.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from core.errors import EngineError
from core.i18n import t
from core.muted import fetch_muted_ranges
from core.timeline import Range


@dataclass
class GameSegment:
    """One stretch of a VOD streamed under one game / category (Twitch "chapters")."""

    start: float  # seconds from the start of the VOD
    end: float
    title: str  # the game's name; the same game can appear in several segments


@dataclass
class Storyboard:
    """Twitch's preview thumbnails: a few big "sprite sheet" JPEGs, each a grid of small frames.

    Frame i shows the VOD at i * interval seconds. Only the first `count` tiles are real frames:
    the last sheet can be padded with unused tiles.
    """

    urls: list[str]  # the sheets, in order; the sheets are public (no token needed)
    tile_w: int
    tile_h: int
    columns: int
    rows: int  # tile rows per sheet
    interval: float  # seconds between two frames (1 / yt-dlp's "fps")
    count: int  # number of real frames

    @property
    def per_sheet(self) -> int:
        return self.columns * self.rows

    def frame_time(self, index: int) -> float:
        return index * self.interval

    def frame_index_at(self, seconds: float) -> int:
        """Index of the frame closest at or before `seconds` (clamped to the real frames)."""
        return max(0, min(self.count - 1, int(seconds // self.interval)))

    def tile_box(self, index: int) -> tuple[int, tuple[int, int, int, int]]:
        """(sheet number, (left, top, right, bottom) in pixels) of frame `index`."""
        sheet, pos = divmod(index, self.per_sheet)
        row, col = divmod(pos, self.columns)
        x, y = col * self.tile_w, row * self.tile_h
        return sheet, (x, y, x + self.tile_w, y + self.tile_h)


QUALITY_BEST = "best"    # the highest quality there is
QUALITY_AUDIO = "audio"  # the audio-only quality


@dataclass(frozen=True)
class VideoFormat:
    """One quality Twitch offers for a VOD (one entry of yt-dlp's "formats")."""
    format_id: str           # what yt-dlp calls it: "1080p60", "720p60", "480p", "Audio_Only"
    height: int = 0          # 0 for audio only
    fps: float = 0.0
    tbr: float = 0.0         # kbit/s as Twitch declares it (0 = unknown)
    audio_only: bool = False
    source: bool = False     # Twitch's own "Source" quality (format_note == "Source")
    container: str = ""      # container/ext: "mp4", "mkv", "webm", "m4a", etc.
    filesize: int = 0        # declared or estimated bytes (0 = unknown)
    vcodec: str = ""
    acodec: str = ""

    @property
    def label(self) -> str:  # what the person reads
        if self.audio_only:
            return "Audio only"
        return f"{self.format_id} (Source)" if self.source else self.format_id

    @property
    def tag(self) -> str:    # for file names
        return "audio" if self.audio_only else self.format_id


@dataclass
class SourceInfo:
    url: str
    id: str
    title: str
    uploader: str
    duration: float
    date: str  # YYYY-MM-DD or ""
    twitch_vod_id: str | None = None
    segments: list[GameSegment] = field(default_factory=list)  # game changes; [] when yt-dlp gives none
    storyboard: Storyboard | None = None  # None when the site has no preview thumbnails
    # Stretches Twitch silenced, in VOD seconds. [] = checked, none; None = not checked or could not be told.
    muted: list[Range] | None = None
    formats: list[VideoFormat] = field(default_factory=list)
    thumbnail: str = ""
    site: str = "twitch"
    provider: Any | None = None

    def has_capability(self, cap: Any) -> bool:
        if self.provider is not None:
            return self.provider.has_capability(cap)
        from core.providers.detect import detect_source
        prov, _ = detect_source(self.url)
        if prov is not None:
            return prov.has_capability(cap)
        from core.providers.twitch import TwitchProvider
        return TwitchProvider().has_capability(cap)


@dataclass
class PlaylistItem:
    id: str
    title: str
    url: str
    duration: float = 0.0
    uploader: str = ""
    thumbnail: str = ""
    index: int = 1


@dataclass
class PlaylistInfo:
    id: str
    title: str
    url: str
    uploader: str = ""
    entries: list[PlaylistItem] = field(default_factory=list)
    thumbnail: str = ""
    site: str = "generic"
    provider: Any | None = None
    twitch_vod_id: str | None = None

    def has_capability(self, cap: Any) -> bool:
        if self.provider is not None:
            return self.provider.has_capability(cap)
        from core.providers.base import Capability
        return bool(cap & (Capability.RESOLVE | Capability.PLAYLIST))


def normalize_url(text: str) -> str:
    text = text.strip()
    if text.isdigit():
        return f"https://www.twitch.tv/videos/{text}"
    return text


def twitch_vod_id(url: str) -> str | None:
    m = re.search(r"twitch\.tv/(?:[\w]+/)?videos?/(\d+)", url)
    return m.group(1) if m else None


YTDLP_MISSING = "yt-dlp is not installed yet (it is downloaded automatically on first run). Check your connection and restart."


def get_source_info(text: str, cookies_browser: str | None = None) -> SourceInfo:
    import luckytwitch_engine
    find_tool = getattr(luckytwitch_engine, "find_tool", None)
    tool_env = getattr(luckytwitch_engine, "_tool_env", lambda: None)
    no_window = getattr(luckytwitch_engine, "_NO_WINDOW", 0)

    url = normalize_url(text)
    if not url:
        raise EngineError(t("Paste a VOD URL or ID."))
    if "\n" in url or "\r" in url:
        raise EngineError(t("Paste a single VOD URL or ID (not multi-line text)."))
    ytdlp = find_tool("yt-dlp") if find_tool else None
    if not ytdlp:
        raise EngineError(YTDLP_MISSING)
    cmd = [ytdlp, "--dump-single-json", "--no-warnings", "--skip-download", "--remote-components", "ejs:github"]
    from core.settings import load_settings
    cb = cookies_browser if cookies_browser is not None else load_settings().get("cookies_from_browser")
    if cb and str(cb).strip().lower() not in ("none", "disabled", ""):
        cmd += ["--cookies-from-browser", str(cb).strip().lower()]
    if not twitch_vod_id(url):
        cmd.append("--flat-playlist")
    cmd.append(url)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=tool_env(),
            creationflags=no_window,
            timeout=180,
        )
    except subprocess.TimeoutExpired as e:
        raise EngineError(t("yt-dlp took too long to read that URL.")) from e
    except OSError as e:
        raise EngineError(t("Could not run yt-dlp:\n{error}").format(error=e)) from e
    if proc.returncode != 0 and "--remote-components" in proc.stderr:
        cmd_fallback = [c for i, c in enumerate(cmd) if c != "--remote-components" and (i == 0 or cmd[i-1] != "--remote-components")]
        try:
            proc = subprocess.run(
                cmd_fallback,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                env=tool_env(),
                creationflags=no_window,
                timeout=180,
            )
        except Exception:
            pass
    if proc.returncode != 0:
        from core.providers.generic import map_generic_error
        raise EngineError(map_generic_error(proc.stderr))
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise EngineError(t("yt-dlp returned unreadable data for that URL.")) from e
    if twitch_vod_id(url):
        src = parse_source_info(info, url)
        src.muted = fetch_muted_ranges(info.get("formats"), src.duration)
    elif is_playlist_dict(info):
        src = parse_playlist_info(info, url)
    else:
        src = parse_generic_source_info(info, url)
    return src


def parse_source_info(info: dict, url: str) -> SourceInfo:
    """Turn yt-dlp's --dump-single-json output into a SourceInfo (no I/O, so it is easy to test)."""
    if not info.get("duration"):
        raise EngineError(t("yt-dlp did not report the video length for that URL."))
    duration = float(info["duration"])
    d = info.get("upload_date") or ""
    date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""
    return SourceInfo(
        url=url,
        id=str(info.get("id", "")),
        title=info.get("title", "") or "",
        uploader=info.get("uploader") or info.get("channel") or "",
        duration=duration,
        date=date,
        twitch_vod_id=twitch_vod_id(url),
        segments=parse_game_segments(info.get("chapters"), duration),
        storyboard=parse_storyboard(info.get("formats"), duration),
        formats=parse_formats(info.get("formats")) if twitch_vod_id(url) else [],
    )


def parse_game_segments(chapters, duration: float) -> list[GameSegment]:
    """yt-dlp "chapters" -> game segments. Tolerates a missing / null / odd list; drops empty or broken entries.

    Segments are NOT merged by title: a streamer can go Just Chatting -> a game -> Just Chatting again.
    """
    if not isinstance(chapters, list):
        return []
    out: list[GameSegment] = []
    for c in chapters:
        if not isinstance(c, dict):
            continue
        try:
            start, end = float(c["start_time"]), float(c["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        start, end = max(0.0, start), min(end, duration)
        if not (end > start):  # also drops NaN
            continue
        out.append(GameSegment(start, end, str(c.get("title") or "").strip()))
    out.sort(key=lambda g: g.start)
    return out


def parse_storyboard(formats, duration: float, prefer: str = "low") -> Storyboard | None:
    """Pick the preview-thumbnail "format" of yt-dlp's list. prefer="low" = smallest tiles (fewest downloads).

    Frame timing comes from the format's "fps" (frames per second, e.g. 0.2 = one every 5 s), NOT from the
    fragments' "duration": those just split the VOD evenly between sheets, while the last sheet is only
    partly filled. Returns None if nothing usable is there.
    """
    if not isinstance(formats, list) or duration <= 0:
        return None
    best = None
    for f in formats:
        if not isinstance(f, dict) or f.get("format_note") != "storyboard":
            continue
        try:
            w, h = int(f["width"]), int(f["height"])
            cols, rows = int(f["columns"]), int(f["rows"])
            fps = float(f["fps"])
            urls = [str(fr["url"]) for fr in f["fragments"]]
        except (KeyError, TypeError, ValueError):
            continue
        if min(w, h, cols, rows) <= 0 or not (fps > 0) or not urls or not all(urls):
            continue
        count = min(math.ceil(duration * fps - 1e-6), len(urls) * cols * rows)  # never beyond what the sheets hold
        if count < 1:
            continue
        sb = Storyboard(urls=urls, tile_w=w, tile_h=h, columns=cols, rows=rows, interval=1 / fps, count=count)
        key = w * h
        if best is None or (key > best[0] if prefer == "high" else key < best[0]):
            best = (key, sb)
    return best[1] if best else None


def parse_formats(formats) -> list[VideoFormat]:
    """Turn yt-dlp's "formats" list into our sorted list of VideoFormat objects."""
    if not isinstance(formats, list):
        return []
    seen = set()
    result: list[VideoFormat] = []
    for f in formats:
        if not isinstance(f, dict):
            continue
        if f.get("format_note") == "storyboard":
            continue
        fid = f.get("format_id")
        if not fid or not isinstance(fid, str) or fid.strip() == "":
            continue
        fid = fid.strip()
        if fid in seen:
            continue
        url = f.get("url")
        if not isinstance(url, str):
            continue
        base_url = url.split("?")[0]
        if ".m3u8" not in base_url:
            continue
        seen.add(fid)
        audio_only = f.get("vcodec") == "none"
        try:
            h = int(f.get("height") or 0)
        except (ValueError, TypeError):
            h = 0
        try:
            fps = float(f.get("fps") or 0.0)
        except (ValueError, TypeError):
            fps = 0.0
        try:
            tbr = float(f.get("tbr") or 0.0)
        except (ValueError, TypeError):
            tbr = 0.0
        is_source = f.get("format_note") == "Source"
        result.append(
            VideoFormat(
                format_id=fid,
                height=max(0, h),
                fps=max(0.0, fps),
                tbr=max(0.0, tbr),
                audio_only=audio_only,
                source=is_source,
            )
        )
    # Sort: video first, then by height desc, fps desc, tbr desc; audio-only last
    result.sort(key=lambda vf: (not vf.audio_only, vf.height, vf.fps, vf.tbr), reverse=True)
    return result


def parse_generic_formats(formats) -> list[VideoFormat]:
    """Turn yt-dlp's "formats" from generic sites (YouTube, TikTok, Reddit, Instagram)
    into a deduplicated, sorted list of VideoFormat choices by resolution + audio only.
    """
    if not isinstance(formats, list):
        return []

    by_height: dict[int, dict] = {}
    best_audio: dict | None = None
    has_video = False

    for f in formats:
        if not isinstance(f, dict):
            continue
        if f.get("format_note") == "storyboard":
            continue
        vcodec = f.get("vcodec") or ""
        acodec = f.get("acodec") or ""
        h = f.get("height")
        try:
            h_int = int(h) if h is not None else 0
        except (ValueError, TypeError):
            h_int = 0

        # Audio-only stream
        if vcodec == "none" and acodec and acodec != "none":
            tbr = float(f.get("tbr") or f.get("abr") or 0.0)
            best_tbr = float(best_audio.get("tbr") or best_audio.get("abr") or 0.0) if best_audio else -1.0
            if best_audio is None or tbr > best_tbr:
                best_audio = f
            continue

        # Video stream
        if vcodec and vcodec != "none" and h_int > 0:
            has_video = True
            tbr = float(f.get("tbr") or f.get("vbr") or 0.0)
            fps = float(f.get("fps") or 0.0)
            existing = by_height.get(h_int)
            ex_fps = float(existing.get("fps") or 0.0) if existing else 0.0
            ex_tbr = float(existing.get("tbr") or existing.get("vbr") or 0.0) if existing else 0.0
            if existing is None or (fps, tbr) > (ex_fps, ex_tbr):
                by_height[h_int] = f

    result: list[VideoFormat] = []
    sorted_heights = sorted(by_height.keys(), reverse=True)
    for i, h in enumerate(sorted_heights):
        f = by_height[h]
        fps = float(f.get("fps") or 0.0)
        tbr = float(f.get("tbr") or f.get("vbr") or 0.0)
        ext = str(f.get("ext") or "mp4")
        fs = int(f.get("filesize") or f.get("filesize_approx") or 0)
        fid = f"{h}p"
        result.append(
            VideoFormat(
                format_id=fid,
                height=h,
                fps=fps,
                tbr=tbr,
                audio_only=False,
                source=(i == 0),
                container=ext,
                filesize=fs,
                vcodec=str(f.get("vcodec") or ""),
                acodec=str(f.get("acodec") or ""),
            )
        )

    if best_audio is not None or has_video:
        tbr = float(best_audio.get("tbr") or best_audio.get("abr") or 0.0) if best_audio else 0.0
        ext = str(best_audio.get("ext") or "m4a") if best_audio else "m4a"
        fs = int(best_audio.get("filesize") or best_audio.get("filesize_approx") or 0) if best_audio else 0
        result.append(
            VideoFormat(
                format_id="Audio_Only",
                height=0,
                fps=0.0,
                tbr=tbr,
                audio_only=True,
                source=False,
                container=ext,
                filesize=fs,
                vcodec="none",
                acodec=str(best_audio.get("acodec") or "") if best_audio else "",
            )
        )

    return result


def is_playlist_dict(info: dict) -> bool:
    return bool(info.get("_type") in ("playlist", "channel", "multi_video") or "entries" in info)


def parse_playlist_info(info: dict, url: str) -> PlaylistInfo:
    """Turn yt-dlp's -J / --flat-playlist output for a playlist or channel into PlaylistInfo."""
    title = str(info.get("title") or info.get("description", "")[:80] or "Playlist").strip()
    uploader = str(info.get("uploader") or info.get("channel") or info.get("uploader_id") or "").strip()
    playlist_id = str(info.get("id") or "")
    thumbnail = str(info.get("thumbnail") or "")

    from core.providers.detect import detect_source
    prov, _ = detect_source(url)
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    site = prov.name if prov and prov.name != "generic" else (extractor or "generic")

    raw_entries = info.get("entries") or []
    items: list[PlaylistItem] = []
    for idx, e in enumerate(raw_entries, start=1):
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or "")
        etitle = str(e.get("title") or f"Item {idx}").strip()
        eurl = str(e.get("url") or e.get("webpage_url") or "")
        if not eurl and eid:
            if "youtube" in site or "youtu" in url:
                eurl = f"https://www.youtube.com/watch?v={eid}"
            else:
                eurl = eid
        elif eurl and not eurl.startswith("http"):
            if "youtube" in site or "youtu" in url:
                eurl = f"https://www.youtube.com/watch?v={eurl}"

        edur = float(e.get("duration") or 0.0)
        euploader = str(e.get("uploader") or e.get("channel") or uploader).strip()
        ethumb = str(e.get("thumbnail") or "")
        if not ethumb and e.get("thumbnails"):
            thumbs = e["thumbnails"]
            if isinstance(thumbs, list) and thumbs:
                ethumb = str(thumbs[-1].get("url") or "")
        if not ethumb and eid and ("youtube" in site or "youtu" in url or "youtube" in eurl):
            ethumb = f"https://i.ytimg.com/vi/{eid}/hqdefault.jpg"

        items.append(
            PlaylistItem(
                id=eid,
                title=etitle,
                url=eurl,
                duration=edur,
                uploader=euploader,
                thumbnail=ethumb,
                index=idx,
            )
        )

    if not thumbnail and items and items[0].thumbnail:
        thumbnail = items[0].thumbnail

    return PlaylistInfo(
        id=playlist_id,
        title=title,
        url=url,
        uploader=uploader,
        entries=items,
        thumbnail=thumbnail,
        site=site,
        provider=prov,
    )


def parse_generic_source_info(info: dict, url: str) -> SourceInfo:
    """Turn yt-dlp's --dump-single-json output for a non-Twitch URL into a neutral SourceInfo."""
    if info.get("_type") in ("playlist", "channel", "multi_video") or "entries" in info:
        raise EngineError(t("Playlists and channels are not supported yet (coming in Phase 6). Paste a single video link."))

    duration = float(info.get("duration") or 0.0)
    d = str(info.get("upload_date") or "")
    date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""
    title = str(info.get("title") or info.get("description", "")[:80] or "video").strip()
    uploader = str(info.get("uploader") or info.get("channel") or info.get("uploader_id") or "").strip()
    thumbnail = str(info.get("thumbnail") or "")

    from core.providers.detect import detect_source
    prov, _ = detect_source(url)
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    site = prov.name if prov and prov.name != "generic" else (extractor or "generic")

    return SourceInfo(
        url=url,
        id=str(info.get("id", "")),
        title=title,
        uploader=uploader,
        duration=duration,
        date=date,
        twitch_vod_id=None,
        segments=[],
        storyboard=None,
        muted=None,
        formats=parse_generic_formats(info.get("formats")),
        thumbnail=thumbnail,
        site=site,
        provider=prov,
    )


def build_generic_format_string(quality: str = QUALITY_BEST, audio_only: bool = False) -> str:
    """Turn quality choice into yt-dlp format selector string."""
    q = (quality or "").strip().lower()
    if audio_only or q in ("audio", "audio only", "audio_only"):
        return "ba/b"
    if q in ("", QUALITY_BEST, "best available"):
        return "bv*+ba/b"
    m = re.search(r"(\d{3,4})p?", q)
    if m:
        h = int(m.group(1))
        return f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
    return q


def build_generic_download_args(
    url: str,
    *,
    quality: str = QUALITY_BEST,
    container: str = "mp4",
    audio_only: bool = False,
    audio_format: str | None = None,
    out_template: str | None = None,
    rate_limit: str | None = None,
    threads: int = 4,
    cookies_browser: str | None = None,
    download_archive: str | None = None,
) -> list[str]:
    format_str = build_generic_format_string(quality=quality, audio_only=audio_only)
    args = [
        "-f", format_str,
        "--no-playlist",
        "--retries", "10",
        "--fragment-retries", "10",
        "--continue",
        "--remote-components", "ejs:github",
    ]
    if threads > 1:
        args += ["--concurrent-fragments", str(max(1, threads))]
    if rate_limit and str(rate_limit).strip():
        args += ["--limit-rate", str(rate_limit).strip()]
    if cookies_browser and str(cookies_browser).strip().lower() not in ("none", "disabled", ""):
        args += ["--cookies-from-browser", str(cookies_browser).strip().lower()]
    if download_archive and str(download_archive).strip():
        args += ["--download-archive", str(download_archive).strip()]
    if audio_only or (quality or "").strip().lower() in ("audio", "audio only", "audio_only"):
        if audio_format and audio_format.lower() in ("mp3", "m4a", "opus", "wav", "flac"):
            afmt = audio_format.lower()
        elif container and container.lower().lstrip(".") in ("mp3", "m4a", "opus", "wav", "flac"):
            afmt = container.lower().lstrip(".")
        else:
            afmt = "m4a"
        args += ["-x", "--audio-format", afmt]
    else:
        cnt = container.lower().lstrip(".")
        if cnt in ("mp4", "mkv", "webm", "mov"):
            args += ["--merge-output-format", cnt]
    if out_template:
        args += ["-o", out_template]
    args.append(url)
    return args



def resolve_format(formats: list[VideoFormat], wanted: str = QUALITY_BEST) -> VideoFormat | None:
    """Pick the format from ``formats`` that best matches the ``wanted`` string."""
    if not formats:
        return None
    w = (wanted or "").strip().lower()

    # 1. "audio" -> audio-only; fallback to best video
    if w in (QUALITY_AUDIO, "audio only", "audio_only"):
        for vf in formats:
            if vf.audio_only:
                return vf
        return resolve_format(formats, QUALITY_BEST)

    # 2. "best" / empty / unknown
    if w in ("", QUALITY_BEST):
        videos = [vf for vf in formats if not vf.audio_only]
        if videos:
            return max(videos, key=lambda vf: (vf.height, vf.fps, vf.tbr))
        return formats[0]

    # 3. Exact format_id match (case-insensitive)
    for vf in formats:
        if vf.format_id.lower() == w:
            return vf

    # 4. Height cap like "720p"
    m = re.search(r"(\d{3,4})p", w)
    if m:
        cap = int(m.group(1))
        videos = [vf for vf in formats if not vf.audio_only and vf.height > 0]
        under = [vf for vf in videos if vf.height <= cap]
        if under:
            return max(under, key=lambda vf: (vf.height, vf.fps, vf.tbr))
        if videos:
            # Lowest video format
            return min(videos, key=lambda vf: (vf.height, vf.fps, vf.tbr))

    # 5. Fallback to best
    return resolve_format(formats, QUALITY_BEST)


def describe_quality(fmt: VideoFormat, asked: str = QUALITY_BEST) -> str:
    """Human-readable description of the resolved format, noting differences if what was asked was not exact."""
    a = (asked or "").strip().lower()
    base = f"Quality: {fmt.label}"
    if a in ("", QUALITY_BEST):
        return base
    if a == fmt.format_id.lower():
        return base
    if a == QUALITY_AUDIO and fmt.audio_only:
        return base
    return f"{base} (asked for {asked})"


def estimate_bytes(fmt: VideoFormat | None, seconds: float) -> int:
    """Estimated download size in bytes based on Twitch's declared bitrate (tbr in kbit/s)."""
    if fmt is None or fmt.tbr <= 0 or seconds <= 0:
        return 0
    return int(round(fmt.tbr * 1000 / 8 * seconds))


def fetch_storyboard_sheet(url: str, user_data_dir_fn=None, user_agent: str = "") -> Path | None:
    """Download one sprite sheet once into the per-user cache and return its path (None on failure)."""
    if not url:
        return None
    if user_data_dir_fn is None:
        import luckytwitch_engine
        user_data_dir_fn = luckytwitch_engine.user_data_dir
    if not user_agent:
        import luckytwitch_engine
        user_agent = getattr(luckytwitch_engine, "USER_AGENT", "")

    path = user_data_dir_fn() / "cache" / "storyboards" / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".jpg")
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
        headers = {"User-Agent": user_agent} if user_agent else {}
        r = requests.get(url, timeout=30, headers=headers)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        os.replace(tmp, path)
        return path
    except (requests.RequestException, OSError):
        return None


def load_storyboard_frames(sb: Storyboard, fetch: Callable[[str], Path | None] = fetch_storyboard_sheet) -> list:
    """Download the sheets and cut them into frames: a list of `sb.count` PIL images (None = unavailable).

    Slow (network): call it from a background thread. Needs Pillow; without it (or without any sheet) the
    frames are all None, so callers just show no thumbnails.
    """
    frames: list = [None] * sb.count
    try:
        from PIL import Image
    except ImportError:
        return frames
    sheets: dict[int, object] = {}
    for n, url in enumerate(sb.urls):
        path = fetch(url)
        if path is None:
            continue
        try:
            with Image.open(path) as im:
                sheets[n] = im.convert("RGB")
        except (OSError, ValueError):
            continue
    for i in range(sb.count):
        n, box = sb.tile_box(i)
        im = sheets.get(n)
        if im is None or box[2] > im.width or box[3] > im.height:  # sheet missing or smaller than expected
            continue
        frames[i] = im.crop(box)
    return frames
