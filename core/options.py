"""Turn the settings dictionary into the engine's ``JobOptions`` and ``ClipFilter`` (no Qt, no tkinter).

This is ``App.build_options`` / ``App.build_filter`` / ``App.num`` of the tkinter app (luckytwitch_downloader.py),
copied here because that module imports tkinter. ``tests/test_core_matches_tkinter.py`` runs both on the same
settings and compares the results (the golden test of Phase 5).

``settings`` is the dict from ``core.settings.load_settings()``: numbers are strings (``"60"``), switches are
booleans. Numbers are read tolerantly, like ``App.num``: text that is not a number gives the fallback value.
"""

from __future__ import annotations

from luckytwitch_engine import (
    CHAT_FORMATS, CHAT_RENDER_LOOKS, CHAT_RENDER_MODES, ClipFilter, JobOptions,
)

from core.settings import DEFAULTS

# What the person reads in a drop-down -> the value the engine uses (copied from luckytwitch_downloader.py)
STRATEGIES = {
    "Auto": "auto",
    "Download full VOD, then split": "full",
    "Download only the parts": "sections",
}
QUALITY_CHOICES = {          # what the person reads -> what the engine uses
    "Best available": "best", "1080p": "1080p", "720p": "720p", "480p": "480p",
    "360p": "360p", "160p": "160p", "Audio only": "audio",
}
AUDIO_FORMAT_CHOICES = {"m4a · keep Twitch's audio": "m4a", "mp3 · converted": "mp3"}
CHAT_RENDER_TYPES = {
    "Transparent · Animation (.mov, small)": "transparent",
    "Transparent · ProRes 4444 (.mov, very big)": "prores",
    "Black background · H.264 (.mp4, smallest)": "compact",
}
CHAT_RENDER_LOOK_TYPES = {
    "Outlined text, nothing behind": "outline",
    "Dark see-through panel": "panel",
}
CHAT_RENDER_FPS_NAMES = ["Like the video", "30", "60"]
COOKIES_BROWSER_NAMES = ["None", "Chrome", "Firefox", "Edge", "Brave", "Opera", "Vivaldi", "Safari"]
COOKIES_SCOPE_CHOICES = {
    "Only known platforms (YouTube, TikTok, Instagram, X)": "known_only",
    "All supported sites": "all",
}
COOKIES_SCOPE_NAMES = list(COOKIES_SCOPE_CHOICES)

STRATEGY_NAMES = list(STRATEGIES)
QUALITY_NAMES = list(QUALITY_CHOICES)
AUDIO_FORMAT_NAMES = list(AUDIO_FORMAT_CHOICES)
CHAT_RENDER_TYPE_NAMES = list(CHAT_RENDER_TYPES)
CHAT_RENDER_LOOK_NAMES = list(CHAT_RENDER_LOOK_TYPES)

assert set(CHAT_RENDER_TYPES.values()) == set(CHAT_RENDER_MODES)
assert set(CHAT_RENDER_LOOK_TYPES.values()) == set(CHAT_RENDER_LOOKS)

_TRUE = {"1", "true", "yes", "on", "t", "y"}


def text(settings: dict, name: str) -> str:
    """The setting as the tkinter ``StringVar`` gave it: always a string (a number in the file reads as its text)."""
    value = settings.get(name, DEFAULTS[name])
    return value if isinstance(value, str) else str(value)


def flag(settings: dict, name: str) -> bool:
    """The setting as the tkinter ``BooleanVar`` gave it. A real boolean is the normal case; Tcl-style words
    ("yes", "on", "1") count as true, anything else unreadable as false."""
    value = settings.get(name, DEFAULTS[name])
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return bool(value)


def num(settings: dict, name: str, cast=float, default=0):
    """``App.num``: ``cast(float(text))``; text that is not a number gives ``default`` and never raises."""
    try:
        return cast(float(settings.get(name, DEFAULTS[name])))
    except (ValueError, TypeError, OverflowError):  # tkinter only caught ValueError/TclError; these cannot be typed in a Tk var
        return default


