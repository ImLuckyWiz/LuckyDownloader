"""Application update discovery, version comparison, asset picking, and integrity verification.

Pure business logic (no Qt dependencies). Communicates with GitHub's releases API and download endpoints.
"""

from __future__ import annotations

from core.i18n import t

import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from core import paths
from core.runtime import USER_AGENT, resolve_dep
from core.tools import _download_file

_ORIG_DOWNLOAD_FILE = _download_file

VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")
GITHUB_RELEASE_API = "https://api.github.com/repos/ImLuckyWiz/LuckyDownloader/releases/latest"
GITHUB_RELEASE_WEB = "https://github.com/ImLuckyWiz/LuckyDownloader/releases/latest"
GITHUB_DOWNLOAD_PREFIX = "https://github.com/ImLuckyWiz/LuckyDownloader/releases/download/"
GITHUB_DOWNLOAD_PREFIXES = (
    "https://github.com/ImLuckyWiz/LuckyDownloader/releases/download/",
    "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/",
)
THROTTLE_HOURS = 24


@dataclass
class UpdateInfo:
    tag: str
    notes: str = ""
    page_url: str = ""
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    sha256: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> UpdateInfo:
        return cls(
            tag=data.get("tag", ""),
            notes=data.get("notes", ""),
            page_url=data.get("page_url", ""),
            asset_name=data.get("asset_name", ""),
            asset_url=data.get("asset_url", ""),
            asset_size=int(data.get("asset_size", 0) or 0),
            sha256=data.get("sha256", ""),
        )


