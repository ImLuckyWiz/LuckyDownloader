"""
Twitch provider wrapping Twitch VOD lookup, game segments, storyboards, muted ranges, and clips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.providers.base import Capability, Provider

if TYPE_CHECKING:
    from core.source_info import SourceInfo
    from core.twitch_api import TwitchClient


class TwitchProvider(Provider):
    @property
    def name(self) -> str:
        return "twitch"

    @property
    def capabilities(self) -> Capability:
        return (
            Capability.RESOLVE
            | Capability.SEGMENTS
            | Capability.TIMELINE
            | Capability.CHAT
            | Capability.BROWSE
            | Capability.SUBSCRIBE
        )

    def get_source_info(self, text: str) -> SourceInfo:
        from core.source_info import get_source_info
        return get_source_info(text)

    def create_client(self, client_id: str = "", client_secret: str = "") -> TwitchClient:
        from core.twitch_api import TwitchClient
        return TwitchClient(client_id=client_id, client_secret=client_secret)
