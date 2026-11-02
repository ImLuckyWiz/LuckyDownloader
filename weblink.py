"""
Links that open the app: ``luckydownloader://open?url=<VOD link>&cuts=<cut points>&label=<name>``.

Any web page, document or other program can offer such a link. Clicking it opens LuckyDownloader (or
brings the open window to the front) with the VOD and the cut points already filled in on the Plan tab.
A link only fills in the form. It never adds anything to the queue and never starts a download: the person
still checks the cut points and presses the button.

Legacy ``luckytwitch://`` links are preserved and remain fully supported as aliases.

This file has no GUI code, so it can be tested without a display. The format is described in
docs/link-format.md.

Parts:
    parse_link / build_link       the link format
    hand_off / take_links / beat  passing a link from a second launch to the window that is already open
    registration / register       making the operating system send links to this app (Windows)
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

SCHEME = "luckydownloader"
LEGACY_SCHEMES = ("luckytwitch",)
SUPPORTED_SCHEMES = ("luckydownloader", "luckytwitch")
VERSION = 1  # layout of the link. Unknown extra parameters are ignored; a higher ``v`` is refused

MAX_URL = 2000
MAX_CUTS = 2000
MAX_LABEL = 120
MAX_LINK = 8000  # whole link, as received

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # everything except tab, newline, carriage return


class LinkError(ValueError):
    """The link cannot be used. The message is written for the person, not for a developer."""


@dataclass(frozen=True)
class OpenRequest:
    url: str  # the VOD (or any link yt-dlp understands), http or https
    cuts: str = ""  # cut points, written as in the Plan tab. Empty: keep the default (whole VOD)
    label: str = ""  # a short name to show in the log, e.g. the title of a job


# --------------------------------------------------------------------------- the link format
def _clean(text: str, limit: int, field: str, multiline: bool = False) -> str:
    text = _CONTROL.sub("", text or "")
    if not multiline:
        text = " ".join(text.split())
    else:
        text = "\n".join(line.strip() for line in text.replace("\r", "").split("\n")).strip()
    if len(text) > limit:
        raise LinkError(f"The link's «{field}» is too long ({len(text)} characters, the limit is {limit}).")
    return text


def _blocked_host(host: str) -> bool:
    """Addresses that only make sense on this computer or its network: a web page has no business asking
    the app to read those."""
    host = host.strip("[]").lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_global


def parse_link(text: str) -> OpenRequest:
    """``luckydownloader://open?url=...`` (or legacy ``luckytwitch://...``) -> OpenRequest. Raises LinkError with a readable message."""
    text = (text or "").strip().strip('"')
    if len(text) > MAX_LINK:
        raise LinkError("That link is too long to be a LuckyDownloader link.")
    parts = urlsplit(text)
    if parts.scheme.lower() not in SUPPORTED_SCHEMES:
        raise LinkError("That is not a luckydownloader:// link.")

    action = (parts.netloc or parts.path).strip("/").lower()
    if action != "open":
        raise LinkError(
            f"This link asks for «{action or 'nothing'}», which this version of the app does not know. "
            "Update LuckyDownloader and try again."
        )

    params: dict[str, str] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        params.setdefault(key.lower(), value)  # the first one wins

    version = params.get("v", "").strip()
    if version:
        if not version.isdigit():
            raise LinkError("The link has a version this app cannot read.")
        if int(version) > VERSION:
            raise LinkError("This link was made for a newer version of the app. Update LuckyDownloader and try again.")

    url = _clean(params.get("url", ""), MAX_URL, "url")
    if not url:
        raise LinkError("The link does not say which VOD to open.")
    if re.search(r"\s", url):
        raise LinkError("The VOD address in the link contains spaces.")
    target = urlsplit(url)
    if target.scheme.lower() not in ("http", "https") or not target.hostname:
        raise LinkError("The VOD address in the link must start with http:// or https://.")
    if target.username or target.password:
        raise LinkError("The VOD address in the link must not contain a user name or password.")
    if _blocked_host(target.hostname):
        raise LinkError("The VOD address in the link points to this computer or a private network, so it was not opened.")

    cuts = _clean(params.get("cuts", ""), MAX_CUTS, "cuts", multiline=True)
    label = _clean(params.get("label", ""), MAX_LABEL, "label")
    return OpenRequest(url=url, cuts=cuts, label=label)


def build_link(url: str, cuts: str = "", label: str = "", scheme: str = SCHEME) -> str:
    """The link for a VOD. Used by the tests and handy for anyone writing a page that offers one."""
    query = [("v", str(VERSION)), ("url", url)]
    if cuts:
        query.append(("cuts", cuts))
    if label:
        query.append(("label", label))
    return f"{scheme}://open?" + "&".join(f"{k}={quote(v, safe='')}" for k, v in query)


def find_link(argv: list[str]) -> str | None:
    """The first command-line argument that is a luckydownloader: or luckytwitch: link."""
    for arg in argv:
        cleaned = arg.strip().strip('"')
        for s in SUPPORTED_SCHEMES:
            if cleaned.lower().startswith(s + ":"):
                return cleaned
    return None


