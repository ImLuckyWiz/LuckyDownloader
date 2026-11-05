from __future__ import annotations

import pytest

from core.providers import (
    ALL_PROVIDERS,
    Capability,
    GenericProvider,
    Provider,
    TwitchProvider,
    YouTubeProvider,
    detect_source,
    get_browsable_providers,
    is_twitch_source,
    is_web_url,
)
from core.providers.youtube import _format_yt_date, _parse_yt_entry
from core.source_info import SourceInfo


# --------------------------------------------------------------------------- #
# Capabilities & Provider Hierarchy
# --------------------------------------------------------------------------- #
def test_provider_capabilities():
    twitch = TwitchProvider()
    assert twitch.name == "twitch"
    assert twitch.display_name == "Twitch"
    assert twitch.has_capability(Capability.RESOLVE)
    assert twitch.has_capability(Capability.SEGMENTS)
    assert twitch.has_capability(Capability.TIMELINE)
    assert twitch.has_capability(Capability.CHAT)
    assert twitch.has_capability(Capability.BROWSE)
    assert twitch.has_capability(Capability.SUBSCRIBE)
    assert Capability.TIMELINE in twitch

    generic = GenericProvider()
    assert generic.name == "generic"
    assert generic.display_name == "Generic"
    assert generic.has_capability(Capability.RESOLVE)
    assert not generic.has_capability(Capability.TIMELINE)
    assert not generic.has_capability(Capability.CHAT)
    assert not generic.has_capability(Capability.SEGMENTS)
    assert not generic.has_capability(Capability.BROWSE)
    assert not generic.has_capability(Capability.SUBSCRIBE)
    assert Capability.RESOLVE in generic
    assert Capability.TIMELINE not in generic

    yt = YouTubeProvider()
    assert yt.name == "youtube"
    assert yt.display_name == "YouTube"
    assert yt.has_capability(Capability.RESOLVE)
    assert yt.has_capability(Capability.PLAYLIST)
    assert yt.has_capability(Capability.BROWSE)
    assert yt.has_capability(Capability.SUBSCRIBE)
    assert not yt.has_capability(Capability.TIMELINE)
    assert not yt.has_capability(Capability.CHAT)


def test_get_browsable_providers():
    browsable = get_browsable_providers()
    names = [p.name for p in browsable]
    assert "twitch" in names
    assert "youtube" in names
    assert "generic" not in names
    for p in browsable:
        assert p.has_capability(Capability.BROWSE)


def test_youtube_entry_parsing():
    entry = {
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "upload_date": "20091025",
        "duration": 212,
        "view_count": 1500000000,
        "thumbnails": [{"url": "https://example.com/small.jpg"}, {"url": "https://example.com/large.jpg"}],
        "uploader": "RickAstleyVEVO",
    }
    parsed = _parse_yt_entry(entry)
    assert parsed["id"] == "dQw4w9WgXcQ"
    assert parsed["title"] == "Never Gonna Give You Up"
    assert parsed["date"] == "2009-10-25"
    assert parsed["duration"] == 212.0
    assert parsed["views"] == 1500000000
    assert parsed["thumb"] == "https://example.com/large.jpg"
    assert parsed["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert parsed["uploader"] == "RickAstleyVEVO"
    assert _format_yt_date("2026-10-01") == "2026-10-01"
    assert _format_yt_date(None) == ""


# --------------------------------------------------------------------------- #
# detect_source: Twitch sources
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected_cleaned",
    [
        ("12345678", "https://www.twitch.tv/videos/12345678"),
        ("  999999  ", "https://www.twitch.tv/videos/999999"),
        ("1", "https://www.twitch.tv/videos/1"),
        ("https://www.twitch.tv/videos/12345678", "https://www.twitch.tv/videos/12345678"),
        ("http://twitch.tv/videos/12345678", "https://www.twitch.tv/videos/12345678"),
        ("twitch.tv/videos/12345678", "https://www.twitch.tv/videos/12345678"),
        ("https://m.twitch.tv/videos/12345678", "https://www.twitch.tv/videos/12345678"),
        ("https://www.twitch.tv/lucky/video/12345678", "https://www.twitch.tv/videos/12345678"),
    ],
)
def test_detect_source_twitch_vods(text, expected_cleaned):
    prov, cleaned = detect_source(text)
    assert isinstance(prov, TwitchProvider)
    assert prov.name == "twitch"
    assert cleaned == expected_cleaned


