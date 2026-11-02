"""Channel and streamer watch list (pins channels and checks for new videos/VODs on start / periodic throttle)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import paths


@dataclass
class WatchedChannel:
    login: str
    name: str = ""
    provider: str = "twitch"
    url: str = ""
    last_vod_id: str = ""
    last_seen_date: str = ""
    last_checked_at: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WatchedChannel:
        login = str(data.get("login") or data.get("channel_id") or data.get("id") or "").strip()
        prov = str(data.get("provider") or "twitch").lower().strip()
        if prov == "twitch":
            login = login.lower()
        url = str(data.get("url") or "").strip()
        if not url and login:
            if prov == "twitch":
                url = f"https://www.twitch.tv/{login}"
            elif prov == "youtube":
                url = f"https://www.youtube.com/{login}" if login.startswith("@") else f"https://www.youtube.com/@{login}"
        return cls(
            login=login,
            name=str(data.get("name") or login).strip(),
            provider=prov,
            url=url,
            last_vod_id=str(data.get("last_vod_id") or data.get("last_item_id") or "").strip(),
            last_seen_date=str(data.get("last_seen_date", "")).strip(),
            last_checked_at=float(data.get("last_checked_at", 0.0) or 0.0),
        )


WatchedStreamer = WatchedChannel


def _watchlist_file(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return getattr(paths, "WATCHLIST_PATH", paths.DATA_DIR / "luckytwitch_watchlist.json")


def load_watchlist(path: Path | None = None) -> list[WatchedChannel]:
    """Read watch list from JSON. Silent on missing/corrupt file."""
    f = _watchlist_file(path)
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [
                WatchedChannel.from_dict(d)
                for d in data
                if isinstance(d, dict) and (d.get("login") or d.get("id") or d.get("url"))
            ]
    except Exception:
        pass
    return []


def save_watchlist(watchers: list[WatchedChannel], path: Path | None = None) -> None:
    """Save watch list to JSON safely."""
    f = _watchlist_file(path)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        raw = [asdict(w) for w in watchers]
        f.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def add_to_watchlist(
    login: str,
    name: str = "",
    provider: str = "twitch",
    url: str = "",
    path: Path | None = None,
) -> list[WatchedChannel]:
    """Pin a channel / streamer to the watch list."""
    clean_login = login.strip()
    clean_prov = provider.lower().strip()
    if clean_prov == "twitch":
        clean_login = clean_login.lower()
    if not clean_login and not url:
        return load_watchlist(path)
    if not url and clean_login:
        if clean_prov == "twitch":
            url = f"https://www.twitch.tv/{clean_login}"
        elif clean_prov == "youtube":
            url = f"https://www.youtube.com/{clean_login}" if clean_login.startswith("@") else f"https://www.youtube.com/@{clean_login}"

    watchers = load_watchlist(path)
    for w in watchers:
        if (clean_login and w.login == clean_login and w.provider == clean_prov) or (url and w.url == url):
            if name and not w.name:
                w.name = name
                save_watchlist(watchers, path)
            return watchers

    watchers.append(WatchedChannel(
        login=clean_login,
        name=name or clean_login,
        provider=clean_prov,
        url=url,
    ))
    save_watchlist(watchers, path)
    return watchers


def remove_from_watchlist(
    login: str,
    provider: str = "twitch",
    path: Path | None = None,
) -> list[WatchedChannel]:
    """Unpin a channel from the watch list."""
    clean_login = login.strip()
    clean_prov = provider.lower().strip()
    if clean_prov == "twitch":
        clean_login = clean_login.lower()
    watchers = [
        w for w in load_watchlist(path)
        if not (
            (w.login == clean_login or (w.url and clean_login in w.url))
            and (not clean_prov or w.provider == clean_prov)
        )
    ]
    save_watchlist(watchers, path)
    return watchers


def is_watched(
    login: str,
    provider: str = "twitch",
    path: Path | None = None,
) -> bool:
    """Check if a channel / streamer login or URL is pinned."""
    clean_login = str(login or "").strip()
    clean_prov = provider.lower().strip()
    if clean_prov == "twitch":
        clean_login = clean_login.lower()
    for w in load_watchlist(path):
        if clean_prov and w.provider != clean_prov:
            continue
        if w.login == clean_login or (w.url and clean_login in w.url):
            return True
    return False


def check_channel_new_items(
    client: Any,
    watcher: WatchedChannel,
    throttle_seconds: int = 300,
    now: float | None = None,
) -> tuple[WatchedChannel, list[dict]]:
    """Look for items newer than the last seen one for this channel.

    Silent on failure; respects throttle_seconds between network calls.
    """
    current_time = time.time() if now is None else now
    if current_time - watcher.last_checked_at < throttle_seconds:
        return watcher, []

    watcher.last_checked_at = current_time

    items: list[dict] = []
    if watcher.provider == "twitch":
        if not client:
            return watcher, []
        try:
            vods = client.get_channel_videos(watcher.login, first=6)
            if isinstance(vods, list):
                items = vods
        except Exception:
            return watcher, []
    elif watcher.provider == "youtube":
        try:
            from core.providers import YOUTUBE_PROVIDER
            target = watcher.url or watcher.login
            videos, _ = YOUTUBE_PROVIDER.fetch_channel_videos(target, limit=6)
            if isinstance(videos, list):
                items = videos
        except Exception:
            return watcher, []

    if not items:
        return watcher, []

    new_items = []
    first_id = str(items[0].get("id", "")) if items else ""
    first_date = str(items[0].get("created_at", "") or items[0].get("date", "")) if items else ""

    if not watcher.last_vod_id:
        # First time tracking: record current top item as baseline without notification
        watcher.last_vod_id = first_id
        watcher.last_seen_date = first_date
        return watcher, []

    for v in items:
        vid = str(v.get("id", ""))
        vdate = str(v.get("created_at", "") or v.get("date", ""))
        if vid == watcher.last_vod_id:
            break
        if watcher.last_seen_date and vdate and vdate <= watcher.last_seen_date:
            break
        new_items.append(v)

    if new_items:
        watcher.last_vod_id = first_id
        watcher.last_seen_date = first_date

    return watcher, new_items


check_streamer_new_vods = check_channel_new_items


def check_all_watchers(
    client: Any,
    path: Path | None = None,
    throttle_seconds: int = 300,
) -> dict[str, list[dict]]:
    """Check all watched channels/streamers for new items and update the watch list."""
    watchers = load_watchlist(path)
    results: dict[str, list[dict]] = {}
    changed = False

    for w in watchers:
        updated, new_items = check_channel_new_items(client, w, throttle_seconds=throttle_seconds)
        if new_items:
            key = f"{w.provider}:{w.login}" if w.provider != "twitch" else w.login
            results[key] = new_items
        if updated.last_checked_at != w.last_checked_at or updated.last_vod_id != w.last_vod_id:
            changed = True

    if changed:
        save_watchlist(watchers, path)

    return results
