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
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from core.errors import EngineError
from core.i18n import t
from core.muted import fetch_muted_ranges
from core.runtime import USER_AGENT, _NO_WINDOW, _tool_env, find_tool, resolve_dep, user_data_dir
from core.timeline import Range

_ORIG_FIND_TOOL = find_tool
_ORIG_TOOL_ENV = _tool_env
_ORIG_NO_WINDOW = _NO_WINDOW
_ORIG_USER_DATA_DIR = user_data_dir
_ORIG_USER_AGENT = USER_AGENT


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
    is_age_restricted: bool = False
    segments: list[GameSegment] = field(default_factory=list)  # game changes; [] when yt-dlp gives none
    storyboard: Storyboard | None = None  # None when the site has no preview thumbnails
    # Stretches Twitch silenced, in VOD seconds. [] = checked, none; None = not checked or could not be told.
    muted: list[Range] | None = None
    formats: list[VideoFormat] = field(default_factory=list)
    thumbnail: str = ""
    site: str = "twitch"
    provider: Any | None = None

    def has_capability(self, cap: Any) -> bool:
        from core.providers.base import Capability
        if cap == Capability.TIMELINE and getattr(self, "site", "") == "twitch" and getattr(self, "twitch_vod_id", None) is None:
            return False
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
    is_age_restricted: bool = False

    def has_capability(self, cap: Any) -> bool:
        from core.providers.base import Capability
        if cap == Capability.TIMELINE and getattr(self, "site", "") == "twitch" and getattr(self, "twitch_vod_id", None) is None:
            return False
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


def _is_youtube_url(url: str) -> bool:
    """Check if the given URL points to a YouTube host."""
    try:
        target = (url or "").strip()
        if not target:
            return False
        if "://" not in target:
            target = f"https://{target}"
        host = (urlparse(target).hostname or "").lower()
        return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
    except Exception:
        return False


def youtube_extra_args(age_restricted: bool = False) -> list[str]:
    """Extra yt-dlp arguments for YouTube requests (remote JS challenge solver, optional user overrides)."""
    args = ["--remote-components", "ejs:github"]
    if age_restricted:
        args.extend(["--extractor-args", "youtube:player_client=default,web_safari"])
    from core.settings import load_settings
    import shlex
    try:
        st = load_settings()
        extra = st.get("ytdlp_extra_args") or os.environ.get("LUCKYDOWNLOADER_YTDLP_EXTRA_ARGS")
        if extra and isinstance(extra, str):
            args.extend(shlex.split(extra))
    except Exception:
        pass
    return args


