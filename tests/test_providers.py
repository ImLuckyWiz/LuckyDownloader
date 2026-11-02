from __future__ import annotations

import pytest

from core.providers import (
    Capability,
    GenericProvider,
    Provider,
    TwitchProvider,
    detect_source,
    is_twitch_source,
    is_web_url,
)
from core.source_info import SourceInfo


# --------------------------------------------------------------------------- #
# Capabilities & Provider Hierarchy
# --------------------------------------------------------------------------- #
def test_provider_capabilities():
    twitch = TwitchProvider()
    assert twitch.name == "twitch"
    assert twitch.has_capability(Capability.RESOLVE)
    assert twitch.has_capability(Capability.SEGMENTS)
    assert twitch.has_capability(Capability.TIMELINE)
    assert twitch.has_capability(Capability.CHAT)
    assert twitch.has_capability(Capability.BROWSE)
    assert twitch.has_capability(Capability.SUBSCRIBE)
    assert Capability.TIMELINE in twitch

    generic = GenericProvider()
    assert generic.name == "generic"
    assert generic.has_capability(Capability.RESOLVE)
    assert not generic.has_capability(Capability.TIMELINE)
    assert not generic.has_capability(Capability.CHAT)
    assert not generic.has_capability(Capability.SEGMENTS)
    assert not generic.has_capability(Capability.BROWSE)
    assert not generic.has_capability(Capability.SUBSCRIBE)
    assert Capability.RESOLVE in generic
    assert Capability.TIMELINE not in generic


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
