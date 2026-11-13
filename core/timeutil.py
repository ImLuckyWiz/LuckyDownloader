"""
Time parsing and formatting helpers for LuckyTwitch Downloader.
"""

from __future__ import annotations

import re

from core.errors import PlanError
from core.i18n import t


def parse_time(text: str) -> float | None:
    """'1:30:00', '90:00', '5400', '1h30m' -> seconds. Empty -> None."""
    text = text.strip().lower()
    if not text:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", text)
    if m and any(m.groups()):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    parts = text.split(":")
    if len(parts) > 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise PlanError(t("Invalid time: «{time}». Use H:MM:SS, MM:SS, seconds or 1h30m.", time=text))
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def fmt_hms(seconds: float | None) -> str:
    """Format seconds into H:MM:SS string. None -> '-'."""
    if seconds is None:
        return "-"
    s = int(round(seconds))
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def parse_twitch_duration(s: str) -> int:
    """'3h2m10s' -> seconds."""
    total = 0
    for value, unit in re.findall(r"(\d+)([hms])", s):
        total += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total
