"""
Generic provider fallback using yt-dlp for all non-Twitch sources (YouTube, TikTok, Instagram, Reddit, etc.).
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from core.errors import EngineError
from core.i18n import t
from core.providers.base import Capability, Provider
from core.runtime import _NO_WINDOW, _tool_env
from core.tools import find_tool

if TYPE_CHECKING:
    from core.source_info import SourceInfo


def map_generic_error(err_text: str) -> str:
    """Map raw yt-dlp stderr output to a clear, friendly user message."""
    s = (err_text or "").strip()
    s_low = s.lower()
    if "unsupported url" in s_low or "no suitable extractor" in s_low:
        return t("Unsupported URL: yt-dlp cannot extract video from this link.")
    if "private video" in s_low or "this video is private" in s_low:
        return t("Private video: this content is private or requires permission from the uploader.")
    if "age" in s_low and any(k in s_low for k in ("confirm your age", "age-restricted", "confirm you are of age", "sign in")):
        return t("Age-restricted video: sign-in required. Enable browser cookies in Options > Tools.")
    if any(k in s_low for k in ("sign in to confirm", "login required", "requires authentication", "account required")):
        return t("Login required: this video requires an account. Enable browser cookies in Options > Tools.")
    if any(k in s_low for k in ("not available in your country", "geo-blocked", "geoblocked", "geographic restriction", "blocked in your country")):
        return t("Geoblocked: this video is not available in your region or country.")
    if any(k in s_low for k in ("too many requests", "rate limit", "http error 429")):
        return t("Rate limited: too many requests. Wait a few minutes before trying again.")
    if any(k in s_low for k in ("extractor error", "unable to extract", "signature extraction failed", "regex pattern")):
        return t("Extractor error: the video site layout may have changed. Try updating yt-dlp in Options > Tools.")
    if any(k in s_low for k in ("unable to download webpage", "network is unreachable", "connection refused", "getaddrinfo failed", "timed out")):
        return t("Network error: could not connect to the video host. Check your internet connection.")
    if "http error 404" in s_low or "video unavailable" in s_low or "not found" in s_low:
        return t("Video unavailable: the requested video was not found or was removed.")
    lines = [line.strip() for line in s.splitlines() if line.strip()]
    if lines:
        last = lines[-1]
        if last.startswith("ERROR:"):
            last = last[6:].strip()
        return t("yt-dlp could not read that URL:\n{error}", error=last)
    return t("yt-dlp could not read that URL.")


def _run_ytdlp_json(
    target: str,
    *,
    cookies_browser: str | None = None,
    flat_playlist: bool = True,
    max_items: int | None = None,
    timeout: int = 180,
    is_youtube: bool = False,
) -> dict[str, Any]:
    """Delegate yt-dlp JSON extraction to core.source_info._run_ytdlp_json."""
    import core.source_info as _si
    if _si._run_ytdlp_json is _si._ORIG_SOURCE_INFO_RUN_YTDLP_JSON:
        return _si._run_ytdlp_json(
            target,
            cookies_browser=cookies_browser,
            flat_playlist=flat_playlist,
            max_items=max_items,
            timeout=timeout,
            is_youtube=is_youtube,
            find_tool_fn=find_tool,
            tool_env_fn=_tool_env,
            no_window_flag=_NO_WINDOW,
        )
    try:
        return _si._run_ytdlp_json(
            target,
            cookies_browser=cookies_browser,
            flat_playlist=flat_playlist,
            max_items=max_items,
            timeout=timeout,
            is_youtube=is_youtube,
        )
    except TypeError:
        return _si._run_ytdlp_json(target)


_ORIG_GENERIC_RUN_YTDLP_JSON = _run_ytdlp_json


class GenericProvider(Provider):
    """Provider for any site supported by yt-dlp."""

    def __init__(self, site_name: str = "generic") -> None:
        self._site_name = site_name

    @property
    def name(self) -> str:
        return self._site_name

    @property
    def capabilities(self) -> Capability:
        return Capability.RESOLVE | Capability.PLAYLIST

    def get_source_info(self, text: str) -> SourceInfo:
        url = text.strip()
        if not url:
            raise EngineError(t("Paste a video URL."))
        if "\n" in url or "\r" in url:
            raise EngineError(t("Paste a single URL (not multi-line text)."))

        if _run_ytdlp_json is _ORIG_GENERIC_RUN_YTDLP_JSON:
            info = _run_ytdlp_json(url, flat_playlist=True, timeout=180)
        else:
            try:
                info = _run_ytdlp_json(url, flat_playlist=True, timeout=180)
            except TypeError:
                info = _run_ytdlp_json(url)

        from core.source_info import is_playlist_dict
        if is_playlist_dict(info):
            return self.parse_playlist_info(info, url)
        return self.parse_info(info, url)

    def parse_info(self, info: dict, url: str) -> SourceInfo:
        """Parse raw yt-dlp dict offline into SourceInfo."""
        from core.source_info import parse_generic_source_info
        src = parse_generic_source_info(info, url)
        src.provider = self
        if self._site_name != "generic":
            src.site = self._site_name
        return src

    def parse_playlist_info(self, info: dict, url: str) -> PlaylistInfo:
        """Parse raw yt-dlp dict offline into PlaylistInfo."""
        from core.source_info import parse_playlist_info
        src = parse_playlist_info(info, url)
        src.provider = self
        if self._site_name != "generic":
            src.site = self._site_name
        return src

    def build_download_args(
        self,
        src: SourceInfo,
        opts: Any | None = None,
        *,
        quality: str = "best",
        container: str = "mp4",
        audio_only: bool = False,
        audio_format: str | None = None,
        out_template: str | None = None,
        rate_limit: str | None = None,
        threads: int = 4,
    ) -> list[str]:
        from core.source_info import build_generic_download_args
        q = getattr(opts, "quality", quality) if opts else quality
        cnt = getattr(opts, "container", container) if opts else container
        afmt = getattr(opts, "audio_format", audio_format) if opts else audio_format
        rl = getattr(opts, "rate_limit", rate_limit) if opts else rate_limit
        th = getattr(opts, "threads", threads) if opts else threads
        cb = getattr(opts, "cookies_browser", None)
        da = getattr(opts, "download_archive", None)
        return build_generic_download_args(
            src.url,
            quality=q,
            container=cnt,
            audio_only=audio_only,
            audio_format=afmt,
            out_template=out_template,
            rate_limit=rl,
            threads=th,
            cookies_browser=cb,
            download_archive=da,
        )
