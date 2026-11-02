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


class GenericProvider(Provider):
    """Provider for any site supported by yt-dlp."""

    def __init__(self, site_name: str = "generic") -> None:
        self._site_name = site_name

    @property
    def name(self) -> str:
        return self._site_name

    @property
    def capabilities(self) -> Capability:
        return Capability.RESOLVE

    def get_source_info(self, text: str) -> SourceInfo:
        from core.source_info import YTDLP_MISSING

        url = text.strip()
        if not url:
            raise EngineError(t("Paste a video URL."))
        if "\n" in url or "\r" in url:
            raise EngineError(t("Paste a single URL (not multi-line text)."))

        ytdlp = find_tool("yt-dlp")
        if not ytdlp:
            raise EngineError(YTDLP_MISSING)

        cmd = [ytdlp, "--dump-single-json", "--no-warnings", "--no-playlist", "--skip-download"]
        from core.settings import load_settings
        cb = load_settings().get("cookies_from_browser")
        if cb and str(cb).strip().lower() not in ("none", "disabled", ""):
            cmd += ["--cookies-from-browser", str(cb).strip().lower()]
        cmd.append(url)
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
                timeout=180,
            )
        except subprocess.TimeoutExpired as e:
            raise EngineError(t("yt-dlp took too long to read that URL.")) from e
        except OSError as e:
            raise EngineError(t("Could not run yt-dlp:\n{error}").format(error=e)) from e

        if proc.returncode != 0:
            raise EngineError(map_generic_error(proc.stderr))

        try:
            info = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise EngineError(t("yt-dlp returned unreadable data for that URL.")) from e

        return self.parse_info(info, url)

    def parse_info(self, info: dict, url: str) -> SourceInfo:
        """Parse raw yt-dlp dict offline into SourceInfo."""
        from core.source_info import parse_generic_source_info
        src = parse_generic_source_info(info, url)
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
        )
