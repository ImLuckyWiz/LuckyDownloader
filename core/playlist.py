"""
Playlist and channel utilities: range parsing, item selection, and job expansion.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from core.errors import EngineError
from core.i18n import t

if TYPE_CHECKING:
    from core.job import Job, JobOptions
    from core.source_info import PlaylistInfo, PlaylistItem, SourceInfo


def parse_item_range(text: str, max_items: int) -> set[int]:
    """Parse range expressions like '1-5, 8, 11-15', '3-', '-4', or 'all' into 1-based indices.

    Out-of-range indices (< 1 or > max_items) are ignored.
    """
    s = (text or "").strip().lower()
    if not s or max_items <= 0:
        return set()

    if s in ("all", "*", "everything"):
        return set(range(1, max_items + 1))

    result: set[int] = set()
    tokens = re.split(r"[,;\s]+", s)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            raw_start, raw_end = parts[0].strip(), parts[1].strip()
            try:
                start = int(raw_start) if raw_start else 1
            except ValueError:
                continue
            try:
                end = int(raw_end) if raw_end else max_items
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for idx in range(start, end + 1):
                if 1 <= idx <= max_items:
                    result.add(idx)
        else:
            try:
                val = int(token)
                if 1 <= val <= max_items:
                    result.add(val)
            except ValueError:
                continue

    return result


def expand_playlist_jobs(
    playlist: PlaylistInfo,
    items: Sequence[PlaylistItem],
    opts: JobOptions,
    *,
    skip_existing: bool = False,
    archive_file: str | None = None,
) -> list[Job]:
    """Expand picked playlist items into individual Jobs with shared options and isolated temp folders."""
    from core.job import Job
    from core.source_info import SourceInfo

    if not items:
        return []

    # If skipping existing items, ensure download archive path is set
    out_dir = opts.out_dir or "."
    final_archive = ""
    if skip_existing:
        if archive_file:
            final_archive = archive_file
        else:
            final_archive = str(Path(out_dir) / ".lucky_download_archive.txt")

    jobs: list[Job] = []
    for item in items:
        if not item.url.startswith(("http://", "https://")):
            continue
        src = SourceInfo(
            url=item.url,
            id=item.id,
            title=item.title,
            uploader=item.uploader or playlist.uploader,
            duration=item.duration,
            date="",
            twitch_vod_id=None,
            segments=[],
            storyboard=None,
            muted=None,
            formats=[],
            thumbnail=item.thumbnail,
            site=playlist.site,
            provider=playlist.provider,
        )

        job_opts = replace(
            opts,
            cut_text="",
            strategy="full",
            keep_full=False,
            sidecar=False,
            chapters=False,
            game_markers=False,
            muted_markers=False,
            chat=False,
            chat_render=False,
            premiere_xml=False,
            premiere_plugin=False,
            download_archive=final_archive if skip_existing else getattr(opts, "download_archive", ""),
        )

        jobs.append(Job(src, job_opts, clips=None, client=None))

    return jobs