@pytest.mark.parametrize(
    "text, expected_cleaned",
    [
        ("https://clips.twitch.tv/FrailTameTruffle", "https://clips.twitch.tv/FrailTameTruffle"),
        ("http://clips.twitch.tv/FrailTameTruffle", "https://clips.twitch.tv/FrailTameTruffle"),
        ("clips.twitch.tv/FrailTameTruffle", "https://clips.twitch.tv/FrailTameTruffle"),
        ("https://www.twitch.tv/lucky/clip/FrailTameTruffle", "https://clips.twitch.tv/FrailTameTruffle"),
    ],
)
def test_detect_source_twitch_clips(text, expected_cleaned):
    prov, cleaned = detect_source(text)
    assert isinstance(prov, TwitchProvider)
    assert cleaned == expected_cleaned


@pytest.mark.parametrize(
    "text, expected_cleaned",
    [
        ("https://www.twitch.tv/shroud", "https://www.twitch.tv/shroud"),
        ("https://www.twitch.tv/shroud/", "https://www.twitch.tv/shroud"),
        ("twitch.tv/shroud", "https://www.twitch.tv/shroud"),
        ("shroud", "https://www.twitch.tv/shroud"),
        ("@shroud", "https://www.twitch.tv/shroud"),
        ("ninja_streamer", "https://www.twitch.tv/ninja_streamer"),
    ],
)
def test_detect_source_twitch_channels_and_handles(text, expected_cleaned):
    prov, cleaned = detect_source(text)
    assert isinstance(prov, TwitchProvider)
    assert cleaned == expected_cleaned


def test_detect_source_custom_link_scheme():
    prov, cleaned = detect_source("luckytwitch://open?url=https%3A%2F%2Fwww.twitch.tv%2Fvideos%2F123456")
    assert isinstance(prov, TwitchProvider)
    assert cleaned == "https://www.twitch.tv/videos/123456"

    prov_direct, cleaned_direct = detect_source("luckytwitch://vod/987654")
    assert isinstance(prov_direct, TwitchProvider)
    assert cleaned_direct == "https://www.twitch.tv/videos/987654"


# --------------------------------------------------------------------------- #
# detect_source: Generic sources (YouTube, TikTok, Instagram, Reddit, etc.)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected_prefix",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ"),
        ("youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.tiktok.com/@scout2015/video/6718335390845095173", "https://www.tiktok.com/@scout2015/video/"),
        ("https://vm.tiktok.com/ZM8vXYZ/", "https://vm.tiktok.com/ZM8vXYZ/"),
        ("https://www.instagram.com/reel/Cx012345/", "https://www.instagram.com/reel/Cx012345/"),
        ("https://www.instagram.com/p/Cx012345/", "https://www.instagram.com/p/Cx012345/"),
        ("https://www.reddit.com/r/funny/comments/12345/title/", "https://www.reddit.com/r/funny/comments/"),
        ("https://v.redd.it/abc123xyz", "https://v.redd.it/abc123xyz"),
    ],
)
def test_detect_source_generic_sites(text, expected_prefix):
    prov, cleaned = detect_source(text)
    assert isinstance(prov, GenericProvider)
    assert prov.name == "generic"
    assert cleaned.startswith(expected_prefix)


# --------------------------------------------------------------------------- #
# detect_source: Invalid text
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "\n",
        "this is not a url",
        "https://",
        "http://",
        ":///",
        "ftp://example.com/file",
        "ab",  # too short for handle or domain
        "settings",  # reserved Twitch word
        "videos",  # reserved Twitch word
        "downloads",  # reserved Twitch word
    ],
)
def test_detect_source_invalid_text(text):
    prov, cleaned = detect_source(text)
    assert prov is None
    assert cleaned == ""


