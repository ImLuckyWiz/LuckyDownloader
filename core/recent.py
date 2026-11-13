"""Streamers picked in the Search tab (copied from luckytwitch_downloader.py)."""

from __future__ import annotations

import json

from core import paths


def _load_channels(path, limit: int | None = None) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        from core.files import backup_corrupt_json
        backup_corrupt_json(path)
        return []
    except OSError:
        return []
    if not isinstance(data, list):
        from core.files import backup_corrupt_json
        backup_corrupt_json(path)
        return []
    out = []
    for c in data:
        if isinstance(c, dict) and c.get("id"):
            login = str(c.get("login") or "")
            out.append({"id": str(c["id"]), "login": login, "name": str(c.get("name") or login)})
    return out[:limit] if limit is not None else out


def _save_channels(path, items: list[dict]) -> None:
    try:
        from core.files import atomic_write_json
        atomic_write_json(path, items, ensure_ascii=False)
    except OSError:
        pass


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
    try:
        data = json.loads(paths.RECENT_SEARCHES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        from core.files import backup_corrupt_json
        backup_corrupt_json(paths.RECENT_SEARCHES_PATH)
        return []
    except OSError:
        return []
    if not isinstance(data, list):
        from core.files import backup_corrupt_json
        backup_corrupt_json(paths.RECENT_SEARCHES_PATH)
        return []
    out = []
    for c in data:
        if isinstance(c, dict) and c.get("name"):
            name = str(c["name"])
            out.append({"id": str(c.get("id") or name), "login": str(c.get("login") or name), "name": name})
    return out[:paths.MAX_RECENT]


def save_recent_searches(items: list[dict]) -> None:
    try:
        from core.files import atomic_write_json
        atomic_write_json(paths.RECENT_SEARCHES_PATH, items, ensure_ascii=False)
    except OSError:
        pass
