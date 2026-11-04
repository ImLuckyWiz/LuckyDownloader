"""
Muted audio stretches detection (silenced by Twitch).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from core.runtime import resolve_dep
from core.timeline import Range

# User-Agent for HLS playlist requests
HLS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Twitch names a silenced segment "<n>-muted.<ext>" (e.g. "522-muted.mp4") and a normal one "<n>.<ext>".
_MUTED_SEGMENT = re.compile(r"-muted(?:\.[A-Za-z0-9]+)?$", re.IGNORECASE)


def parse_muted_ranges(text: str, duration: float | None = None) -> list[Range]:
    """
    A media playlist -> the stretches (start, end in VOD seconds) made of "-muted" segments; touching
    segments are merged. Deliberately lenient (unlike parse_hls_playlist): tags it does not know are
    ignored, because all it needs is the length of each segment and whether its name says "muted".
    """
    out: list[list[float]] = []
    t, length = 0.0, 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#EXTINF:"):
                try:
                    length = float(line[8:].split(",", 1)[0])
                except ValueError:
                    length = 0.0
            continue
        name = urlsplit(line).path.rsplit("/", 1)[-1]
        if _MUTED_SEGMENT.search(name) and length > 0:
            if out and abs(out[-1][1] - t) < 0.01:
                out[-1][1] = t + length
            else:
                out.append([t, t + length])
        t += length
        length = 0.0
    top = duration if duration and duration > 0 else None
    ranges: list[Range] = []
    for s, e in out:
        if top is not None:
            s, e = min(s, top), min(e, top)
        if e - s >= 0.5:
            ranges.append((round(s, 3), round(e, 3)))
    return ranges


def pick_playlist_url(formats) -> str | None:
    """The HLS media playlist of the best video quality in yt-dlp's format list (the one the downloads use)."""
    if not isinstance(formats, list):
        return None
    best: tuple[tuple[float, float, float], str] | None = None
    for f in formats:
        if not isinstance(f, dict):
            continue
        url = f.get("url")
        if not isinstance(url, str) or ".m3u8" not in url.split("?", 1)[0]:
            continue
        if f.get("vcodec") == "none" or f.get("format_note") == "storyboard":  # audio-only / thumbnails
            continue
        key = tuple(float(f.get(k) or 0) for k in ("height", "fps", "tbr"))
        if best is None or key > best[0]:
            best = (key, url)  # type: ignore[assignment]
    return best[1] if best else None


def muted_from_playlist_url(url: str, duration: float | None = None) -> list[Range] | None:
    """Download a playlist and read its muted stretches. None = could not be told (any failure)."""
    try:
        resp = requests.get(url, headers={"User-Agent": HLS_USER_AGENT}, timeout=15)
        resp.raise_for_status()
        return parse_muted_ranges(resp.text, duration)
    except (requests.RequestException, ValueError):
        return None


_ORIG_MUTED_FROM_PLAYLIST_URL = muted_from_playlist_url


def fetch_muted_ranges(formats, duration: float | None = None) -> list[Range] | None:
    """The muted stretches of a VOD from yt-dlp's format list: [] = none, None = could not be told."""
    url = pick_playlist_url(formats)
    if not url:
        return None
    fn = resolve_dep("muted_from_playlist_url", _ORIG_MUTED_FROM_PLAYLIST_URL, muted_from_playlist_url)
    return fn(url, duration)


def muted_overlap(muted: list[Range] | None, start: float, end: float) -> float:
    """Seconds of [start, end] that fall inside muted stretches."""
    return sum(max(0.0, min(e, end) - max(s, start)) for s, e in (muted or []))
