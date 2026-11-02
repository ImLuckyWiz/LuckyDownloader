from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from core.errors import EngineError
from core.finalize import (
    GENERIC_NAME_TEMPLATE,
    format_generic_stem,
    part_stem,
)
from core.job import JobOptions
from core.planning import Part
from core.providers import Capability, GenericProvider
from core.source_info import (
    VideoFormat,
    build_generic_download_args,
    build_generic_format_string,
    parse_generic_formats,
    parse_generic_source_info,
    resolve_format,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# YouTube sample fixture parsing
# --------------------------------------------------------------------------- #
def test_parse_youtube_sample():
    info = _load_fixture("youtube_sample.json")
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    prov = GenericProvider("youtube")
    src = prov.parse_info(info, url)

    assert src.id == "dQw4w9WgXcQ"
    assert "Never Gonna Give You Up" in src.title
    assert src.uploader == "Rick Astley"
    assert src.duration == 213.0
    assert src.date == "2009-10-25"
    assert src.site == "youtube"
    assert src.provider is prov
    assert src.twitch_vod_id is None
    assert src.has_capability(Capability.RESOLVE)
    assert not src.has_capability(Capability.TIMELINE)
    assert not src.has_capability(Capability.SEGMENTS)

    # Formats checks
    assert len(src.formats) >= 5
    heights = [vf.height for vf in src.formats if not vf.audio_only]
    assert 2160 in heights
    assert 1080 in heights
    assert 720 in heights
    assert 360 in heights
    # Check descending order of heights
    assert heights == sorted(heights, reverse=True)

    # Audio format check
    audio_fmts = [vf for vf in src.formats if vf.audio_only]
    assert len(audio_fmts) == 1
    assert audio_fmts[0].format_id == "Audio_Only"
    assert audio_fmts[0].container in ("m4a", "webm", "opus", "mp4")

    # Format resolution
    best = resolve_format(src.formats, "best")
    assert best is not None
    assert best.height == 2160

    f1080 = resolve_format(src.formats, "1080p")
    assert f1080 is not None
    assert f1080.height == 1080

    faudio = resolve_format(src.formats, "audio")
    assert faudio is not None
    assert faudio.audio_only is True


# --------------------------------------------------------------------------- #
# TikTok sample fixture parsing
# --------------------------------------------------------------------------- #
def test_parse_tiktok_sample():
    info = _load_fixture("tiktok_sample.json")
    url = "https://www.tiktok.com/@scout2015/video/6718335390845095173"
    prov = GenericProvider("tiktok")
    src = prov.parse_info(info, url)

    assert src.id == "6718335390845095173"
    assert src.uploader == "scout2015"
    assert src.duration == 10.0
    assert src.date == "2019-07-27"
    assert src.site == "tiktok"
    assert src.has_capability(Capability.RESOLVE)
    assert not src.has_capability(Capability.TIMELINE)

    best = resolve_format(src.formats, "best")
    assert best is not None
    assert best.height == 1280


# --------------------------------------------------------------------------- #
# Instagram sample fixture parsing
# --------------------------------------------------------------------------- #
def test_parse_instagram_sample():
    info = _load_fixture("instagram_sample.json")
    url = "https://www.instagram.com/reel/Chunk8-jurw/"
    prov = GenericProvider("instagram")
    src = prov.parse_info(info, url)

    assert src.id == "Chunk8-jurw"
    assert src.uploader == "Instagram"
    assert src.site == "instagram"
    assert src.duration >= 0.0
    assert src.has_capability(Capability.RESOLVE)
    assert not src.has_capability(Capability.TIMELINE)

    best = resolve_format(src.formats, "best")
    assert best is not None
    assert best.height == 1280


# --------------------------------------------------------------------------- #
# Reddit sample fixture parsing
# --------------------------------------------------------------------------- #
def test_parse_reddit_sample():
    info = _load_fixture("reddit_sample.json")
    url = "https://www.reddit.com/r/aww/comments/123456/sample_dog/"
    prov = GenericProvider("reddit")
    src = prov.parse_info(info, url)

    assert src.id == "zv89llsvexdz"
    assert src.title == "That small heart attack."
    assert src.uploader == "Antw87"
    assert src.duration == 12.0
    assert src.site == "reddit"

    heights = [vf.height for vf in src.formats if not vf.audio_only]
    assert heights == [1080, 720, 480, 360]


# --------------------------------------------------------------------------- #
# Playlist & Channel rejection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        {"_type": "playlist", "id": "PL123"},
        {"_type": "channel", "id": "UC123"},
        {"_type": "multi_video", "id": "MV123"},
        {"entries": [{"id": "1"}, {"id": "2"}]},
    ],
)
def test_parse_playlist_rejected(payload):
    with pytest.raises(EngineError, match=r"Playlists and channels are not supported yet"):
        parse_generic_source_info(payload, "https://www.youtube.com/playlist?list=PL123")


