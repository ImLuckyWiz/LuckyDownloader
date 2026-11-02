"""
Cookie scope validation to restrict browser cookies to eligible domains only.
"""

from __future__ import annotations

import urllib.parse

DEFAULT_COOKIE_DOMAINS: tuple[str, ...] = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "twitter.com",
    "x.com",
)

COOKIE_SCOPE_KNOWN = "known_only"
COOKIE_SCOPE_ALL = "all"
COOKIE_SCOPE_KNOWN_LABEL = "Only known platforms (YouTube, TikTok, Instagram, X)"
COOKIE_SCOPE_ALL_LABEL = "All supported sites"
COOKIE_SCOPE_NAMES = [COOKIE_SCOPE_KNOWN_LABEL, COOKIE_SCOPE_ALL_LABEL]


def is_cookie_eligible(url: str, scope_mode: str = COOKIE_SCOPE_KNOWN) -> bool:
    """Return True if `url` is eligible to receive browser cookies under `scope_mode`."""
    if not url or not isinstance(url, str):
        return False

    mode = (scope_mode or COOKIE_SCOPE_KNOWN).strip().lower()
    if mode in (
        COOKIE_SCOPE_ALL,
        COOKIE_SCOPE_ALL_LABEL.lower(),
        "all",
        "all_sites",
        "all supported sites",
    ):
        return True

    clean = url.strip()
    try:
        parts = urllib.parse.urlsplit(clean)
        host = (parts.hostname or "").lower()
    except Exception:
        return False

    if not host and "://" not in clean:
        try:
            parts = urllib.parse.urlsplit("https://" + clean)
            host = (parts.hostname or "").lower()
        except Exception:
            return False

    if not host:
        return False

    for domain in DEFAULT_COOKIE_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True

    return False


def resolve_cookies_for_request(
    url: str,
    cookies_browser: str | None,
    scope_mode: str = COOKIE_SCOPE_KNOWN,
    explicit_enabled: bool | None = None,
) -> str | None:
    """
    Resolve the browser cookies string to pass to yt-dlp, or None if cookies should not be used.

    - `cookies_browser`: e.g. "firefox", "chrome", "None"
    - `scope_mode`: "known_only" (default) or "all"
    - `explicit_enabled`:
        - None: auto-determine based on `is_cookie_eligible(url, scope_mode)`
        - True: user explicitly requested cookies for this request
        - False: user explicitly disabled cookies for this request
    """
    cb = (cookies_browser or "").strip().lower()
    if not cb or cb in ("none", "disabled"):
        return None

    if explicit_enabled is False:
        return None

    if explicit_enabled is True:
        return cb

    if is_cookie_eligible(url, scope_mode=scope_mode):
        return cb

    return None
