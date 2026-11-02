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
        ytdlp = find_tool("yt-dlp")
        if not ytdlp:
            from core.source_info import YTDLP_MISSING
            raise EngineError(YTDLP_MISSING)

        cmd = [
            ytdlp,
            "--dump-single-json",
            "--no-warnings",
            "--flat-playlist",
            "--skip-download",
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player_client=web_safari,web",
        ]
        if max_items:
            cmd.extend(["--playlist-end", str(max_items)])

        from core.settings import load_settings
        from core.cookie_scope import resolve_cookies_for_request
        st = load_settings()
        cb = st.get("cookies_from_browser")
        scope = st.get("cookies_scope", "known_only")
        resolved_cb = resolve_cookies_for_request("https://www.youtube.com", cb, scope_mode=scope)
        if resolved_cb:
            cmd += ["--cookies-from-browser", resolved_cb]

        cmd.append(target)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                env=_tool_env(),
                creationflags=_NO_WINDOW,
                timeout=60,
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
                    env=_tool_env(),
                    creationflags=_NO_WINDOW,
                    timeout=60,
                )
            except Exception:
                pass

        if proc.returncode != 0:
            raise EngineError(map_generic_error(proc.stderr))

        try:
            return json.loads(proc.stdout)
        except Exception as e:
            raise EngineError(t("Could not parse yt-dlp output.")) from e