# --------------------------------------------------------------------------- #
# Format string builder
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "quality, audio_only, expected",
    [
        ("best", False, "bv*+ba/b"),
        ("BEST AVAILABLE", False, "bv*+ba/b"),
        ("", False, "bv*+ba/b"),
        ("1080p", False, "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"),
        ("720p60", False, "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b"),
        ("480", False, "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b"),
        ("best", True, "ba/b"),
        ("audio", False, "ba/b"),
        ("audio only", False, "ba/b"),
        ("audio_only", False, "ba/b"),
    ],
)
def test_build_generic_format_string(quality, audio_only, expected):
    assert build_generic_format_string(quality=quality, audio_only=audio_only) == expected


# --------------------------------------------------------------------------- #
# Download arguments builder
# --------------------------------------------------------------------------- #
def test_build_generic_download_args_defaults():
    args = build_generic_download_args("https://example.com/video")
    assert "-f" in args
    assert "bv*+ba/b" in args
    assert "--merge-output-format" in args
    assert "mp4" in args
    assert "--concurrent-fragments" in args
    assert "4" in args
    assert args[-1] == "https://example.com/video"


def test_build_generic_download_args_custom_container_and_rate_limit():
    args = build_generic_download_args(
        "https://example.com/video",
        quality="720p",
        container="mkv",
        rate_limit="2.5M",
        threads=8,
        out_template="D:/out/%(title)s.%(ext)s",
    )
    assert "-f" in args
    assert "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b" in args
    assert "--merge-output-format" in args
    assert "mkv" in args
    assert "--limit-rate" in args
    assert "2.5M" in args
    assert "--concurrent-fragments" in args
    assert "8" in args
    assert "-o" in args
    assert "D:/out/%(title)s.%(ext)s" in args


def test_build_generic_download_args_audio_only():
    args_mp3 = build_generic_download_args(
        "https://example.com/video",
        audio_only=True,
        container="mp3",
    )
    assert "-f" in args_mp3
    assert "ba/b" in args_mp3
    assert "-x" in args_mp3
    assert "--audio-format" in args_mp3
    assert "mp3" in args_mp3
    assert "--merge-output-format" not in args_mp3

    args_m4a = build_generic_download_args(
        "https://example.com/video",
        audio_only=True,
        audio_format="m4a",
    )
    assert "-x" in args_m4a
    assert "--audio-format" in args_m4a
    assert "m4a" in args_m4a


# --------------------------------------------------------------------------- #
# Generic naming templates & part_stem
# --------------------------------------------------------------------------- #
def test_format_generic_stem():
    info = _load_fixture("youtube_sample.json")
    src = GenericProvider("youtube").parse_info(info, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    stem = format_generic_stem(src, GENERIC_NAME_TEMPLATE)
    assert stem == "Rick Astley - 2009-10-25 - Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster) [dQw4w9WgXcQ]"

    custom = "{site} - {uploader} - {id}"
    assert format_generic_stem(src, custom) == "youtube - Rick Astley - dQw4w9WgXcQ"


def test_part_stem_routing():
    part = Part(index=1, start=0.0, end=100.0)

    # Twitch source info
    twitch_src = parse_generic_source_info(
        {"id": "999", "title": "Twitch Stream", "uploader": "streamer", "upload_date": "20261102"},
        "https://www.twitch.tv/videos/999",
    )
    twitch_src.twitch_vod_id = 999
    twitch_src.site = "twitch"
    opts = JobOptions(cut_text="", out_dir="", name_template="{channel} - {title}")
    assert part_stem(twitch_src, opts=opts, part=part, total=1) == "streamer - Twitch Stream"

    # Generic source info
    generic_src = parse_generic_source_info(
        {"id": "yt123", "title": "My Cool Video", "uploader": "creator", "upload_date": "20261102"},
        "https://youtube.com/watch?v=yt123",
    )
    generic_src.twitch_vod_id = None
    generic_src.site = "youtube"
    opts_generic = JobOptions(cut_text="", out_dir="", generic_name_template="{uploader} - {title} [{id}]")
    assert part_stem(generic_src, opts=opts_generic, part=part, total=1) == "creator - My Cool Video [yt123]"


# --------------------------------------------------------------------------- #
# GenericProvider.get_source_info error handling
# --------------------------------------------------------------------------- #
def test_generic_provider_empty_or_multiline_url():
    prov = GenericProvider()
    with pytest.raises(EngineError, match=r"Paste a video URL"):
        prov.get_source_info("")
    with pytest.raises(EngineError, match=r"Paste a video URL"):
        prov.get_source_info("   ")
    with pytest.raises(EngineError, match=r"single URL"):
        prov.get_source_info("http://a.com\nhttp://b.com")


def test_generic_provider_missing_tool(monkeypatch):
    monkeypatch.setattr("core.providers.generic.find_tool", lambda name: None)
    prov = GenericProvider()
    with pytest.raises(EngineError, match=r"yt-dlp is not installed yet"):
        prov.get_source_info("https://youtube.com/watch?v=123")


def test_generic_provider_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=180)

    monkeypatch.setattr("core.providers.generic.find_tool", lambda name: "fake_ytdlp")
    monkeypatch.setattr("subprocess.run", fake_run)
    prov = GenericProvider()
    with pytest.raises(EngineError, match=r"yt-dlp took too long"):
        prov.get_source_info("https://youtube.com/watch?v=123")


