from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.options import JobOptions
from core.playlist import expand_playlist_jobs, parse_item_range
from core.providers import Capability, GenericProvider
from core.source_info import (
    PlaylistInfo,
    PlaylistItem,
    build_generic_download_args,
    is_playlist_dict,
    parse_playlist_info,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_is_playlist_dict():
    assert is_playlist_dict({"_type": "playlist"}) is True
    assert is_playlist_dict({"_type": "channel"}) is True
    assert is_playlist_dict({"_type": "multi_video"}) is True
    assert is_playlist_dict({"entries": []}) is True
    assert is_playlist_dict({"id": "123", "title": "video"}) is False
    assert is_playlist_dict({}) is False


def test_parse_playlist_fixture():
    fixture_path = FIXTURES_DIR / "playlist_sample.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    url = "https://www.youtube.com/playlist?list=PLBCF2DAC6FFB574DE"
    pl = parse_playlist_info(data, url)

    assert isinstance(pl, PlaylistInfo)
    assert pl.id == "PLBCF2DAC6FFB574DE"
    assert pl.title == "Google Search Stories"
    assert pl.uploader == "Google Search Stories"
    assert len(pl.entries) == 5

    # Check entries
    e0 = pl.entries[0]
    assert isinstance(e0, PlaylistItem)
    assert e0.id == "GvgqDSnpRQM"
    assert e0.title == "Andrew Willis, Skatepark Engineer"
    assert e0.duration == 90.0
    assert e0.url == "https://www.youtube.com/watch?v=GvgqDSnpRQM"
    assert e0.index == 1
    assert "hqdefault.jpg" in e0.thumbnail

    e4 = pl.entries[4]
    assert e4.index == 5
    assert e4.id != ""


def test_playlist_provider_capabilities():
    prov = GenericProvider("youtube")
    assert prov.has_capability(Capability.PLAYLIST)
    assert prov.has_capability(Capability.RESOLVE)

    fixture_path = FIXTURES_DIR / "playlist_sample.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    pl = prov.parse_playlist_info(data, "https://www.youtube.com/playlist?list=PLBCF2DAC6FFB574DE")
    assert pl.site == "youtube"
    assert pl.has_capability(Capability.PLAYLIST)


@pytest.mark.parametrize(
    "text, max_items, expected",
    [
        ("", 10, set()),
        ("all", 5, {1, 2, 3, 4, 5}),
        ("*", 3, {1, 2, 3}),
        ("1", 5, {1}),
        ("3", 5, {3}),
        ("1-3", 5, {1, 2, 3}),
        ("3-1", 5, {1, 2, 3}),
        ("1, 3, 5", 6, {1, 3, 5}),
        ("1-2, 4-5", 5, {1, 2, 4, 5}),
        ("3-", 5, {3, 4, 5}),
        ("-3", 5, {1, 2, 3}),
        ("0, 6, 7", 5, set()),  # out of bounds ignored
        ("1-10", 4, {1, 2, 3, 4}),  # clamped to max_items
        ("foo, 2, bar", 5, {2}),  # invalid tokens ignored
    ],
)
def test_parse_item_range(text, max_items, expected):
    assert parse_item_range(text, max_items) == expected


def test_expand_playlist_jobs(tmp_path):
    pl = PlaylistInfo(
        id="PLtest",
        title="My Playlist",
        url="https://www.youtube.com/playlist?list=PLtest",
        uploader="ChannelName",
        site="youtube",
        entries=[
            PlaylistItem(id="vid1", title="Video One", url="https://youtube.com/watch?v=vid1", duration=100.0, index=1),
            PlaylistItem(id="vid2", title="Video Two", url="https://youtube.com/watch?v=vid2", duration=200.0, index=2),
        ],
    )

    base_opts = JobOptions(
        cut_text="0:00 - 1:00",
        out_dir=str(tmp_path / "downloads"),
        container="mp4",
        quality="1080p",
    )

    # 1. Expand without download archive
    jobs = expand_playlist_jobs(pl, pl.entries, base_opts, skip_existing=False)
    assert len(jobs) == 2
    assert jobs[0].source.id == "vid1"
    assert jobs[0].source.title == "Video One"
    assert jobs[0].source.uploader == "ChannelName"
    assert jobs[0].opts.out_dir == str(tmp_path / "downloads")
    assert jobs[0].opts.quality == "1080p"
    assert jobs[0].opts.cut_text == ""  # full video, no partial cut
    assert jobs[0].opts.download_archive == ""

    assert jobs[1].source.id == "vid2"

    # 2. Expand with download archive
    jobs_archive = expand_playlist_jobs(pl, pl.entries, base_opts, skip_existing=True)
    assert len(jobs_archive) == 2
    expected_archive = str(Path(tmp_path / "downloads") / ".lucky_download_archive.txt")
    assert jobs_archive[0].opts.download_archive == expected_archive
    assert jobs_archive[1].opts.download_archive == expected_archive


def test_build_generic_download_args_with_archive():
    args = build_generic_download_args(
        "https://www.youtube.com/watch?v=sample",
        download_archive="/path/to/archive.txt",
    )
    assert "--download-archive" in args
    idx = args.index("--download-archive")
    assert args[idx + 1] == "/path/to/archive.txt"


def test_parse_playlist_info_youtube_thumbnail_fallback():
    # When yt-dlp flat playlist does not return thumbnail or thumbnails for an entry
    data = {
        "_type": "playlist",
        "id": "PL123",
        "title": "Sample Playlist",
        "uploader": "Sample Channel",
        "entries": [
            {
                "id": "dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "duration": 213,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                # no thumbnail or thumbnails field
            }
        ],
    }
    pl = parse_playlist_info(data, "https://www.youtube.com/playlist?list=PL123")
    assert pl.entries[0].thumbnail == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert pl.thumbnail == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_run_ytdlp_forwards_download_archive(monkeypatch):
    import luckytwitch_engine as eng
    from core.download import run_ytdlp

    recorded = []
    monkeypatch.setattr(eng, "find_tool", lambda n: "yt-dlp")

    class FakeProc:
        def __init__(self, cmd, **kw):
            self.cmd = cmd
            self.stdout = iter([])
            self.returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(eng.subprocess, "Popen", lambda cmd, **kw: (recorded.append(cmd), FakeProc(cmd))[1])
    ctx = eng.Ctx()
    run_ytdlp(ctx, ["https://youtube.com/watch?v=123"], threads=4, download_archive="/tmp/archive.txt")

    assert len(recorded) == 1
    cmd = recorded[0]
    assert "--download-archive" in cmd
    idx = cmd.index("--download-archive")
    assert cmd[idx + 1] == "/tmp/archive.txt"


def test_run_job_forwards_download_archive_and_handles_archive_skip(monkeypatch, tmp_path):
    import luckytwitch_engine as eng

    pl = PlaylistInfo(
        id="PLtest",
        title="My Playlist",
        url="https://www.youtube.com/playlist?list=PLtest",
        uploader="ChannelName",
        site="youtube",
        provider=GenericProvider("youtube"),
        entries=[
            PlaylistItem(id="vid1", title="Video One", url="https://youtube.com/watch?v=vid1", duration=100.0, index=1),
        ],
    )
    base_opts = JobOptions(
        cut_text="",
        out_dir=str(tmp_path / "downloads"),
        container="mp4",
        quality="best",
    )
    jobs = expand_playlist_jobs(pl, pl.entries, base_opts, skip_existing=True)
    assert len(jobs) == 1
    job = jobs[0]
    expected_archive = str(Path(tmp_path / "downloads") / ".lucky_download_archive.txt")
    assert job.opts.download_archive == expected_archive

    monkeypatch.setattr(eng, "find_tool", lambda n: "fake_tool")
    recorded_kw = {}

    def fake_ytdlp_skip(ctx, args, threads, **kw):
        recorded_kw.update(kw)
        # Simulate yt-dlp skipping an archived video: exits 0 without writing any file

    monkeypatch.setattr(eng, "run_ytdlp", fake_ytdlp_skip)
    logs = []
    ctx = eng.Ctx(log=logs.append)
    results = eng.run_job(job, ctx)

    assert recorded_kw.get("download_archive") == expected_archive
    assert results == []
    assert any("archive" in m.lower() for m in logs)

