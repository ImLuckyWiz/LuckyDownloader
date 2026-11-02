"""
LuckyDownloader providers package.
"""

from core.providers.base import Capability, Provider
from core.providers.detect import (
    GENERIC_PROVIDER,
    TWITCH_PROVIDER,
    detect_source,
    is_twitch_source,
    is_web_url,
)
from core.providers.generic import GenericProvider, map_generic_error
from core.providers.twitch import TwitchProvider
from core.providers.youtube import YouTubeProvider

YOUTUBE_PROVIDER = YouTubeProvider()
ALL_PROVIDERS: list[Provider] = [TWITCH_PROVIDER, YOUTUBE_PROVIDER, GENERIC_PROVIDER]


def get_browsable_providers() -> list[Provider]:
    """Return all providers capable of browsing/searching (Capability.BROWSE)."""
    return [p for p in ALL_PROVIDERS if p.has_capability(Capability.BROWSE)]


__all__ = [
    "Capability",
    "Provider",
    "TwitchProvider",
    "GenericProvider",
    "YouTubeProvider",
    "map_generic_error",
    "TWITCH_PROVIDER",
    "GENERIC_PROVIDER",
    "YOUTUBE_PROVIDER",
    "ALL_PROVIDERS",
    "get_browsable_providers",
    "detect_source",
    "is_twitch_source",
    "is_web_url",
]