def test_generic_provider_failed_exit(monkeypatch):
    class FakeProc:
        returncode = 1
        stderr = "ERROR: Completely unexpected failure xyz occurred"
        stdout = ""

    monkeypatch.setattr("core.providers.generic.find_tool", lambda name: "fake_ytdlp")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeProc())
    prov = GenericProvider()
    with pytest.raises(EngineError, match=r"yt-dlp could not read that URL"):
        prov.get_source_info("https://youtube.com/watch?v=123")


def test_generic_provider_mapped_error(monkeypatch):
    class FakeProc:
        returncode = 1
        stderr = "ERROR: Private video"
        stdout = ""

    monkeypatch.setattr("core.providers.generic.find_tool", lambda name: "fake_ytdlp")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeProc())
    prov = GenericProvider()
    with pytest.raises(EngineError, match=r"Private video"):
        prov.get_source_info("https://youtube.com/watch?v=123")


def test_generic_provider_invalid_json(monkeypatch):
    class FakeProc:
        returncode = 0
        stderr = ""
        stdout = "Not JSON at all"

    monkeypatch.setattr("core.providers.generic.find_tool", lambda name: "fake_ytdlp")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeProc())
    prov = GenericProvider()
    with pytest.raises(EngineError, match=r"returned unreadable data"):
        prov.get_source_info("https://youtube.com/watch?v=123")


# --------------------------------------------------------------------------- #
# Phase 4 Error Mapping & Cookies Tests
# --------------------------------------------------------------------------- #
def test_map_generic_error_samples():
    from core.providers.generic import map_generic_error

    # 1. Unsupported URL
    msg = map_generic_error("ERROR: Unsupported URL: https://unknown.site/video")
    assert "Unsupported URL" in msg

    # 2. Private video
    msg = map_generic_error("ERROR: This video is private")
    assert "Private video" in msg

    # 3. Age restricted
    msg = map_generic_error("ERROR: Sign in to confirm your age. This video may be inappropriate for some users.")
    assert "Age-restricted" in msg
    assert "browser cookies" in msg

    # 4. Login required
    msg = map_generic_error("ERROR: Sign in to confirm you are not a bot. Login required.")
    assert "Login required" in msg
    assert "browser cookies" in msg

    # 5. Geoblocked
    msg = map_generic_error("ERROR: This video is not available in your country due to geographic restrictions.")
    assert "Geoblocked" in msg

    # 6. Rate limited
    msg = map_generic_error("ERROR: HTTP Error 429: Too Many Requests. Rate limit exceeded.")
    assert "Rate limited" in msg

    # 7. Extractor failure
    msg = map_generic_error("ERROR: Unable to extract video data; signature extraction failed")
    assert "Extractor error" in msg
    assert "updating yt-dlp" in msg

    # 8. Network error
    msg = map_generic_error("ERROR: Unable to download webpage: <urlopen error timed out>")
    assert "Network error" in msg

    # 9. 404 Video unavailable
    msg = map_generic_error("ERROR: Video unavailable. HTTP Error 404: Not Found")
    assert "Video unavailable" in msg


