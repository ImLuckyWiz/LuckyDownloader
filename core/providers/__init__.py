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

__all__ = [
    "Capability",
    "Provider",
    "TwitchProvider",
    "GenericProvider",
    "map_generic_error",
    "TWITCH_PROVIDER",
    "GENERIC_PROVIDER",
    "detect_source",
    "is_twitch_source",
    "is_web_url",
]
