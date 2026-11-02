"""
Job and JobOptions dataclasses for LuckyTwitch Downloader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.chapters import ClipFilter
from core.source_info import QUALITY_BEST, SourceInfo
if TYPE_CHECKING:
    from core.twitch_api import TwitchClient


@dataclass
class JobOptions:
    cut_text: str
    out_dir: str
    container: str = "mp4"  # mp4 | mkv
    strategy: str = "auto"  # auto | full | sections
    full_threshold: float = 0.6
    exact: bool = False  # re-encode for frame-exact cuts (slow)
    keep_full: bool = False
    threads: int = 8
    name_template: str = "{streamer} - {date} - {id} - part{n}"
    chapters: bool = False
    clip_filter: ClipFilter = field(default_factory=ClipFilter)
    sidecar: bool = False  # write a .clips.json next to each part
    subfolders: bool = True  # out_dir/<streamer>/<stream>/parts
    provider_subfolders: bool = False  # group downloads under out_dir/<Provider>/...
    provider_out_dirs: dict[str, str] = field(default_factory=dict)
    folder_template: str = "{date} - {title} - {id}"  # name of the per-stream folder
    clip_name_template: str = "{clip_title}"  # file name when a single clip is downloaded
    generic_name_template: str = "{uploader} - {date} - {title} [{id}]"  # file name for generic (non-Twitch) downloads
    clean_title: bool = True  # strip bot commands (!links, !gsupps) and promo tags from stream titles
    premiere_xml: bool = False  # also write a Premiere Pro XML (clips as markers) next to each part
    game_markers: bool = False  # also put the game / category changes into that XML as markers ("GAME: ...")
    premiere_plugin: bool = False  # also write a .markers.json for the LuckyTwitch Premiere Pro plugin (colors, details)
    muted_markers: bool = False  # ... and put the stretches Twitch silenced into that .markers.json (kind "muted")
    chat: bool = False  # also download the chat of each part with TwitchDownloaderCLI (Twitch VODs only)
    chat_format: str = "json"  # json | txt | html
    chat_embed: bool = False  # embed emotes / badges in the chat file (bigger, but it renders offline)
    chat_render: bool = False  # also render the chat of each part as an overlay video for the editor (Twitch VODs only)
    chat_render_mode: str = "transparent"  # transparent (Animation .mov) | prores (ProRes 4444 .mov) | compact (H.264 .mp4)
    chat_render_look: str = "outline"  # outline (text with an outline, nothing behind) | panel (dark see-through panel)
    chat_render_width: int = 400  # pixels
    chat_render_height: int = 0  # pixels; 0 = the height of the video part
    chat_render_font_size: int = 18
    chat_render_fps: int = 0  # 0 = like the video (60 if it has 60 fps, else 30)
    chat_render_smooth: bool = False  # redraw on every frame (smooth scrolling, slower) instead of 5 times a second
    quality: str = QUALITY_BEST  # quality to download (Twitch VODs): "best", "720p60", "audio", etc.
    audio_format: str = "m4a"  # audio container when quality is audio-only: "m4a" | "mp3"
    rate_limit: str = ""  # optional bandwidth limit passed to yt-dlp ("--limit-rate"), e.g. "5M", "500K"
    cookies_browser: str = ""  # browser to pass cookies from ("--cookies-from-browser"), e.g. "chrome", "firefox"
    cookies_scope: str = "known_only"  # "known_only" (YouTube, TikTok, Instagram, X) or "all"
    download_archive: str = ""  # optional path to yt-dlp download archive file ("--download-archive")


@dataclass
class Job:
    source: SourceInfo
    opts: JobOptions
    clips: list[dict] | None = None  # pre-fetched clips (otherwise fetched at run time)
    client: TwitchClient | None = None
    single_clip: dict | None = None  # set when the job only downloads this one clip