def test_build_generic_download_args_cookies():
    from core.source_info import build_generic_download_args

    args_no_cookies = build_generic_download_args("https://youtube.com/watch?v=123")
    assert "--cookies-from-browser" not in args_no_cookies

    args_chrome = build_generic_download_args("https://youtube.com/watch?v=123", cookies_browser="chrome")
    assert "--cookies-from-browser" in args_chrome
    idx = args_chrome.index("--cookies-from-browser")
    assert args_chrome[idx + 1] == "chrome"

    args_none = build_generic_download_args("https://youtube.com/watch?v=123", cookies_browser="None")
    assert "--cookies-from-browser" not in args_none


def test_generic_provider_build_download_args_cookies():
    prov = GenericProvider("youtube")
    from core.source_info import SourceInfo
    src = SourceInfo(
        url="https://youtube.com/watch?v=123",
        id="123",
        title="Test",
        uploader="Rick",
        duration=100.0,
        date="2026-01-01",
        site="youtube",
    )
    opts = JobOptions(cut_text="", out_dir="", cookies_browser="firefox")
    args = prov.build_download_args(src, opts)
    assert "--cookies-from-browser" in args
    idx = args.index("--cookies-from-browser")
    assert args[idx + 1] == "firefox"


def test_generic_provider_get_source_info_passes_cookies(monkeypatch):
    captured_cmd = []

    class FakeProc:
        returncode = 0
        stderr = ""
        stdout = '{"id": "123", "title": "Vid", "duration": 10}'

    def fake_run(cmd, *args, **kwargs):
        captured_cmd.extend(cmd)
        return FakeProc()

    monkeypatch.setattr("core.providers.generic.find_tool", lambda name: "fake_ytdlp")
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("core.settings.load_settings", lambda: {"cookies_from_browser": "edge"})

    prov = GenericProvider("youtube")
    prov.get_source_info("https://youtube.com/watch?v=123")

    assert "--cookies-from-browser" in captured_cmd
    idx = captured_cmd.index("--cookies-from-browser")
    assert captured_cmd[idx + 1] == "edge"


def test_generic_run_job_uses_generic_format_string_and_cookies(monkeypatch, tmp_path):
    from core.finalize import run_job
    from core.job import Job, JobOptions
    from core.runtime import Ctx
    from core.source_info import SourceInfo, VideoFormat
    import luckytwitch_engine as eng

    formats = [
        VideoFormat(format_id="1080p", height=1080, fps=60, container="mp4"),
        VideoFormat(format_id="720p", height=720, fps=30, container="mp4"),
    ]
    src = SourceInfo(
        url="https://youtube.com/watch?v=abc1234",
        id="abc1234",
        title="Test Generic Video",
        uploader="Channel",
        duration=60.0,
        date="2026-11-02",
        site="youtube",
        formats=formats,
    )
    opts = JobOptions(
        cut_text="",
        out_dir=str(tmp_path / "out"),
        strategy="full",
        quality="1080p",
        cookies_browser="brave",
    )
    job = Job(source=src, opts=opts)

    captured_kw = {}
    raw = tmp_path / "full.mp4"
    raw.write_bytes(b"x" * 1024)

    def fake_dl_full(ctx, url, workdir, threads, **kw):
        captured_kw.update(kw)
        return raw

    monkeypatch.setattr(eng, "find_tool", lambda name: "fake_" + name)
    monkeypatch.setattr(eng, "download_full", fake_dl_full)
    monkeypatch.setattr(eng, "finalize_part", lambda *a, **k: tmp_path / "out" / "final.mp4")

    ctx = Ctx()
    run_job(job, ctx)

    assert "format_id" in captured_kw
    assert captured_kw["format_id"] == "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"
    assert captured_kw.get("cookies_browser") == "brave"


def test_get_source_info_passes_cookies_and_remote_components(monkeypatch):
    import subprocess
    from core.source_info import get_source_info

    captured_cmd = []

    def fake_run(cmd, **kw):
        captured_cmd.extend(cmd)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"id": "123", "title": "Test", "duration": 100, "uploader": "Me"}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("luckytwitch_engine.find_tool", lambda name: "fake_ytdlp")

    get_source_info("https://www.youtube.com/watch?v=123", cookies_browser="firefox")

    assert "--cookies-from-browser" in captured_cmd
    idx = captured_cmd.index("--cookies-from-browser")
    assert captured_cmd[idx + 1] == "firefox"
    assert "--remote-components" in captured_cmd
    idx_rc = captured_cmd.index("--remote-components")
    assert captured_cmd[idx_rc + 1] == "ejs:github"
    assert "--extractor-args" in captured_cmd
    idx_ea = captured_cmd.index("--extractor-args")
    assert captured_cmd[idx_ea + 1] == "youtube:player_client=web_safari,web"