def parse_version(v: str | None) -> tuple[int, int, int, str] | None:
    """Parse a semantic version like 'v2.1.1' or 'v2.0.0-beta.1' into (major, minor, patch, prerelease).
    Returns None if the version does not match standard semver (e.g. '', '1.0', dev build).
    """
    if not v:
        return None
    m = VERSION_RE.match(v.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or ""


def is_valid_app_version(v: str | None) -> bool:
    """Check if version is a valid release version (not empty, '1.0', or dev build)."""
    return parse_version(v) is not None


def is_newer(remote_tag: str, current_version: str) -> bool:
    """Return True if remote_tag represents a strictly newer version than current_version.

    Rules:
    - If current_version is not valid semver (e.g. dev build, '1.0', empty), returns False.
    - If remote_tag is not valid semver, returns False.
    - Stable builds (current_version has no prerelease suffix) ignore prereleases.
    - If (major, minor, patch) numbers differ, higher tuple is newer.
    - If numbers match:
        - A version without prerelease is newer than a prerelease with same numbers (e.g. v2.0.0 > v2.0.0-beta.1).
        - If both have prerelease, compare prerelease strings lexicographically (e.g. beta.2 > beta.1).
    """
    curr = parse_version(current_version)
    rem = parse_version(remote_tag)
    if not curr or not rem:
        return False

    curr_nums, curr_pre = curr[:3], curr[3]
    rem_nums, rem_pre = rem[:3], rem[3]

    # Stable builds ignore pre-releases
    if not curr_pre and rem_pre:
        return False

    if rem_nums != curr_nums:
        return rem_nums > curr_nums

    # Numbers match:
    # Final release is newer than a pre-release of the same version
    if not rem_pre and curr_pre:
        return True
    if rem_pre and not curr_pre:
        return False
    if rem_pre and curr_pre:
        return rem_pre > curr_pre

    return False


def pick_asset(release: dict, sys_platform: str | None = None, machine: str | None = None) -> dict | None:
    """Select the appropriate download asset from a GitHub release payload for the current platform.
    Returns the asset dict or None if no matching asset found.
    """
    sys_plat = sys_platform if sys_platform is not None else sys.platform
    mach = (machine if machine is not None else platform.machine()).lower()

    assets = release.get("assets", [])
    if not isinstance(assets, list):
        return None

    if sys_plat.startswith("win"):
        for a in assets:
            name = a.get("name", "")
            if name.startswith(("LuckyTwitch-Setup", "LuckyDownloader-Setup")) and name.endswith(".exe"):
                return a
    elif sys_plat == "darwin":
        is_arm = mach in ("arm64", "aarch64")
        target_token = "arm64" if is_arm else "x86_64"
        for a in assets:
            name = a.get("name", "")
            if name.startswith(("LuckyTwitch-", "LuckyDownloader-")) and name.endswith(".dmg") and target_token in name:
                return a
        for a in assets:
            if name.startswith(("LuckyTwitch-", "LuckyDownloader-")) and name.endswith(".dmg"):
                return a
    elif sys_plat.startswith("linux"):
        for a in assets:
            name = a.get("name", "")
            if name.startswith(("LuckyTwitch-", "LuckyDownloader-")) and name.endswith(".AppImage") and "x86_64" in name:
                return a
        for a in assets:
            if name.startswith(("LuckyTwitch-", "LuckyDownloader-")) and name.endswith(".AppImage"):
                return a
        for a in assets:
            name = a.get("name", "")
            if name.startswith(("LuckyTwitch-", "LuckyDownloader-")) and name.endswith(".tar.gz") and "linux" in name:
                return a

    return None


def is_safe_asset_url(url: str) -> bool:
    """Ensure asset download URL starts with the official release download prefix."""
    return bool(url and any(url.startswith(p) for p in GITHUB_DOWNLOAD_PREFIXES))


def verify_download(file_path: Path, expected_size: int, expected_sha256: str) -> bool:
    """Verify downloaded file size and SHA-256 integrity.
    Requires expected_sha256 to be a non-empty 64-character hex string.
    """
    if not expected_sha256 or len(expected_sha256.strip()) != 64:
        return False
    if not file_path.is_file():
        return False
    if expected_size > 0 and file_path.stat().st_size != expected_size:
        return False

    h = hashlib.sha256()
    try:
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
    except OSError:
        return False
    return h.hexdigest().lower() == expected_sha256.strip().lower()


def extract_sha256_from_sums(sums_text: str, asset_name: str) -> str:
    """Parse SHA256SUMS.txt content for the line corresponding to asset_name."""
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            h, name = parts[0], parts[-1].lstrip("*")
            if name == asset_name and len(h) == 64:
                return h.lower()
    return ""


def fetch_latest(session: requests.Session | None = None,
                 sys_platform: str | None = None,
                 machine: str | None = None) -> UpdateInfo | None:
    """Fetch information about the latest stable release.
    Attempts the GitHub API first (8s timeout). If rate limited (403/429),
    falls back to resolving the redirect location of the releases/latest web URL.
    Returns UpdateInfo or None on error.
    """
    s = session or requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}

    # 1. Try GitHub API
    try:
        resp = s.get(GITHUB_RELEASE_API, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("tag_name", "")
            if not tag:
                return None
            notes = data.get("body", "") or ""
            page_url = data.get("html_url", "") or f"https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/{tag}"

            asset = pick_asset(data, sys_platform=sys_platform, machine=machine)
            asset_name = asset.get("name", "") if asset else ""
            asset_url = asset.get("browser_download_url", "") if asset else ""
            asset_size = asset.get("size", 0) if asset else 0

            sha256 = ""
            if asset:
                digest = asset.get("digest", "")
                if digest and digest.startswith("sha256:"):
                    sha256 = digest.split(":", 1)[1].strip().lower()

            if not sha256 and asset_name:
                for a in data.get("assets", []):
                    if a.get("name") == "SHA256SUMS.txt" and a.get("browser_download_url"):
                        try:
                            sums_resp = s.get(a["browser_download_url"], headers={"User-Agent": USER_AGENT}, timeout=5)
                            if sums_resp.status_code == 200:
                                sha256 = extract_sha256_from_sums(sums_resp.text, asset_name)
                        except Exception:
                            pass
                        break

            return UpdateInfo(
                tag=tag,
                notes=notes,
                page_url=page_url,
                asset_name=asset_name,
                asset_url=asset_url,
                asset_size=asset_size,
                sha256=sha256,
            )
    except Exception:
        pass

    # 2. Redirect fallback on releases/latest web URL (useful when API is rate-limited)
    try:
        r = s.get(GITHUB_RELEASE_WEB, headers={"User-Agent": USER_AGENT}, timeout=8, allow_redirects=False)
        loc = r.headers.get("Location", "")
        if "/releases/tag/" in loc:
            tag = loc.rsplit("/tag/", 1)[-1].strip()
            if tag:
                return UpdateInfo(
                    tag=tag,
                    notes="",
                    page_url=loc,
                )
    except Exception:
        pass

    return None


def should_check(state: dict, now: datetime | None = None) -> bool:
    """Return True if at least 24 hours have passed since the last check (or if never checked)."""
    last_check_str = state.get("last_check")
    if not last_check_str:
        return True
    try:
        current_time = now or datetime.now(timezone.utc)
        clean_str = last_check_str.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(clean_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        # Clock turned back check
        if last_dt > current_time:
            return True
        diff = (current_time - last_dt).total_seconds()
        return diff >= THROTTLE_HOURS * 3600
    except (ValueError, TypeError):
        return True


def load_state() -> dict:
    """Load update state from UPDATE_STATE_PATH."""
    try:
        text = paths.UPDATE_STATE_PATH.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "last_check": "",
        "latest_tag": "",
        "notified_tag": "",
        "skipped_tag": "",
        "cached": {},
        "installer_path": "",
    }


def save_state(state: dict) -> None:
    """Save update state to UPDATE_STATE_PATH."""
    try:
        from core.files import atomic_write_json
        atomic_write_json(paths.UPDATE_STATE_PATH, state)
    except OSError:
        pass


def download_installer(ctx, info: UpdateInfo, dest: Path) -> Path:
    """Download the installer asset to dest using the engine's download helper.
    Validates destination URL against allow-list before downloading.
    """
    if not is_safe_asset_url(info.asset_url):
        raise ValueError(t("Asset URL is not on the GitHub releases allow-list: {url}").format(url=info.asset_url))
    dl_fn = resolve_dep("_download_file", _ORIG_DOWNLOAD_FILE, _download_file)
    dl_fn(ctx, info.asset_url, dest)
    return dest


def is_installed_setup() -> bool:
    """Return True if running on Windows and installed via Inno Setup (unins000.exe present)."""
    if sys.platform != "win32":
        return False
    exe_dir = Path(sys.executable).parent
    return (exe_dir / "unins000.exe").is_file()


def get_update_temp_dir() -> Path:
    """Return the folder used for staging installer downloads (inside DATA_DIR/updates)."""
    dest = paths.DATA_DIR / "updates"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def cleanup_stale_installer() -> None:
    """Delete any leftover installer or installer folder from a previous update."""
    state = load_state()
    path_str = state.get("installer_path")
    if not path_str:
        return
    try:
        p = Path(path_str)
        if p.is_file():
            p.unlink(missing_ok=True)
        if p.parent.name in ("LuckyTwitch-update", "updates") and p.parent.is_dir():
            # If inside updates directory, delete the installer file (do not wipe whole updates dir)
            if p.parent.name == "LuckyTwitch-update":
                shutil.rmtree(p.parent, ignore_errors=True)
    except OSError:
        pass
    state["installer_path"] = ""
    save_state(state)


def launch_installer(installer_path: Path | str, expected_sha256: str = "", expected_size: int = 0) -> bool:
    """Launch the Windows installer detached with silent and relaunch parameters.
    Optionally re-verifies expected_sha256 if provided before executing.
    Returns True if the process was launched, False if OSError was raised or verification failed.
    """
    if expected_sha256:
        if not verify_download(Path(installer_path), expected_size, expected_sha256):
            return False
    cmd = [
        str(installer_path),
        "/SILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/RELAUNCH=1",
    ]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    try:
        subprocess.Popen(
            cmd,
            creationflags=creationflags,
            close_fds=(sys.platform != "win32"),
        )
        return True
    except OSError:
        return False
