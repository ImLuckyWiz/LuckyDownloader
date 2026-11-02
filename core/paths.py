"""Where the app keeps its files (copied from luckytwitch_downloader.py, same names, same locations).

The data folder is shared with the tkinter app: from source it is the app folder, packaged it is the per-user
data folder. For a packaged pre-release (a build version containing a hyphen, such as ``v0.8.0-beta.1``), a separate
sibling folder ``LuckyDownloader-beta`` is used so a beta install never overwrites a stable install's settings or login.
Tests monkeypatch the attributes of THIS module (the other core modules read them at call time).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from core.resources import resource_path
from core.runtime import APP_DIR, legacy_user_data_dir, user_data_dir

PRE_RELEASE_DIR_SUFFIX = "-beta"
APP_USER_MODEL_ID = "LuckyDownloader.Downloader"
PRE_RELEASE_APP_USER_MODEL_ID = "LuckyDownloader.Downloader.Beta"


def read_bundled_version() -> str:
    """Return the version string written into ``version.txt`` by the build script when frozen, or ``""``."""
    try:
        p = resource_path("version.txt")
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        cand = Path(sys.executable).parent / "version.txt"
        if cand.is_file():
            return cand.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def is_prerelease_version(version: str) -> bool:
    """Pre-release tags contain a hyphen (for example ``v0.8.0-beta.1``); stable tags (``v2.0.0``, ``1.0``) do not."""
    return "-" in (version or "").strip()


def resolve_data_dir(frozen: bool = False, version: str = "") -> Path:
    """Return the folder where settings, credentials, recent channels and link files live.

    - From source (``frozen=False``): ``APP_DIR`` (same as the tkinter app).
    - Frozen stable release (no ``-`` in ``version``): ``user_data_dir()`` (upgrading to LuckyDownloader keeps
      the user's Twitch login, saved settings, recent streamers and tools).
    - Frozen pre-release (``-`` in ``version``, e.g. ``v0.8.0-beta.1``): a sibling folder ``LuckyDownloader-beta`` next to
      ``user_data_dir()`` so a beta install never overwrites a stable install's settings or login.
    """
    if not frozen:
        return APP_DIR
    base = user_data_dir()
    if is_prerelease_version(version):
        return base.with_name(base.name + PRE_RELEASE_DIR_SUFFIX)
    return base


def resolve_legacy_data_dir(frozen: bool = False, version: str = "") -> Path | None:
    """Return the legacy folder (LuckyTwitch) if frozen, or None if running from source."""
    if not frozen:
        return None
    base = legacy_user_data_dir()
    if is_prerelease_version(version):
        return base.with_name(base.name + PRE_RELEASE_DIR_SUFFIX)
    return base


def migrate_from_legacy(src: Path | None = None, dest: Path | None = None) -> list[str]:
    """Copy user settings, history, watchlist, recent streamers, UI state, and managed tools from legacy folder.

    Only copies files that do not already exist in dest.
    Never modifies or deletes files in src (preserves for rollback safety).
    Returns list of migrated relative paths.
    """
    if src is None:
        src = resolve_legacy_data_dir(FROZEN, BUNDLED_VERSION)
    if dest is None:
        dest = DATA_DIR
    if src is None or not src.is_dir() or src == dest:
        return []

    migrated: list[str] = []
    files_to_copy = [
        "config.json",
        "luckytwitch_settings.json",
        "luckytwitch_recent.json",
        "luckytwitch_history.json",
        "luckytwitch_watchlist.json",
        "luckytwitch_ui.json",
        "luckytwitch_update.json",
    ]
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []

    for name in files_to_copy:
        src_file = src / name
        dest_file = dest / name
        if src_file.is_file() and not dest_file.exists():
            try:
                shutil.copy2(src_file, dest_file)
                migrated.append(name)
            except OSError:
                pass

    src_tools = src / "tools"
    dest_tools = dest / "tools"
    if src_tools.is_dir():
        try:
            dest_tools.mkdir(parents=True, exist_ok=True)
            for tool_file in src_tools.iterdir():
                if tool_file.is_file():
                    target = dest_tools / tool_file.name
                    if not target.exists():
                        shutil.copy2(tool_file, target)
                        migrated.append(f"tools/{tool_file.name}")
        except OSError:
            pass

    return migrated


def resolve_app_user_model_id(version: str = "") -> str:
    """Return the Windows taskbar AppUserModelID (separate for pre-release builds)."""
    return PRE_RELEASE_APP_USER_MODEL_ID if is_prerelease_version(version) else APP_USER_MODEL_ID


def is_frozen() -> bool:
    """Return True if running inside a compiled / packaged binary (Nuitka, PyInstaller, etc.)."""
    if getattr(sys, "frozen", False):
        return True
    if "__compiled__" in globals() or hasattr(sys.modules.get("__main__"), "__compiled__"):
        return True
    if getattr(sys, "_MEIPASS", None):
        return True
    return False


if is_frozen() and not getattr(sys, "frozen", False):
    sys.frozen = True  # Standardize across packaging backends (e.g. Nuitka)

FROZEN = is_frozen()
BUNDLED_VERSION = read_bundled_version() if FROZEN else ""
DATA_DIR = resolve_data_dir(FROZEN, BUNDLED_VERSION)
CONFIG_PATH = DATA_DIR / "config.json"
SETTINGS_PATH = DATA_DIR / "luckytwitch_settings.json"
RECENT_PATH = DATA_DIR / "luckytwitch_recent.json"
RECENT_SEARCHES_PATH = DATA_DIR / "recent_searches.json"
LINKS_DIR = DATA_DIR / "links"  # links other launches leave for the open window (see weblink.py)
BEAT_PATH = DATA_DIR / "running.beat"  # the open window touches this so a second launch knows it is there
UI_STATE_PATH = DATA_DIR / "luckytwitch_ui.json"
UPDATE_STATE_PATH = DATA_DIR / "luckytwitch_update.json"
HISTORY_PATH = DATA_DIR / "luckytwitch_history.json"
WATCHLIST_PATH = DATA_DIR / "luckytwitch_watchlist.json"
MAX_RECENT = 12


def ensure_data_dir() -> None:
    """Create the data folder and perform legacy data migration if running frozen."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if FROZEN:
        migrate_from_legacy()