def _run_ytdlp_json(
    target: str,
    *,
    cookies_browser: str | None = None,
    cookies_url: str | None = None,
    flat_playlist: bool = True,
    max_items: int | None = None,
    timeout: int = 180,
    is_youtube: bool = False,
    find_tool_fn: Callable[[str], str | None] | None = None,
    tool_env_fn: Callable[[], dict[str, str] | None] | None = None,
    no_window_flag: int | None = None,
    json_error_msg: str | None = None,
    is_age_restricted: bool = False,
) -> dict[str, Any]:
    """Execute yt-dlp --dump-single-json with fallback and error mapping."""
    _find = find_tool_fn if find_tool_fn is not None else resolve_dep("find_tool", _ORIG_FIND_TOOL, find_tool)
    _env = tool_env_fn if tool_env_fn is not None else resolve_dep("_tool_env", _ORIG_TOOL_ENV, _tool_env)
    _nw = no_window_flag if no_window_flag is not None else resolve_dep("_NO_WINDOW", _ORIG_NO_WINDOW, _NO_WINDOW)

    ytdlp = _find("yt-dlp") if _find else None
    if not ytdlp:
        raise EngineError(YTDLP_MISSING)

    cmd = [
        ytdlp,
        "--dump-single-json",
        "--no-warnings",
        "--skip-download",
    ]
    if is_youtube or _is_youtube_url(target):
        cmd += youtube_extra_args(age_restricted=is_age_restricted)
    if max_items:
        cmd.extend(["--playlist-end", str(max_items)])

    from core.settings import load_settings
    from core.cookie_scope import resolve_cookies_for_request
    st = load_settings()
    cb = cookies_browser if cookies_browser is not None else st.get("cookies_from_browser")
    scope = st.get("cookies_scope", "known_only")
    effective_cookies_url = cookies_url or ("https://www.youtube.com" if is_youtube else target)
    resolved_cb = resolve_cookies_for_request(effective_cookies_url, cb, scope_mode=scope)
    if resolved_cb:
        cmd += ["--cookies-from-browser", resolved_cb]
    if flat_playlist:
        cmd.append("--flat-playlist")
    cmd.extend(["--", target])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=_env(),
            creationflags=_nw,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise EngineError(t("yt-dlp took too long to read that URL.")) from e
    except OSError as e:
        raise EngineError(t("Could not run yt-dlp:\n{error}", error=e)) from e

    if proc.returncode != 0 and "--remote-components" in proc.stderr:
        cmd_fallback = [
            c for i, c in enumerate(cmd)
            if c != "--remote-components" and (i == 0 or cmd[i - 1] != "--remote-components")
        ]
        try:
            proc = subprocess.run(
                cmd_fallback,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                env=_env(),
                creationflags=_nw,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise EngineError(t("yt-dlp took too long to read that URL.")) from e
        except OSError as e:
            raise EngineError(t("Could not run yt-dlp:\n{error}", error=e)) from e

    if proc.returncode != 0:
        from core.providers.generic import map_generic_error
        raise EngineError(map_generic_error(proc.stderr))
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise EngineError(json_error_msg or t("yt-dlp returned unreadable data for that URL.")) from e

    # If YouTube video is age-restricted and cookies are active, but default client only yielded
    # low resolution (<=360p) due to missing PO-token, re-fetch with web_safari fallback.
    if (is_youtube or _is_youtube_url(target)) and resolved_cb and not is_age_restricted:
        age_limit = int(data.get("age_limit") or 0)
        is_age = age_limit >= 18 or data.get("is_age_restricted") is True
        if is_age:
            fmts = data.get("formats") or []
            max_h = max((int(f.get("height") or 0) for f in fmts if f.get("vcodec") != "none"), default=0)
            if max_h <= 360:
                try:
                    data = _run_ytdlp_json(
                        target,
                        cookies_browser=cookies_browser,
                        cookies_url=cookies_url,
                        flat_playlist=flat_playlist,
                        max_items=max_items,
                        timeout=timeout,
                        is_youtube=is_youtube,
                        find_tool_fn=_find,
                        tool_env_fn=_env,
                        no_window_flag=_nw,
                        json_error_msg=json_error_msg,
                        is_age_restricted=True,
                    )
                except Exception:
                    pass
    return data


_ORIG_SOURCE_INFO_RUN_YTDLP_JSON = _run_ytdlp_json


def get_source_info(text: str, cookies_browser: str | None = None) -> SourceInfo:
    url = normalize_url(text)
    if not url:
        raise EngineError(t("Paste a VOD URL or ID."))
    if "\n" in url or "\r" in url:
        raise EngineError(t("Paste a single VOD URL or ID (not multi-line text)."))

    run_fn = resolve_dep("_run_ytdlp_json", _ORIG_SOURCE_INFO_RUN_YTDLP_JSON, _run_ytdlp_json)

    is_vod = bool(twitch_vod_id(url))
    if run_fn is _ORIG_SOURCE_INFO_RUN_YTDLP_JSON:
        info = run_fn(
            url,
            cookies_browser=cookies_browser,
            flat_playlist=not is_vod,
            timeout=180,
        )
    else:
        try:
            info = run_fn(
                url,
                cookies_browser=cookies_browser,
                flat_playlist=not is_vod,
                timeout=180,
            )
        except TypeError:
            info = run_fn(url)

    if is_vod:
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


_SITE_PREFIX_ALIASES = ("youtube", "twitch", "tiktok", "instagram", "twitter", "reddit", "kick")


def _normalize_site_name(raw_ext: str, prov: Any | None) -> str:
    site = (raw_ext or "generic").lower().split(":")[0]
    for prefix in _SITE_PREFIX_ALIASES:
        if site.startswith(prefix):
            return prefix
    if prov and getattr(prov, "name", "generic") != "generic":
        return prov.name
    return site


def parse_playlist_info(info: dict, url: str) -> PlaylistInfo:
    """Turn yt-dlp's -J / --flat-playlist output for a playlist or channel into PlaylistInfo."""
    title = str(info.get("title") or info.get("description", "")[:80] or "Playlist").strip()
    uploader = str(info.get("uploader") or info.get("channel") or info.get("uploader_id") or "").strip()
    playlist_id = str(info.get("id") or "")
    thumbnail = str(info.get("thumbnail") or "")

    from core.providers.detect import detect_provider
    prov = detect_provider(url)
    raw_ext = (info.get("extractor") or info.get("extractor_key") or "generic").lower()
    site = _normalize_site_name(raw_ext, prov)

    raw_entries = info.get("entries") or []
    items: list[PlaylistItem] = []
    for idx, e in enumerate(raw_entries, start=1):
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or "")
        etitle = str(e.get("title") or f"Item {idx}").strip()
        eurl = str(e.get("url") or e.get("webpage_url") or "")
        if not eurl.startswith(("http://", "https://")):
            if (site == "youtube" or "youtu" in url) and re.match(r"^[A-Za-z0-9_-]{11}$", eid):
                eurl = f"https://www.youtube.com/watch?v={eid}"
            elif (site == "youtube" or "youtu" in url) and eurl and re.match(r"^[A-Za-z0-9_-]{11}$", eurl):
                eurl = f"https://www.youtube.com/watch?v={eurl}"
            else:
                continue

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
        is_age_restricted=bool(int(info.get("age_limit") or 0) >= 18 or info.get("is_age_restricted") is True),
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

    from core.providers.detect import detect_provider
    prov = detect_provider(url)
    raw_ext = (info.get("extractor") or info.get("extractor_key") or "generic").lower()
    site = _normalize_site_name(raw_ext, prov)
    clean_id = re.sub(r"[\\/]+", "_", str(info.get("id", "") or "")).strip()

    return SourceInfo(
        url=url,
        id=clean_id,
        title=title,
        uploader=uploader,
        duration=duration,
        date=date,
        twitch_vod_id=None,
        segments=parse_game_segments(info.get("chapters"), duration) if info.get("chapters") else [],
        storyboard=parse_storyboard(info.get("formats"), duration),
        muted=None,
        formats=parse_generic_formats(info.get("formats")),
        thumbnail=thumbnail,
        site=site,
        provider=prov,
        is_age_restricted=bool(int(info.get("age_limit") or 0) >= 18 or info.get("is_age_restricted") is True),
    )


