"""Settings defaults, load and save (copied from luckytwitch_downloader.py).

The key names and the JSON format stay identical to the tkinter app, so a settings file written by either app
loads in the other (docs/migration/SETTINGS_KEYS.md lists the 38 keys). Numbers are stored as strings, on/off
switches as JSON booleans. There is no variable binding yet: Phase 5 adds the SettingsBinder that edits this dict.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import paths
from luckytwitch_engine import APP_DIR

DEFAULTS = {
    "out_dir": str((Path.home() / "Downloads" / "LuckyTwitch") if paths.FROZEN else (APP_DIR / "downloads")),
    "container": "mp4",
    "strategy": "Auto",
    "threshold": "60",
    "exact": False,
    "keep_full": False,
    "threads": "8",
    "name_template": "{streamer} - {date} - {id} - part{n}",
    "chapters": False,
    "min_views": "0",
    "min_duration": "0",
    "top_n": "0",
    "pad_before": "3",
    "pad_after": "0",
    "title_tpl": "{title} ({creator}, {views} views)",
    "gap_title": "Stream",
    "sidecar": False,
    "premiere_xml": False,
    "premiere_plugin": False,
    "game_markers": False,
    "muted_markers": False,
    "chat": False,
    "chat_format": "json",
    "chat_embed": False,
    "chat_render": False,
    "chat_render_mode": "Transparent · Animation (.mov, small)",
    "chat_render_look": "Outlined text, nothing behind",
    "chat_render_width": "400",
    "chat_render_height": "0",
    "chat_render_font_size": "18",
    "chat_render_fps": "Like the video",
    "chat_render_smooth": False,
    "subfolders": True,
    "provider_subfolders": False,
    "provider_out_dirs": {},
    "clean_title": True,
    "default_quality": "Best available",
    "audio_format": "m4a · keep Twitch's audio",
    "folder_template": "{date} - {title} - {id}",
    "clip_name_template": "{clip_title}",
    "generic_name_template": "{uploader} - {date} - {title} [{id}]",
    "clip_pad_before": "3",
    "clip_pad_after": "3",
    "cookies_from_browser": "None",
    "cookies_scope": "Only known platforms (YouTube, TikTok, Instagram, X)",
    "auto_update": True,
    "check_app_updates": True,
}


def load_settings() -> dict:
    """DEFAULTS overlaid with the saved keys that exist in DEFAULTS. Unknown keys are dropped; a missing or
    broken file (or one that is not a JSON object) gives the defaults."""
    try:
        saved = json.loads(paths.SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save_settings(data: dict) -> None:
    """Write ``data`` as indented JSON; an OSError is ignored, like in the tkinter app."""
    try:
        paths.SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
