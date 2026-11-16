"""Download history tracking finished jobs (VOD id, title, streamer, date, parts, folder, quality)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import paths
from core.files import JsonStore


@dataclass
class HistoryEntry:
    vod_id: str
    title: str = ""
    streamer: str = ""
    date: str = ""
    downloaded_at: str = ""
    parts: int = 1
    folder: str = ""
    quality: str = ""
    site: str = "twitch"
    url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            vod_id=str(data.get("vod_id", "")),
            title=str(data.get("title", "")),
            streamer=str(data.get("streamer", "")),
            date=str(data.get("date", "")),
            downloaded_at=str(data.get("downloaded_at", "") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
            parts=int(data.get("parts", 1) or 1),
            folder=str(data.get("folder", "")),
            quality=str(data.get("quality", "")),
            site=str(data.get("site", "twitch") or "twitch"),
            url=str(data.get("url", "") or ""),
        )


def _history_file(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return getattr(paths, "HISTORY_PATH", paths.DATA_DIR / "luckytwitch_history.json")


_HISTORY_STORE: JsonStore[list[HistoryEntry]] = JsonStore(
    lambda: _history_file(),
    list,
    expected_type=list,
    ensure_ascii=False,
    serializer=lambda entries: [asdict(e) for e in entries],
    deserializer=lambda data: [
        HistoryEntry.from_dict(item)
        for item in data
        if isinstance(item, dict) and (item.get("vod_id") or item.get("url"))
    ],
)


def load_history(path: Path | None = None) -> list[HistoryEntry]:
    """Read history from JSON; returns empty list on any error or missing file."""
    return _HISTORY_STORE.load(path=_history_file(path))


def save_history(entries: list[HistoryEntry], path: Path | None = None) -> None:
    """Save history entries to JSON safely."""
    _HISTORY_STORE.save(entries, path=_history_file(path))


def record_download(
    entry: HistoryEntry | dict[str, Any],
    path: Path | None = None,
    enabled: bool = True,
    max_entries: int = 500,
) -> list[HistoryEntry]:
    """Record a finished download. If enabled is False, does not write anything."""
    target = _history_file(path)
    with _HISTORY_STORE.lock(target):
        if not enabled:
            return load_history(target)
        item = entry if isinstance(entry, HistoryEntry) else HistoryEntry.from_dict(entry)
        if not item.vod_id and not item.url:
            return load_history(target)
        if not item.downloaded_at:
            item.downloaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        def _matches(a: HistoryEntry, b: HistoryEntry) -> bool:
            if a.folder != b.folder:
                return False
            if a.vod_id and b.vod_id and a.vod_id == b.vod_id:
                return True
            if a.url and b.url and a.url == b.url:
                return True
            return False

        def _apply(entries: list[HistoryEntry]) -> list[HistoryEntry]:
            filtered = [e for e in entries if not _matches(e, item)]
            filtered.insert(0, item)
            if len(filtered) > max_entries:
                filtered = filtered[:max_entries]
            return filtered

        return _HISTORY_STORE.update(_apply, path=target)


def clear_history(path: Path | None = None) -> None:
    """Clear all recorded download history."""
    _HISTORY_STORE.clear(path=_history_file(path))


def is_downloaded(
    vod_id: str | None = None,
    path: Path | None = None,
    *,
    url: str | None = None,
) -> HistoryEntry | None:
    """Check if a VOD id or URL is recorded in history; returns the latest entry or None."""
    target_id = str(vod_id).strip() if vod_id else ""
    target_url = str(url).strip() if url else ""
    if not target_id and not target_url:
        return None
    target = _history_file(path)
    with _HISTORY_STORE.lock(target):
        for e in load_history(target):
            if target_id and (e.vod_id == target_id or (e.url and e.url == target_id)):
                return e
            if target_url and (e.url == target_url or (e.vod_id and e.vod_id == target_url)):
                return e
    return None
