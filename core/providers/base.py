"""
Base provider interface and capability flags.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Flag, auto
from typing import Any


class Capability(Flag):
    RESOLVE = auto()
    SEGMENTS = auto()
    TIMELINE = auto()
    CHAT = auto()
    BROWSE = auto()
    SUBSCRIBE = auto()
    PLAYLIST = auto()


class Provider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier string, e.g. 'twitch', 'generic'."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> Capability:
        """Capability flags supported by this provider."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable provider name for UI display."""
        return self.name.capitalize()

    def has_capability(self, cap: Capability) -> bool:
        """Return True if the provider supports the given capability flag."""
        return bool(self.capabilities & cap)

    def __contains__(self, cap: Capability) -> bool:
        return self.has_capability(cap)
