"""
YouTube provider supporting video search (ytsearch) and channel video browsing via yt-dlp.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from core.errors import EngineError
from core.i18n import t
from core.providers.base import Capability
from core.providers.generic import GenericProvider, map_generic_error
from core.runtime import _NO_WINDOW, _tool_env
from core.tools import find_tool

if TYPE_CHECKING:
    from core.source_info import SourceInfo


def _format_yt_date(raw_date: str | None) -> str:
    """Format YYYYMMDD to YYYY-MM-DD, or return as-is if already formatted."""
    if not raw_date:
        return ""
    d = str(raw_date).strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _parse_yt_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a yt-dlp entry into a video dictionary compatible with VodModel."""
    vid_id = str(entry.get("id") or "")
    url = entry.get("url") or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "")
    thumb = ""
    thumbs = entry.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        thumb = thumbs[-1].get("url") or ""
    if not thumb:
        thumb = str(entry.get("thumbnail") or "")

    return {
        "id": vid_id,
        "title": entry.get("title") or "(untitled)",
        "date": _format_yt_date(entry.get("upload_date") or entry.get("date")),
        "duration": float(entry.get("duration") or 0.0),
        "views": int(entry.get("view_count") or 0),
        "thumb": thumb,
        "url": url,
        "uploader": entry.get("uploader") or entry.get("channel") or "",
    }


class YouTubeProvider(GenericProvider):
    """Provider specifically for YouTube, with search and channel browsing capabilities."""

    def __init__(self) -> None:
        super().__init__(site_name="youtube")

    @property
    def display_name(self) -> str:
        return "YouTube"

    @property
    def capabilities(self) -> Capability:
        return (
            Capability.RESOLVE
            | Capability.PLAYLIST
            | Capability.BROWSE
            | Capability.SUBSCRIBE
        )

    def search_videos(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search YouTube videos matching `query` using yt-dlp ytsearch."""
        q = (query or "").strip()
        if not q:
            return []

        # If user pasted a channel URL or handle, route to channel listing
        if q.startswith(("@", "http://", "https://", "youtube.com/")):
            videos, _ = self.fetch_channel_videos(q, limit=limit)
            return videos

        target = f"ytsearch{max(1, min(limit, 50))}:{q}"
        data = self._run_ytdlp_json(target)
        entries = data.get("entries") or []
        results: list[dict[str, Any]] = []
        for e in entries:
            if isinstance(e, dict):
                results.append(_parse_yt_entry(e))
        return results

    def fetch_channel_videos(self, channel_or_url: str, limit: int = 20) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch latest videos from a YouTube channel handle, URL, or identifier."""
        s = (channel_or_url or "").strip()
        if not s:
            return [], None

        if s.startswith("@"):
            url = f"https://www.youtube.com/{s}/videos"
        elif not s.lower().startswith(("http://", "https://")):
            if s.lower().startswith("youtube.com"):
                url = f"https://www.{s}"
            else:
                url = f"https://www.youtube.com/@{s}/videos"
        else:
            url = s
            # Ensure it targets the videos tab if bare channel URL
            if not any(url.rstrip("/").endswith(tab) for tab in ("/videos", "/shorts", "/streams", "/playlists")):
                url = f"{url.rstrip('/')}/videos"

        data = self._run_ytdlp_json(url, max_items=limit)
        entries = data.get("entries") or []
        videos: list[dict[str, Any]] = []
        for e in entries:
            if isinstance(e, dict):
                videos.append(_parse_yt_entry(e))
        return videos, None

    def _run_ytdlp_json(self, target: str, max_items: int | None = None) -> dict[str, Any]:
        """Execute yt-dlp with flat playlist extraction and return parsed JSON."""
        if _run_ytdlp_json is not _ORIG_YOUTUBE_RUN_YTDLP_JSON:
            try:
                return _run_ytdlp_json(target, max_items=max_items)
            except TypeError:
                return _run_ytdlp_json(target)
        return _run_ytdlp_json(target, max_items=max_items, timeout=60, is_youtube=True)


def _run_ytdlp_json(
    target: str,
    max_items: int | None = None,
    *,
    timeout: int = 60,
    is_youtube: bool = True,
) -> dict[str, Any]:
    """Delegate yt-dlp JSON extraction to core.source_info._run_ytdlp_json."""
    import core.source_info as _si
    if _si._run_ytdlp_json is _si._ORIG_SOURCE_INFO_RUN_YTDLP_JSON:
        return _si._run_ytdlp_json(
            target,
            flat_playlist=True,
            max_items=max_items,
            timeout=timeout,
            is_youtube=is_youtube,
            find_tool_fn=find_tool,
            tool_env_fn=_tool_env,
            no_window_flag=_NO_WINDOW,
            json_error_msg=t("Could not parse yt-dlp output."),
        )
    try:
        return _si._run_ytdlp_json(
            target,
            flat_playlist=True,
            max_items=max_items,
            timeout=timeout,
            is_youtube=is_youtube,
        )
    except TypeError:
        try:
            return _si._run_ytdlp_json(target, max_items=max_items)
        except TypeError:
            return _si._run_ytdlp_json(target)


_ORIG_YOUTUBE_RUN_YTDLP_JSON = _run_ytdlp_json