def build_filter(settings: dict) -> ClipFilter:
    return ClipFilter(
        min_views=num(settings, "min_views", int),
        min_duration=num(settings, "min_duration", float),
        top_n=num(settings, "top_n", int),
        pad_before=num(settings, "pad_before", float, 3),
        pad_after=num(settings, "pad_after", float),
        title_template=text(settings, "title_tpl") or DEFAULTS["title_tpl"],
        gap_title=text(settings, "gap_title").strip(),
    )


def build_options(settings: dict, cut_text: str = "", quality: str | None = None) -> JobOptions:
    """``cut_text`` is the text of the Plan tab's cut points box (empty until the Plan tab exists, Phase 6)."""
    s = settings
    chat_format = text(s, "chat_format")
    fps = text(s, "chat_render_fps")
    return JobOptions(
        cut_text=cut_text.strip(),
        out_dir=text(s, "out_dir").strip() or DEFAULTS["out_dir"],
        container=text(s, "container"),
        strategy=STRATEGIES.get(text(s, "strategy"), "auto"),
        full_threshold=min(max(num(s, "threshold", float, 60), 1), 100) / 100,
        exact=flag(s, "exact"),
        keep_full=flag(s, "keep_full"),
        threads=max(1, num(s, "threads", int, 8)),
        name_template=text(s, "name_template").strip() or DEFAULTS["name_template"],
        chapters=flag(s, "chapters"),
        clip_filter=build_filter(s),
        sidecar=flag(s, "sidecar"),
        premiere_xml=flag(s, "premiere_xml"),
        premiere_plugin=flag(s, "premiere_plugin"),
        game_markers=flag(s, "game_markers"),
        muted_markers=flag(s, "muted_markers"),
        chat=flag(s, "chat"),
        chat_format=chat_format if chat_format in CHAT_FORMATS else "json",
        chat_embed=flag(s, "chat_embed"),
        chat_render=flag(s, "chat_render"),
        chat_render_mode=CHAT_RENDER_TYPES.get(text(s, "chat_render_mode"), "transparent"),
        chat_render_look=CHAT_RENDER_LOOK_TYPES.get(text(s, "chat_render_look"), "outline"),
        chat_render_width=num(s, "chat_render_width", int, 400),
        chat_render_height=num(s, "chat_render_height", int, 0),
        chat_render_font_size=num(s, "chat_render_font_size", int, 18),
        chat_render_fps=0 if fps not in ("30", "60") else int(fps),
        chat_render_smooth=flag(s, "chat_render_smooth"),
        subfolders=flag(s, "subfolders"),
        provider_subfolders=flag(s, "provider_subfolders"),
        provider_out_dirs=dict(s.get("provider_out_dirs") or {}) if isinstance(s.get("provider_out_dirs"), dict) else {},
        folder_template=text(s, "folder_template").strip() or DEFAULTS["folder_template"],
        clip_name_template=text(s, "clip_name_template").strip() or DEFAULTS["clip_name_template"],
        generic_name_template=text(s, "generic_name_template").strip() or DEFAULTS.get("generic_name_template", "{uploader} - {date} - {title} [{id}]"),
        clean_title=flag(s, "clean_title") if "clean_title" in s else True,
        quality=quality or QUALITY_CHOICES.get(text(s, "default_quality"), "best"),
        audio_format=AUDIO_FORMAT_CHOICES.get(text(s, "audio_format"), "m4a"),
        cookies_browser="" if text(s, "cookies_from_browser").strip().lower() in ("none", "disabled", "") else text(s, "cookies_from_browser").strip().lower(),
        cookies_scope=COOKIES_SCOPE_CHOICES.get(text(s, "cookies_scope"), text(s, "cookies_scope").strip().lower() if text(s, "cookies_scope").strip().lower() in ("known_only", "all") else "known_only"),
    )