# --------------------------------------------------------------------------- one window only
# A second launch (the browser starts the program again for every click) must not open a second window.
# It leaves the link as a small file in a folder the running window watches, then waits for it to be taken.
# Nothing listens on the network, so nothing outside this computer's files can reach the app.
BEAT_FRESH = 6.0  # seconds: how recent the running window's heartbeat must be
MAX_WAITING = 20  # links waiting in the folder; more than that are refused
MAX_AGE = 300.0  # a link left in the folder for longer than this is stale and ignored


def beat(path: Path) -> None:
    """The open window calls this every couple of seconds to say it is alive."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def is_running(path: Path, now: float | None = None) -> bool:
    try:
        stamp = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (now if now is not None else time.time()) - stamp <= BEAT_FRESH


def _drop(inbox: Path, link: str) -> Path | None:
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        if len(list(inbox.glob("*.link"))) >= MAX_WAITING:
            return None
        name = f"{time.time_ns()}-{os.getpid()}"
        tmp = inbox / (name + ".tmp")
        tmp.write_text(link, encoding="utf-8")
        final = inbox / (name + ".link")
        tmp.replace(final)  # the window only ever sees finished files
        return final
    except OSError:
        return None


def hand_off(link: str, inbox: Path, heartbeat: Path, wait: float = 3.0, poll: float = 0.1) -> bool:
    """Give the link to the window that is already open. True when that window took it.

    False means there is no such window (or it did not answer in time): the caller opens its own window and
    uses the link itself. The file is removed in that case, so the link is never used twice.
    """
    if not is_running(heartbeat):
        return False
    path = _drop(inbox, link)
    if path is None:
        return False
    end = time.time() + wait
    while time.time() < end:
        if not path.exists():
            return True
        time.sleep(poll)
    try:
        path.unlink()
    except OSError:
        return True  # it was taken in the last instant
    return False


def take_links(inbox: Path, now: float | None = None) -> list[str]:
    """The links waiting for the open window, oldest first. Each one is removed as it is read."""
    out: list[str] = []
    try:
        files = sorted(inbox.glob("*.link"))
    except OSError:
        return out
    now = now if now is not None else time.time()
    for path in files:
        try:
            fresh = now - path.stat().st_mtime <= MAX_AGE
            text = path.read_text(encoding="utf-8") if fresh else ""
            path.unlink()
        except OSError:
            continue
        if text.strip():
            out.append(text.strip())
    return out


# --------------------------------------------------------------------------- telling the system about the scheme
# Windows keeps this per user (HKEY_CURRENT_USER\Software\Classes), so it needs no administrator rights. The
# installer writes the same entries. On macOS the app bundle declares the scheme (see build_mac.sh), so there is
# nothing to do at run time.
_KEY = r"Software\Classes\luckydownloader"
_LEGACY_KEY = r"Software\Classes\luckytwitch"


@dataclass(frozen=True)
class Registration:
    supported: bool  # can this system be set up from inside the app?
    state: str  # "ok" (points at this app) | "other" (points somewhere else) | "missing" | "unsupported"
    command: str = ""  # what the system currently runs for such a link


def launch_command(exe: str | None = None, script: str | None = None) -> str:
    """The command the system should run, with ``%1`` where the link goes."""
    if getattr(sys, "frozen", False) or "__compiled__" in globals() or hasattr(sys.modules.get("__main__"), "__compiled__") or exe:
        return f'"{exe or sys.executable}" "%1"'
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")  # no console window when started from a link
    if windowless.exists():
        python = windowless
    return f'"{python}" "{script or Path(sys.argv[0]).resolve()}" "%1"'


def _winreg():
    if sys.platform != "win32":
        return None
    import winreg

    return winreg


def _same_command(a: str, b: str) -> bool:
    return os.path.normcase(a.strip()) == os.path.normcase(b.strip())


def registration(expected: str | None = None, reg=None) -> Registration:
    reg = reg or _winreg()
    if reg is None:
        return Registration(False, "unsupported")
    expected = expected or launch_command()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, _KEY + r"\shell\open\command") as key:
            command = str(reg.QueryValueEx(key, "")[0])
    except OSError:
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, _LEGACY_KEY + r"\shell\open\command") as key:
                command = str(reg.QueryValueEx(key, "")[0])
        except OSError:
            return Registration(True, "missing")
    return Registration(True, "ok" if _same_command(command, expected) else "other", command)


def register(expected: str | None = None, reg=None) -> None:
    """Point luckydownloader: and luckytwitch: links at this app. Raises OSError if the system refuses."""
    reg = reg or _winreg()
    if reg is None:
        raise OSError("Links are set up by the app bundle on this system.")
    expected = expected or launch_command()

    def put(subkey: str, name: str, value: str) -> None:
        with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, subkey, 0, reg.KEY_SET_VALUE) as key:
            reg.SetValueEx(key, name, 0, reg.REG_SZ, value)

    for k in (_KEY, _LEGACY_KEY):
        put(k, "", "URL:LuckyDownloader Link")
        put(k, "URL Protocol", "")
        put(k + r"\shell\open\command", "", expected)
