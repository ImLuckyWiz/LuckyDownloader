"""
Source detection and URL normalization across providers.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from core.providers.base import Provider
from core.providers.generic import GenericProvider
from core.providers.twitch import TwitchProvider

TWITCH_PROVIDER = TwitchProvider()
GENERIC_PROVIDER = GenericProvider()

_VOD_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?twitch\.tv/(?:[\w]+/)?videos?/(\d+)",
    re.I,
)
_CLIP_URL_RE = re.compile(
    r"(?:https?://)?(?:(?:clips\.twitch\.tv/([a-zA-Z0-9_]+(?:-[a-zA-Z0-9_-]+)?))|(?:(?:www\.|m\.)?twitch\.tv/(?:[\w]+/)?clip/([a-zA-Z0-9_]+(?:-[a-zA-Z0-9_-]+)?)))",
    re.I,
)
_CHANNEL_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([a-zA-Z0-9_]{3,30})(?:[/?#].*)?$",
    re.I,
)
_CHANNEL_HANDLE_RE = re.compile(r"^@?([a-zA-Z0-9_]{3,30})$")
RESERVED_TWITCH = {
    "videos", "video", "directory", "p", "settings",
    "inventory", "downloads", "subscriptions", "wallet",
}

# General web URL validator: requires domain with dot and valid TLD, or localhost / IP
_WEB_URL_RE = re.compile(
    r"^(?:https?://)?"
    r"(?:(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}|localhost|\d{1,3}(?:\.\d{1,3}){3})"
    r"(?::\d+)?"
    r"(?:/.*)?$",
    re.I,
)


def is_twitch_source(text: str) -> bool:
    """Return True if text represents a Twitch VOD, clip, channel, or bare identifier."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s:
        return False
    if s.isdigit():
        return True
    if _VOD_URL_RE.search(s) or _CLIP_URL_RE.search(s):
        return True
    m_chan = _CHANNEL_URL_RE.match(s)
    if m_chan and m_chan.group(1).lower() not in RESERVED_TWITCH:
        return True
    m_handle = _CHANNEL_HANDLE_RE.match(s)
    if m_handle:
        user = m_handle.group(1).lower()
        if not user.isdigit() and user not in RESERVED_TWITCH:
            return True
    return False


def is_web_url(text: str) -> bool:
    """Return True if text matches a web URL structure."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s:
        return False
    if " " in s:
        return False
    return bool(_WEB_URL_RE.match(s))


def detect_source(text: str) -> tuple[Provider | None, str]:
    """Detect the source provider and return (provider, cleaned_url).

    Twitch is tried first (VOD URLs, bare IDs, clips, channel URLs, bare streamer names).
    Generic (yt-dlp) is tried last for any other valid web URL.
    Returns (None, "") if the input cannot be resolved to any provider.
    """
    s = (text or "").strip().strip('"\'')
    if not s or "\n" in s or "\r" in s:
        return None, ""

    # Unpack custom app link schemes (luckytwitch:// or luckydownloader://)
    if s.lower().startswith(("luckytwitch://", "luckydownloader://")):
        try:
            from weblink import parse_link
            req = parse_link(s)
            s = req.url.strip()
        except Exception:
            # Fallback regex for direct scheme paths like luckytwitch://vod/123
            m_scheme = re.match(r"^(?:luckytwitch|luckydownloader)://(?:vod/)?(\d+)", s, re.I)
            if m_scheme:
                s = m_scheme.group(1)
            else:
                return None, ""

    # 1. Bare numeric Twitch VOD ID
    if s.isdigit():
        return TWITCH_PROVIDER, f"https://www.twitch.tv/videos/{s}"

    # 2. Twitch VOD URL
    m_vod = _VOD_URL_RE.search(s)
    if m_vod:
        vod_id = m_vod.group(1)
        return TWITCH_PROVIDER, f"https://www.twitch.tv/videos/{vod_id}"

    # 3. Twitch Clip URL
    m_clip = _CLIP_URL_RE.search(s)
    if m_clip:
        clip_id = m_clip.group(1) or m_clip.group(2)
        return TWITCH_PROVIDER, f"https://clips.twitch.tv/{clip_id}"

    # 4. Twitch Channel URL
    m_chan = _CHANNEL_URL_RE.match(s)
    if m_chan:
        user = m_chan.group(1).lower()
        if user not in RESERVED_TWITCH:
            return TWITCH_PROVIDER, f"https://www.twitch.tv/{user}"

    # 5. Generic web URL (YouTube, TikTok, Instagram, Reddit, etc.)
    if is_web_url(s):
        cleaned = s if s.lower().startswith(("http://", "https://")) else f"https://{s}"
        # Disallow non-http/https schemes if any slipped through
        parts = urlsplit(cleaned)
        if parts.scheme.lower() not in ("http", "https"):
            return None, ""
        return GENERIC_PROVIDER, cleaned

    # 6. Bare Twitch streamer name/handle (@streamer or streamer)
    m_handle = _CHANNEL_HANDLE_RE.match(s)
    if m_handle:
        user = m_handle.group(1).lower()
        if not user.isdigit() and user not in RESERVED_TWITCH:
            return TWITCH_PROVIDER, f"https://www.twitch.tv/{user}"

    return None, ""


_KNOWN_PROVIDER_DOMAINS: tuple[tuple[str, str], ...] = (
    ("twitch.tv", "twitch"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("kick.com", "kick"),
    ("tiktok.com", "tiktok"),
    ("instagram.com", "instagram"),
    ("twitter.com", "twitter"),
    ("x.com", "twitter"),
)


def detect_provider(text: str) -> Provider:
    """Return the Provider for *text*, distinguishing known platforms from arbitrary generic URLs."""
    prov, cleaned = detect_source(text)
    if prov is TWITCH_PROVIDER:
        return TWITCH_PROVIDER
    target = cleaned or (text or "").strip()
    try:
        host = (urlsplit(target if "://" in target else f"https://{target}").hostname or "").lower()
    except Exception:
        host = ""
    for domain, site_id in _KNOWN_PROVIDER_DOMAINS:
        if host == domain or host.endswith("." + domain):
            if site_id == "twitch":
                return TWITCH_PROVIDER
            if site_id == "youtube":
                try:
                    parts = urlsplit(target if "://" in target else f"https://{target}")
                    path = (parts.path or "").lower()
                    if path.startswith(("/@", "/channel/", "/c/")):
                        from core.providers import YOUTUBE_PROVIDER
                        return YOUTUBE_PROVIDER
                except Exception:
                    pass
            return GenericProvider(site_id)
    return GENERIC_PROVIDER
