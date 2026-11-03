"""
Tool management: download, update, and verify yt-dlp, ffmpeg, and TwitchDownloaderCLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path, PurePosixPath

import requests

from core.errors import Cancelled, EngineError
from core.i18n import t
from core.runtime import (
    EXE,
    TOOLS_DIR,
    USER_AGENT,
    _NO_WINDOW,
    _tool_env,
    find_tool,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime import Ctx

YTDLP_RELEASES = "https://github.com/yt-dlp/yt-dlp/releases"
FFMPEG_BUILDS = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest"
TDCLI_REPO = "lay295/TwitchDownloader"
TDCLI_VERSION = "1.56.5"
_TDCLI_EXE = "TwitchDownloaderCLI" + EXE


def _is_managed(path: str | Path) -> bool:
    try:
        return Path(path).resolve().parent == TOOLS_DIR.resolve()
    except OSError:
        return False


def _read_versions() -> dict:
    try:
        return json.loads((TOOLS_DIR / "versions.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_version(name: str, value: str) -> None:
    data = _read_versions()
    data[name] = value
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    (TOOLS_DIR / "versions.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _run_version(path: str, flag: str) -> str:
    try:
        out = subprocess.run(
            [path, flag],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=_tool_env(),
            creationflags=_NO_WINDOW,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "?"
    first = (out.strip().splitlines() or ["?"])[0].strip()
    m = re.match(r"ffmpeg version (\S+)", first)
    return m.group(1) if m else first


def installed_ytdlp_version() -> str | None:
    path = find_tool("yt-dlp")
    if not path:
        return None
    return (_read_versions().get("yt-dlp") if _is_managed(path) else None) or _run_version(path, "--version")


def describe_tools() -> str:
    """Human-readable status of both tools (runs them, so call it from a worker thread)."""
    lines = []
    for name, flag in (("yt-dlp", "--version"), ("ffmpeg", "-version")):
        path = find_tool(name)
        if not path:
            lines.append(f"{name}: not installed")
            continue
        where = "managed by LuckyTwitch" if _is_managed(path) else path
        lines.append(f"{name} {_run_version(path, flag)}  ({where})")
    tdcli = find_tdcli()
    if not tdcli:
        lines.append("TwitchDownloaderCLI: not installed (downloaded the first time chat is used)")
    elif _is_managed_tdcli(tdcli):
        lines.append(f"TwitchDownloaderCLI {_read_versions().get('tdcli', '?')}  (managed by LuckyTwitch)")
    else:
        lines.append(f"TwitchDownloaderCLI {_run_version(tdcli, '--version')}  ({tdcli})")
    return "\n".join(lines)


def _http_get(url: str, **kw) -> requests.Response:
    return requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT}, **kw)


def _download_file(ctx: "Ctx", url: str, dest: Path) -> None:
    ctx.check_cancel()
    dest.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    try:
        with _http_get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    ctx.check_cancel()
                    f.write(chunk)
                    done += len(chunk)
                    speed = done / max(time.monotonic() - t0, 0.001) / 1048576
                    size = f"{done / 1048576:.0f}" + (f"/{total / 1048576:.0f}" if total else "") + " MiB"
                    ctx.report(done / total if total else None, f"{size} · {speed:.1f} MiB/s")
    except requests.RequestException as e:
        raise EngineError(t("Network error while downloading {file}:\n{error}").format(file=url.rsplit("/", 1)[-1], error=e)) from e


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _verify_checksum(path: Path, sums_url: str, filename: str) -> None:
    """Check the download against the checksum list published next to it on GitHub."""
    try:
        r = _http_get(sums_url)
        r.raise_for_status()
    except requests.RequestException as e:
        raise EngineError(t("Could not fetch the checksums to verify {filename}:\n{error}").format(filename=filename, error=e)) from e
    expected = None
    for line in r.text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and Path(parts[-1].lstrip("*")).name == filename:
            expected = parts[0].lower()
            break
    if not expected:
        raise EngineError(t("No checksum is published for {filename}.").format(filename=filename))
    if _sha256(path) != expected:
        raise EngineError(t("Checksum mismatch for {filename}: the download is corrupted, try again.").format(filename=filename))


def _ytdlp_asset() -> str:
    if sys.platform == "win32":
        return "yt-dlp.exe" if sys.maxsize > 2**32 else "yt-dlp_x86.exe"
    if sys.platform == "darwin":
        return "yt-dlp_macos"  # universal2 (Intel + Apple Silicon)
    return "yt-dlp_linux_aarch64" if platform.machine().lower() in ("aarch64", "arm64") else "yt-dlp_linux"


def latest_ytdlp_tag() -> str:
    """Latest release tag, read from the redirect of /releases/latest/download (no API rate limit)."""
    try:
        r = _http_get(f"{YTDLP_RELEASES}/latest/download/SHA2-256SUMS", allow_redirects=False, stream=True)
        try:
            location = r.headers.get("Location", "")
        finally:
            r.close()
    except requests.RequestException as e:
        raise EngineError(t("Could not reach GitHub to check yt-dlp:\n{error}").format(error=e)) from e
    m = re.search(r"/download/([^/]+)/", location)
    if not m:
        raise EngineError(t("Could not find the latest yt-dlp release on GitHub."))
    return m.group(1)


def install_ytdlp(ctx: "Ctx", tag: str | None = None) -> str:
    """Download the standalone yt-dlp binary from GitHub into the tools folder."""
    tag = tag or latest_ytdlp_tag()
    asset = _ytdlp_asset()
    base = f"{YTDLP_RELEASES}/download/{tag}"
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TOOLS_DIR / "yt-dlp.download"
    ctx.log(t("Downloading yt-dlp {tag}…").format(tag=tag))
    ctx.stage(0.0, 1.0, f"Downloading yt-dlp {tag}")
    try:
        _download_file(ctx, f"{base}/{asset}", tmp)
        _verify_checksum(tmp, f"{base}/SHA2-256SUMS", asset)
        tmp.chmod(0o755)
        try:
            os.replace(tmp, TOOLS_DIR / ("yt-dlp" + EXE))
        except PermissionError as e:
            raise EngineError(t("yt-dlp is in use right now. Wait for running jobs to finish and try again.")) from e
    finally:
        tmp.unlink(missing_ok=True)
    _write_version("yt-dlp", tag)
    ctx.log(t("yt-dlp {tag} installed.").format(tag=tag))
    return tag


_FFMPEG_NAMES = {"ffmpeg", "ffprobe"}


def _wanted_member(path: str) -> str | None:
    """File name to extract for a member of an ffmpeg archive (only bin/ffmpeg, bin/ffprobe, bin/*.dll)."""
    p = PurePosixPath(path.replace("\\", "/"))
    if p.parent.name != "bin":
        return None
    stem = p.name[:-4] if p.name.lower().endswith(".exe") else p.name
    if stem in _FFMPEG_NAMES or p.name.lower().endswith(".dll"):
        return p.name
    return None


def _write_member(src, name: str) -> None:
    tmp = TOOLS_DIR / (name + ".tmp")
    with open(tmp, "wb") as out:
        shutil.copyfileobj(src, out)
    tmp.chmod(0o755)
    os.replace(tmp, TOOLS_DIR / name)


def _extract_ffmpeg(archive: Path) -> None:
    found = set()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = None if info.is_dir() else _wanted_member(info.filename)
                if name:
                    with z.open(info) as src:
                        _write_member(src, name)
                    found.add(name)
    else:
        with tarfile.open(archive, "r:*") as tf:
            for m in tf:
                name = _wanted_member(m.name) if m.isfile() else None
                if name:
                    src = tf.extractfile(m)
                    if src is not None:
                        with src:
                            _write_member(src, name)
                        found.add(name)
    if "ffmpeg" + EXE not in found:
        raise EngineError(t("The ffmpeg archive did not contain ffmpeg."))


_MAC_FFMPEG_SHA256: dict[str, str] = {
    "https://ffmpeg.martin-riedl.de/download/macos/arm64/1793460248_N-128220-gbea9d176f7/ffmpeg.zip": (
        "8094d88c459b6e0ab3bd69e96729485b50cb859451ba92c3779818d38d4b656d"
    ),
    "https://ffmpeg.martin-riedl.de/download/macos/arm64/1793460248_N-128220-gbea9d176f7/ffprobe.zip": (
        "4587e2f13de2fa368067ad903def39306ba697cc07c1bb27da5753161628ce76"
    ),
    "https://ffmpeg.martin-riedl.de/download/macos/amd64/1767299902_N-122320-g38e89fe502/ffmpeg.zip": (
        "6f0736d424b7426f8cbb7bba5c5448d94c976c138c669593b1f40ba534ed192f"
    ),
    "https://ffmpeg.martin-riedl.de/download/macos/amd64/1767299902_N-122320-g38e89fe502/ffprobe.zip": (
        "46852ce00ae6f722ed30be269f310ea96c106a4246f2905d3147c5e02293081c"
    ),
    "https://www.osxexperts.net/ffmpeg80arm.zip": (
        "0d4efcaf6a098430a708e0af694a84792938921fa126162787ae98c6151d7a95"
    ),
    "https://www.osxexperts.net/ffprobe80arm.zip": (
        "b46eb342707ec0d31d3e8337bb56831e59c9e20918f414fd7a9d65a32fcb348f"
    ),
    "https://www.osxexperts.net/ffmpeg80intel.zip": (
        "2d24d22db78c87f394a5822867acd5c5dc5e762cd261a44bd26923f3a5af3e07"
    ),
    "https://www.osxexperts.net/ffprobe80intel.zip": (
        "0b6576104a95c1b39d4939e2df86f8f7cf1d55287ff57da48777d94605d12feb"
    ),
    "https://evermeet.cx/ffmpeg/ffmpeg-9.0.2.zip": (
        "4acc0be580f9b2788029eb7bd4d645ff87968911b0a62aeeb3940d42d54558d5"
    ),
    "https://evermeet.cx/ffmpeg/ffprobe-9.0.2.zip": (
        "24a9c968cd4da72d99c7245e914b921815835eb6dff01d99868031aebaf1d439"
    ),
}


def _mac_ffmpeg_sources(tool: str) -> list[tuple[str, str]]:
    """(label, url) candidates for a macOS static build, native architecture first."""
    arm = platform.machine().lower() in ("arm64", "aarch64")
    riedl_ver = "arm64/1793460248_N-128220-gbea9d176f7" if arm else "amd64/1767299902_N-122320-g38e89fe502"
    riedl = f"https://ffmpeg.martin-riedl.de/download/macos/{riedl_ver}/{tool}.zip"
    osx = f"https://www.osxexperts.net/{tool}80{'arm' if arm else 'intel'}.zip"
    ever = f"https://evermeet.cx/ffmpeg/{tool}-9.0.2.zip"
    return [("martin-riedl.de", riedl), ("osxexperts.net", osx), ("evermeet.cx", ever)]


def _verify_mac_ffmpeg_archive(archive: Path, url: str, tool: str) -> None:
    """Verify a downloaded macOS ffmpeg/ffprobe archive against its pinned SHA-256 digest."""
    filename = f"{tool}.zip"
    expected = _MAC_FFMPEG_SHA256.get(url, "").strip().lower()
    if not expected:
        raise EngineError(t("No checksum is published for {filename}.").format(filename=filename))
    if _sha256(archive).lower() != expected:
        raise EngineError(t("Checksum mismatch for {filename}: the download is corrupted, try again.").format(filename=filename))


def _download_with_retry(ctx: "Ctx", url: str, dest: Path, attempts: int = 3) -> None:
    """_download_file, but waits and retries when the server says 429 / 5xx."""
    for n in range(1, attempts + 1):
        try:
            _download_file(ctx, url, dest)
            return
        except EngineError as e:
            if isinstance(e, Cancelled) or n == attempts or not re.search(r"\b(429|50[0-4])\b", str(e)):
                raise
            wait = 5 * n
            ctx.log(t("Server busy ({host}), retrying in {wait}s…").format(host=url.split("/")[2], wait=wait))
            for _ in range(wait):
                ctx.check_cancel()
                time.sleep(1)


def _install_ffmpeg_macos(ctx: "Ctx") -> None:
    """Static builds, trying several hosts so one rate-limiting us (HTTP 429) is not fatal."""
    errors: list[str] = []
    for label in [s[0] for s in _mac_ffmpeg_sources("ffmpeg")]:
        try:
            for i, tool in enumerate(("ffmpeg", "ffprobe")):
                url = dict(_mac_ffmpeg_sources(tool))[label]
                archive = TOOLS_DIR / f"{tool}.zip.download"
                ctx.stage(i / 2, (i + 1) / 2, f"Downloading {tool}")
                try:
                    _download_with_retry(ctx, url, archive)
                    _verify_mac_ffmpeg_archive(archive, url, tool)
                    with zipfile.ZipFile(archive) as z:
                        member = next((n for n in z.namelist()
                                       if PurePosixPath(n).name == tool and not n.startswith("__MACOSX")), None)
                        if member is None:
                            raise EngineError(t("The {tool} download did not contain {tool}.").format(tool=tool))
                        with z.open(member) as src:
                            _write_member(src, tool)
                finally:
                    archive.unlink(missing_ok=True)
            return
        except (EngineError, zipfile.BadZipFile) as e:
            if isinstance(e, Cancelled):
                raise
            errors.append(f"{label}: {str(e).splitlines()[0]}")
            ctx.log(t("ffmpeg from {label} failed, trying the next source…").format(label=label))
    raise EngineError("Could not download ffmpeg automatically:\n  " + "\n  ".join(errors) +
                      "\n\nWait a few minutes and try again, or install it with Homebrew:  brew install ffmpeg"
                      f"\n(or copy ffmpeg and ffprobe into {TOOLS_DIR})")


def install_ffmpeg(ctx: "Ctx") -> None:
    """Download a static ffmpeg + ffprobe build into the tools folder (one-time)."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    ctx.log(t("Downloading ffmpeg (one-time download, it can be large)…"))
    if sys.platform == "darwin":
        _install_ffmpeg_macos(ctx)
        _write_version("ffmpeg", "macos-static")
        ctx.log(t("ffmpeg installed."))
        return
    arm = platform.machine().lower() in ("aarch64", "arm64")
    if sys.platform == "win32":
        asset = "ffmpeg-master-latest-win64-gpl-shared.zip"  # "shared" = same tools, much smaller download
    else:
        asset = "ffmpeg-master-latest-linuxarm64-gpl.tar.xz" if arm else "ffmpeg-master-latest-linux64-gpl.tar.xz"
    archive = TOOLS_DIR / (asset + ".download")
    try:
        ctx.stage(0.0, 0.9, "Downloading ffmpeg")
        _download_file(ctx, f"{FFMPEG_BUILDS}/{asset}", archive)
        ctx.stage(0.9, 1.0, "Verifying ffmpeg")
        ctx.report(None)
        _verify_checksum(archive, f"{FFMPEG_BUILDS}/checksums.sha256", asset)
        ctx.stage(0.95, 1.0, "Extracting ffmpeg")
        ctx.report(None)
        _extract_ffmpeg(archive)
    finally:
        archive.unlink(missing_ok=True)
    _write_version("ffmpeg", asset)
    ctx.log(t("ffmpeg installed."))


def ensure_tools(ctx: "Ctx", update_ytdlp: bool = True, force: bool = False) -> None:
    """
    Make sure ffmpeg and yt-dlp exist (download them if not) and keep our own copy
    of yt-dlp up to date. Missing tools raise EngineError; a failed update check
    is only logged. `force` = reinstall the latest yt-dlp even if it looks current.
    """
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        install_ffmpeg(ctx)
    else:
        where = "managed by LuckyTwitch" if _is_managed(ffmpeg) else ffmpeg
        ctx.log(t("ffmpeg is installed ({version}, {where}).").format(version=_run_version(ffmpeg, "-version"), where=where))
    if not find_tool("ffprobe"):
        ctx.log(t("Warning: ffprobe was not found next to ffmpeg; some features may fail."))

    ytdlp = find_tool("yt-dlp")
    if not ytdlp or (force and not _is_managed(ytdlp)):
        install_ytdlp(ctx)
        return
    if not update_ytdlp and not force:
        return
    if not _is_managed(ytdlp):
        ctx.log(t("Using the yt-dlp found at {path} (update it yourself if downloads break).").format(path=ytdlp))
        return
    try:
        latest = latest_ytdlp_tag()
        current = installed_ytdlp_version()
        if force or current != latest:
            install_ytdlp(ctx, latest)
        else:
            ctx.log(t("yt-dlp is up to date ({version}).").format(version=current))
    except Cancelled:
        raise
    except EngineError as e:
        ctx.log(t("Could not update yt-dlp (using the installed one): {error}").format(error=e))


def tdcli_dir() -> Path:
    return TOOLS_DIR / "TwitchDownloaderCLI"


def find_tdcli() -> str | None:
    """Our own copy first, then a TwitchDownloaderCLI next to the script / in bin / on PATH."""
    cand = tdcli_dir() / _TDCLI_EXE
    if cand.is_file():
        return str(cand)
    return find_tool("TwitchDownloaderCLI")


def _is_managed_tdcli(path: str | Path) -> bool:
    try:
        return Path(path).resolve().parent == tdcli_dir().resolve()
    except OSError:
        return False


def pick_tdcli_asset(names: list[str], plat: str | None = None, machine: str | None = None) -> str | None:
    """Which file of a TwitchDownloader release is the CLI for this system (matched by keywords)."""
    plat = plat or sys.platform
    arm = (machine or platform.machine()).lower().startswith(("arm", "aarch"))
    for name in names:
        n = name.lower()
        if not (n.startswith("twitchdownloadercli") and n.endswith(".zip")):
            continue
        if plat == "win32":
            ok = "windows" in n and "x64" in n  # the x64 build also runs on Windows on ARM
        elif plat == "darwin":
            ok = "mac" in n and (("arm" in n) if arm else ("x64" in n and "arm" not in n))
        else:
            ok = "linux" in n and "alpine" not in n and (("arm" in n) if arm else ("x64" in n and "arm" not in n))
        if ok:
            return name
    return None


def _tdcli_release(tag: str) -> dict:
    for candidate_tag in (tag, "v" + tag):
        try:
            r = _http_get(f"https://api.github.com/repos/{TDCLI_REPO}/releases/tags/{candidate_tag}")
        except requests.RequestException as e:
            raise EngineError(t("Could not reach GitHub to download TwitchDownloaderCLI:\n{error}").format(error=e)) from e
        if r.status_code == 404:
            continue
        if not r.ok:
            raise EngineError(t("GitHub refused the TwitchDownloaderCLI lookup (HTTP {code}). Try again in a few minutes.").format(code=r.status_code))
        return r.json()
    raise EngineError(t("TwitchDownloaderCLI {tag} was not found on GitHub.").format(tag=tag))


def _extract_tdcli(archive: Path, dest: Path) -> None:
    """Unzip the CLI and the files next to it into `dest`, whatever folder layout the zip has."""
    with zipfile.ZipFile(archive) as z:
        files = [i for i in z.infolist() if not i.is_dir()]
        main = next((i for i in files if PurePosixPath(i.filename.replace("\\", "/")).name == _TDCLI_EXE), None)
        if main is None:
            raise EngineError(t("The TwitchDownloaderCLI download did not contain the program."))
        root = PurePosixPath(main.filename.replace("\\", "/")).parent
        dest.mkdir(parents=True)
        base = dest.resolve()
        for info in files:
            try:
                rel = PurePosixPath(info.filename.replace("\\", "/")).relative_to(root)
            except ValueError:
                continue  # outside the folder that holds the program
            target = (dest / rel).resolve()
            if base not in target.parents:
                continue  # never write outside the destination
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    (dest / _TDCLI_EXE).chmod(0o755)


def install_tdcli(ctx: "Ctx", tag: str = TDCLI_VERSION) -> None:
    """Download the pinned TwitchDownloaderCLI release from GitHub into the tools folder."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    ctx.log(t("Downloading TwitchDownloaderCLI {tag} (needed for chat, one-time download)…").format(tag=tag))
    ctx.stage(0.0, 1.0, f"Downloading TwitchDownloaderCLI {tag}")
    release = _tdcli_release(tag)
    assets = [a for a in release.get("assets", []) if isinstance(a, dict) and a.get("name")]
    name = pick_tdcli_asset([a["name"] for a in assets])
    manual = (f"You can download it yourself from https://github.com/{TDCLI_REPO}/releases "
              f"and put the program in:\n{tdcli_dir()}")
    asset = next((a for a in assets if a["name"] == name), None)
    if not asset or not asset.get("browser_download_url"):
        raise EngineError(t("There is no TwitchDownloaderCLI build for this system in release {tag}.\n{manual}").format(tag=tag, manual=manual))
    archive = TOOLS_DIR / "TwitchDownloaderCLI.zip.download"
    staging = TOOLS_DIR / "TwitchDownloaderCLI.new"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _download_with_retry(ctx, asset["browser_download_url"], archive)
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            if _sha256(archive) != digest[len("sha256:"):].lower():
                raise EngineError(t("Checksum mismatch for TwitchDownloaderCLI: the download is corrupted, try again."))
        else:
            ctx.log(t("GitHub published no checksum for TwitchDownloaderCLI, so it was not verified."))
        try:
            _extract_tdcli(archive, staging)
        except zipfile.BadZipFile as e:
            raise EngineError(t("The TwitchDownloaderCLI download is not a valid zip file, try again.")) from e
        try:
            if tdcli_dir().exists():
                shutil.rmtree(tdcli_dir())
            os.replace(staging, tdcli_dir())
        except OSError as e:
            raise EngineError(t("TwitchDownloaderCLI is in use right now. Wait for running jobs to finish and try again.")) from e
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    _write_version("tdcli", tag)
    ctx.log(t("TwitchDownloaderCLI {tag} installed.").format(tag=tag))


def ensure_tdcli(ctx: "Ctx") -> str:
    """Path of TwitchDownloaderCLI: a copy the user provided as it is, ours only if it is the pinned version."""
    path = find_tdcli()
    if path and (not _is_managed_tdcli(path) or _read_versions().get("tdcli") == TDCLI_VERSION):
        return path
    install_tdcli(ctx)
    path = find_tdcli()
    if not path:
        raise EngineError(t("TwitchDownloaderCLI was installed but could not be found."))
    return path