def build_generic_format_string(
    quality: str = QUALITY_BEST,
    audio_only: bool | Any = False,
    src: Any = None,
) -> str:
    """Turn quality choice into yt-dlp format selector string."""
    if hasattr(audio_only, "formats") or hasattr(audio_only, "has_capability"):
        src = audio_only
        audio_only = False
    q = (quality or "").strip().lower()
    if audio_only or q in ("audio", "audio only", "audio_only"):
        return "ba/b"
    if not q or q in (QUALITY_BEST, "best", "source", "best available"):
        return "bv*+ba/b"
    m = re.search(r"(\d{3,4})p?", q)
    if m:
        h = int(m.group(1))
        return f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
    if src and getattr(src, "formats", None):
        matching = next(
            (f for f in src.formats if getattr(f, "format_id", None) == quality or getattr(f, "id", None) == quality),
            None,
        )
        if getattr(matching, "video_only", False) or getattr(src, "format_Needs_audio_merge", False) or getattr(src, "format_needs_audio_merge", False):
            return f"{quality}+bestaudio/{quality}/best"
        return f"{quality}/best"
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
    is_age_restricted: bool = False,
) -> list[str]:
    format_str = build_generic_format_string(quality=quality, audio_only=audio_only)
    args = [
        "-f", format_str,
        "--no-playlist",
        "--retries", "10",
        "--fragment-retries", "10",
        "--continue",
    ]
    if bool(re.search(r"(?:youtube\.com|youtu\.be)", url or "", re.I)):
        has_cookies = bool(cookies_browser and str(cookies_browser).strip().lower() not in ("none", "disabled", ""))
        args += youtube_extra_args(age_restricted=bool(is_age_restricted and has_cookies))
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
    args += ["--", url]
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
        user_data_dir_fn = resolve_dep("user_data_dir", _ORIG_USER_DATA_DIR, user_data_dir)
    if not user_agent:
        user_agent = resolve_dep("USER_AGENT", _ORIG_USER_AGENT, USER_AGENT) or ""

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