# --------------------------------------------------------------------------- #
# SourceInfo capability integration
# --------------------------------------------------------------------------- #
def test_youtube_channel_provider_detection():
    from core.providers import YOUTUBE_PROVIDER
    from core.providers.detect import detect_provider
    assert detect_provider("https://www.youtube.com/@somecreator/videos") is YOUTUBE_PROVIDER
    assert detect_provider("https://youtube.com/channel/UC1234567890") is YOUTUBE_PROVIDER
    assert detect_provider("https://www.youtube.com/c/CustomChannel/videos") is YOUTUBE_PROVIDER
    assert detect_provider("https://www.youtube.com/watch?v=dQw4w9WgXcQ").name == "youtube"
    assert detect_provider("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is not YOUTUBE_PROVIDER


def test_source_info_has_capability():
    twitch_src = SourceInfo(
        url="https://www.twitch.tv/videos/123",
        id="123",
        title="Twitch Stream",
        uploader="Lucky",
        duration=3600.0,
        date="2026-10-01",
        twitch_vod_id="123",
    )
    assert twitch_src.has_capability(Capability.TIMELINE)
    assert twitch_src.has_capability(Capability.CHAT)

    yt_src = SourceInfo(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        id="dQw4w9WgXcQ",
        title="Rick Astley",
        uploader="RickAstleyVEVO",
        duration=212.0,
        date="2009-10-25",
        site="youtube",
    )
    assert yt_src.has_capability(Capability.RESOLVE)
    assert not yt_src.has_capability(Capability.TIMELINE)
    assert not yt_src.has_capability(Capability.CHAT)


def test_run_ytdlp_json_consolidation_and_monkeypatch_hooks(monkeypatch):
    """Verify generic, youtube, and source_info all route through _run_ytdlp_json and honor monkeypatch hooks."""
    import core.source_info as si
    import core.providers.generic as gen
    import core.providers.youtube as yt
    from core.providers.generic import GenericProvider
    from core.providers.youtube import YouTubeProvider

    calls = []

    def fake_si_run(url, **kwargs):
        calls.append(("si", url, kwargs))
        if str(url).startswith("ytsearch"):
            return {"_type": "playlist", "entries": [{"id": "v1", "title": "Vid 1", "duration": 60}]}
        return {
            "id": "v1",
            "title": "Video 1",
            "uploader": "Channel",
            "duration": 60,
            "extractor_key": "Youtube",
            "webpage_url": "https://www.youtube.com/watch?v=v1",
            "formats": [{"format_id": "18", "vcodec": "avc1", "acodec": "mp4a", "height": 360}],
        }

    monkeypatch.setattr(si, "_run_ytdlp_json", fake_si_run)

    # 1. GenericProvider.get_source_info delegates to core.source_info._run_ytdlp_json
    gp = GenericProvider()
    src = gp.get_source_info("https://www.youtube.com/watch?v=v1")
    assert src.id == "v1"
    assert calls[-1][0] == "si"

    # 2. YouTubeProvider._run_ytdlp_json delegates to core.source_info._run_ytdlp_json
    yp = YouTubeProvider()
    videos = yp.search_videos("cats", limit=5)
    assert len(videos) == 1
    assert videos[0]["id"] == "v1"
    assert calls[-1][0] == "si"
    assert calls[-1][2].get("flat_playlist") is True

    # 3. Direct monkeypatch on core.providers.generic._run_ytdlp_json is respected
    monkeypatch.setattr(
        gen,
        "_run_ytdlp_json",
        lambda u: {"id": "gen_patched", "title": "Patched", "duration": 10, "extractor_key": "Generic"},
    )
    src2 = gp.get_source_info("https://example.com/v")
    assert src2.id == "gen_patched"

    # 4. Direct monkeypatch on core.providers.youtube._run_ytdlp_json is respected
    monkeypatch.setattr(
        yt,
        "_run_ytdlp_json",
        lambda target, max_items=None: {"entries": [{"id": "yt_patched", "title": "YT Patched"}]},
    )
    vids2 = yp.search_videos("dogs", limit=3)
    assert vids2[0]["id"] == "yt_patched"


def test_youtube_extractor_args_scoped(monkeypatch):
    """Test that YouTube extractor-args and remote-components are only added for YouTube URLs."""
    import core.download as dl
    import core.source_info as si

    executed_cmds = []

    def fake_subprocess_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        import subprocess
        proc = subprocess.CompletedProcess(cmd, 0, stdout='{"id": "test", "formats": []}', stderr="")
        return proc

    monkeypatch.setattr("luckytwitch_engine.find_tool", lambda name: "mock-ytdlp")
    monkeypatch.setattr("core.source_info.subprocess.run", fake_subprocess_run)

    # 1. Non-YouTube URL in _run_ytdlp_json
    si._run_ytdlp_json("https://www.twitch.tv/videos/12345")
    cmd1 = executed_cmds[-1]
    assert "--remote-components" not in cmd1
    assert "--extractor-args" not in cmd1

    # 2. YouTube URL in _run_ytdlp_json
    si._run_ytdlp_json("https://www.youtube.com/watch?v=12345")
    cmd2 = executed_cmds[-1]
    assert "--remote-components" in cmd2
    # extractor-args no longer hardcoded by default
    assert "--remote-components" in cmd2

    # 3. is_youtube=True flag
    si._run_ytdlp_json("https://custom.site/video", is_youtube=True)
    cmd3 = executed_cmds[-1]
    assert "--remote-components" in cmd3
    assert "--remote-components" in cmd3

    # 4. In core.download.run_ytdlp
    popen_cmds = []

    class MockPopen:
        def __init__(self, cmd, *args, **kwargs):
            popen_cmds.append(cmd)
            import io
            self.stdout = io.StringIO("")
            self.poll = lambda: 0
            self.wait = lambda: 0
            self.returncode = 0

        def communicate(self, *args, **kwargs):
            return ("", "")

    monkeypatch.setattr("core.download.find_tool", lambda name: "mock-ytdlp")
    monkeypatch.setattr("core.download.subprocess.Popen", MockPopen)

    class DummyCtx:
        def check_cancel(self): pass
        def report(self, *args): pass
        def log_progress(self, *args): pass
        def attach_proc(self, *args): pass

    dl.run_ytdlp(DummyCtx(), ["https://vimeo.com/12345"], threads=1)
    assert "--remote-components" not in popen_cmds[-1]

    dl.run_ytdlp(DummyCtx(), ["https://youtu.be/12345"], threads=1)
    assert "--remote-components" in popen_cmds[-1]



def test_youtube_extra_args_default_and_override(monkeypatch):
    from core.source_info import youtube_extra_args
    # Default: only remote-components, no broken extractor-args
    monkeypatch.delenv("LUCKYDOWNLOADER_YTDLP_EXTRA_ARGS", raising=False)
    monkeypatch.setattr("core.settings.load_settings", lambda: {})
    args = youtube_extra_args()
    assert args == ["--remote-components", "ejs:github"]

    # With settings override
    monkeypatch.setattr("core.settings.load_settings", lambda: {"ytdlp_extra_args": "--extractor-args youtube:player_client=android"})
    args_custom = youtube_extra_args()
    assert "--remote-components" in args_custom
    assert "--extractor-args" in args_custom
    assert "youtube:player_client=android" in args_custom

    # With env override
    monkeypatch.setattr("core.settings.load_settings", lambda: {})
    monkeypatch.setenv("LUCKYDOWNLOADER_YTDLP_EXTRA_ARGS", "--limit-rate 5M")
    args_env = youtube_extra_args()
    assert "--limit-rate" in args_env
    assert "5M" in args_env
