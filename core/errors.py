"""
Exception hierarchy for LuckyTwitch Downloader.
"""

from __future__ import annotations


class EngineError(Exception):
    """Something went wrong; the message is meant to be shown to the user."""


class PlanError(EngineError):
    """The cut points text is invalid."""


class Cancelled(EngineError):
    """The user cancelled the job."""


class ArchiveSkippedError(EngineError):
    """The video was skipped because it is already recorded in the download archive."""


class DiskSpaceError(EngineError, RuntimeError):
    """Insufficient free disk space for download."""

