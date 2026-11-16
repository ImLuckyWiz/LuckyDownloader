"""Streamers picked in the Search tab (copied from luckytwitch_downloader.py)."""

from __future__ import annotations

from core import paths
from core.files import JsonStore

_CHANNELS_STORE: JsonStore[list[dict]] = JsonStore(
    lambda: paths.RECENT_PATH,
    list,
    expected_type=list,
    ensure_ascii=False,
)

_RECENT_SEARCHES_STORE: JsonStore[list[dict]] = JsonStore(
    lambda: paths.RECENT_SEARCHES_PATH,
    list,
    expected_type=list,
    ensure_ascii=False,
)


def _load_channels(path, limit: int | None = None) -> list[dict]:
    data = _CHANNELS_STORE.load(path=path)
    out = []
    for c in data:
        if isinstance(c, dict) and c.get("id"):
            login = str(c.get("login") or "")
            out.append({"id": str(c["id"]), "login": login, "name": str(c.get("name") or login)})
    return out[:limit] if limit is not None else out


def _save_channels(path, items: list[dict]) -> None:
    _CHANNELS_STORE.save(items, path=path)


def load_recent() -> list[dict]:
    """Streamers picked in the Search tab, most recent first: [{id, login, name}]."""
    return _load_channels(paths.RECENT_PATH, limit=paths.MAX_RECENT)


def save_recent(items: list[dict]) -> None:
    _save_channels(paths.RECENT_PATH, items)


def load_favorites() -> list[dict]:
    """Favorite streamers saved in the Search tab: [{id, login, name}]."""
    return _load_channels(paths.FAVORITES_PATH)


def save_favorites(items: list[dict]) -> None:
    _save_channels(paths.FAVORITES_PATH, items)


def load_recent_searches() -> list[dict]:
    """Recent generic/YouTube searches or channels: [{id, login, name}]."""
    data = _RECENT_SEARCHES_STORE.load(path=paths.RECENT_SEARCHES_PATH)
    out = []
    for c in data:
        if isinstance(c, dict) and c.get("name"):
            name = str(c["name"])
            out.append({"id": str(c.get("id") or name), "login": str(c.get("login") or name), "name": name})
    return out[:paths.MAX_RECENT]


def save_recent_searches(items: list[dict]) -> None:
    _RECENT_SEARCHES_STORE.save(items, path=paths.RECENT_SEARCHES_PATH)
