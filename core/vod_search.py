"""
Twitch channel searching and VOD listing.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import requests

from core.runtime import USER_AGENT, resolve_dep, user_data_dir
from core.timeutil import parse_twitch_duration
from core.twitch_api import TwitchClient

_ORIG_USER_DATA_DIR = user_data_dir
_ORIG_USER_AGENT = USER_AGENT

VIDEO_TYPES = ("archive", "highlight", "upload")  # past broadcasts, highlights, uploads


def search_channels(client: TwitchClient, query: str, limit: int = 8) -> list[dict]:
    """
    Streamers matching `query`: [{id, login, name, live}]. An exact login match comes first,
    so typing a full channel name always finds that channel even if Twitch ranks it lower.
    """
    query = query.strip().lstrip("@")
    if not query:
        return []
    found: list[dict] = []
    for c in client.get("search/channels", {"query": query, "first": max(1, min(limit, 25))}).get("data", []):
        found.append({
            "id": str(c.get("id", "")),
            "login": c.get("broadcaster_login", ""),
            "name": c.get("display_name") or c.get("broadcaster_login", ""),
            "live": bool(c.get("is_live")),
        })
    if re.fullmatch(r"\w{1,25}", query):
        try:
            users = client.get("users", {"login": query.lower()}).get("data", [])
        except requests.RequestException:
            users = []  # the search above already worked; skip the exact lookup
        if users:
            u = users[0]
            uid = str(u.get("id", ""))
            exact = next((c for c in found if c["id"] == uid), None) or {
                "id": uid,
                "login": u.get("login", ""),
                "name": u.get("display_name") or u.get("login", ""),
                "live": False,
            }
            found = [exact] + [c for c in found if c["id"] != uid]
    return [c for c in found if c["id"]]


def fetch_videos(client: TwitchClient, user_id: str, vtype: str = "archive",
                 after: str | None = None, first: int = 20) -> tuple[list[dict], str | None]:
    """
    One page of a streamer's VODs, newest first: ([{id, title, date, duration, views, thumb, url}], next_cursor).
    `thumb` is a ready-to-download image URL ("" when Twitch has none yet, e.g. a stream still in progress).
    """
    if vtype not in VIDEO_TYPES:
        vtype = "archive"
    params: dict = {"user_id": user_id, "type": vtype, "sort": "time", "first": max(1, min(first, 100))}
    if after:
        params["after"] = after
    page = client.get("videos", params)
    videos = []
    for v in page.get("data", []):
        thumb = (v.get("thumbnail_url") or "").replace("%{width}", "320").replace("%{height}", "180")
        videos.append({
            "id": str(v.get("id", "")),
            "title": v.get("title") or "(untitled)",
            "date": (v.get("created_at") or "")[:10],
            "duration": parse_twitch_duration(v.get("duration", "")),
            "views": v.get("view_count", 0),
            "thumb": thumb,
            "url": v.get("url") or f"https://www.twitch.tv/videos/{v.get('id', '')}",
        })
    return videos, (page.get("pagination") or {}).get("cursor") or None


def fetch_thumbnail(url: str, user_data_dir_fn=None, user_agent: str = "") -> Path | None:
    """Download a thumbnail once into the per-user cache folder and return its path (None on failure)."""
    if not url:
        return None
    if user_data_dir_fn is None:
        user_data_dir_fn = resolve_dep("user_data_dir", _ORIG_USER_DATA_DIR, user_data_dir)
    if not user_agent:
        user_agent = resolve_dep("USER_AGENT", _ORIG_USER_AGENT, USER_AGENT) or ""

    path = user_data_dir_fn() / "cache" / "thumbs" / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".jpg")
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
        headers = {"User-Agent": user_agent} if user_agent else {}
        r = requests.get(url, timeout=15, headers=headers)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        os.replace(tmp, path)
        return path
    except (requests.RequestException, OSError):
        return None
