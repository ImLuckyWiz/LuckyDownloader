"""Streamers picked in the Search tab (copied from luckytwitch_downloader.py)."""

from __future__ import annotations

import json

from core import paths


def load_recent() -> list[dict]:
    """Streamers picked in the Search tab, most recent first: [{id, login, name}]."""
    try:
        data = json.loads(paths.RECENT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for c in data:
        if isinstance(c, dict) and c.get("id"):
            login = str(c.get("login") or "")
            out.append({"id": str(c["id"]), "login": login, "name": str(c.get("name") or login)})
    return out[:paths.MAX_RECENT]


def save_recent(items: list[dict]) -> None:
    try:
        from core.files import atomic_write_json
        atomic_write_json(paths.RECENT_PATH, items, ensure_ascii=False)
    except OSError:
        pass


def load_recent_searches() -> list[dict]:
    """Recent generic/YouTube searches or channels: [{id, login, name}]."""
    try:
        data = json.loads(paths.RECENT_SEARCHES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
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
