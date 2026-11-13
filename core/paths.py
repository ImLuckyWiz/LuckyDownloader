"""Where the app keeps its files (copied from luckytwitch_downloader.py, same names, same locations).

The data folder is shared with the tkinter app: from source it is the app folder, packaged it is the per-user
data folder. For a packaged pre-release (a build version containing a hyphen, such as ``v0.8.0-beta.1``), a separate
sibling folder ``LuckyDownloader-beta`` is used so a beta install never overwrites a stable install's settings or login.
Tests monkeypatch the attributes of THIS module (the other core modules read them at call time).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
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

    sentinel = dest / ".migrated_from_luckytwitch"
    if sentinel.exists():
        return []

    migrated: list[str] = []
    files_to_copy = [
        "config.json",
        "luckytwitch_settings.json",
        "luckytwitch_recent.json",
        "recent_searches.json",
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
                if name == "config.json" and os.name == "posix":
                    os.chmod(dest_file, 0o600)
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

    try:
        dest.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("1", encoding="utf-8")
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
FAVORITES_PATH = DATA_DIR / "luckytwitch_favorites.json"
RECENT_SEARCHES_PATH = DATA_DIR / "recent_searches.json"
LINKS_DIR = DATA_DIR / "links"  # links other launches leave for the open window (see weblink.py)
BEAT_PATH = DATA_DIR / "running.beat"  # the open window touches this so a second launch knows it is there
UI_STATE_PATH = DATA_DIR / "luckytwitch_ui.json"
UPDATE_STATE_PATH = DATA_DIR / "luckytwitch_update.json"
HISTORY_PATH = DATA_DIR / "luckytwitch_history.json"
WATCHLIST_PATH = DATA_DIR / "luckytwitch_watchlist.json"
QUEUE_STATE_PATH = DATA_DIR / "queue_state.json"
QUEUE_STATE_FILE = QUEUE_STATE_PATH
MAX_RECENT = 12


def _extract_uninstaller_exe(cmd: str) -> Path | None:
    """Extract the executable path from an Inno Setup UninstallString command."""
    if not cmd:
        return None
    s = cmd.strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        exe = s[1:end] if end != -1 else s.strip('"')
    else:
        m = re.match(r"^(.+?\.exe)\b", s, re.IGNORECASE)
        if m:
            exe = m.group(1).strip()
        else:
            parts = s.split(maxsplit=1)
            exe = parts[0] if parts else ""
    if exe:
        try:
            p = Path(exe)
            if p.is_file():
                return p
        except (ValueError, OSError):
            pass
    return None


def find_legacy_uninstaller(current_exe_dir: Path | None = None) -> Path | None:
    """Find the uninstaller executable for LuckyTwitch on Windows, if installed."""
    if sys.platform != "win32":
        return None

    if current_exe_dir is None:
        try:
            current_exe_dir = Path(sys.executable).resolve().parent
        except (ValueError, OSError):
            current_exe_dir = None

    # 1. Check registry (HKCU and HKLM)
    try:
        import winreg

        subkeys = [
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E2B6B0C-3F0D-4C57-9B6A-1A7C2E0D4F11}_is1",
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{9C4A8D2E-7B1F-4E63-8A5D-3F2E1C9B7D44}_is1",
        ]
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            # Known GUIDs
            for subkey in subkeys:
                try:
                    with winreg.OpenKey(root, subkey) as k:
                        disp_name = ""
                        try:
                            disp_name, _ = winreg.QueryValueEx(k, "DisplayName")
                        except OSError:
                            pass
                        loc = ""
                        try:
                            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                        except OSError:
                            pass
                        if "luckydownloader" in str(disp_name).lower() or "luckydownloader" in str(loc).lower():
                            continue
                        for val_name in ("QuietUninstallString", "UninstallString"):
                            try:
                                cmd, _ = winreg.QueryValueEx(k, val_name)
                                p = _extract_uninstaller_exe(str(cmd))
                                if p and (current_exe_dir is None or p.resolve().parent != current_exe_dir):
                                    return p
                            except OSError:
                                pass
                except OSError:
                    pass

            pass
    except Exception:
        pass

    # 2. Check standard install folders
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        for cand_dir in (
            Path(localappdata) / "Programs" / "LuckyTwitch",
            Path(localappdata) / "Programs" / "LuckyTwitch-Beta",
        ):
            uninst = cand_dir / "unins000.exe"
            if uninst.is_file():
                if current_exe_dir is None or uninst.resolve().parent != current_exe_dir:
                    return uninst

    return None


def cleanup_legacy_shortcuts() -> list[str]:
    """Remove leftover LuckyTwitch desktop and Start Menu shortcuts, returning list of removed paths."""
    removed: list[str] = []
    if sys.platform == "win32":
        candidates = []
        user_desktop = Path.home() / "Desktop"
        candidates.extend([
            user_desktop / "LuckyTwitch.lnk",
            user_desktop / "LuckyTwitch (Beta).lnk",
        ])
        appdata = os.environ.get("APPDATA")
        if appdata:
            programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            candidates.extend([
                programs / "LuckyTwitch.lnk",
                programs / "LuckyTwitch (Beta).lnk",
                programs / "LuckyTwitch" / "LuckyTwitch.lnk",
                programs / "LuckyTwitch" / "Uninstall LuckyTwitch.lnk",
            ])
            folder = programs / "LuckyTwitch"
            if folder.is_dir():
                try:
                    for f in folder.iterdir():
                        f.unlink(missing_ok=True)
                    folder.rmdir()
                    removed.append(str(folder))
                except OSError:
                    pass
        for p in candidates:
            try:
                if p.is_file():
                    p.unlink(missing_ok=True)
                    removed.append(str(p))
            except OSError:
                pass
    elif sys.platform == "darwin":
        pass
    elif sys.platform.startswith("linux"):
        desktop = Path.home() / ".local" / "share" / "applications" / "luckytwitch.desktop"
        if desktop.is_file():
            try:
                desktop.unlink(missing_ok=True)
                removed.append(str(desktop))
            except OSError:
                pass
    return removed


def uninstall_legacy_app(uninst_path: Path | None = None, wait: bool = False) -> bool:
    """Trigger silent uninstallation of legacy LuckyTwitch if detected, and remove legacy shortcuts.

    Returns True if an uninstaller was triggered, False otherwise.
    """
    if uninst_path is None:
        uninst_path = find_legacy_uninstaller()

    triggered = False
    if uninst_path and uninst_path.is_file():
        cmd = [str(uninst_path), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        try:
            proc = subprocess.Popen(
                cmd,
                creationflags=creationflags,
                close_fds=(sys.platform != "win32"),
            )
            triggered = True
            if wait:
                try:
                    proc.wait(timeout=30)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        except OSError:
            pass

    cleanup_legacy_shortcuts()
    return triggered


def ensure_data_dir() -> None:
    """Create the data folder, perform legacy data migration, and auto-uninstall legacy app if running frozen."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if FROZEN:
        migrate_from_legacy()
        uninst_sentinel = DATA_DIR / ".legacy_uninstalled"
        if not uninst_sentinel.exists():
            uninstall_legacy_app()
            try:
                uninst_sentinel.write_text("1\n", encoding="utf-8")
            except OSError:
                pass
