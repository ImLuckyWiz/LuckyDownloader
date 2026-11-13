"""
Runtime execution context: logging, progress, cancellation, tool location and process management.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from core.errors import Cancelled

_override_provider: Callable[[str, Any], Any] | None = None


def register_override_provider(provider: Callable[[str, Any], Any] | None) -> None:
    """Register an optional override provider hook (e.g. from facade modules for test monkeypatching)."""
    global _override_provider
    _override_provider = provider


def resolve_dep(name: str, default: Any, local_current: Any = None) -> Any:
    """Resolve a dependency by name, preferring local module patches first, then any registered provider."""
    if local_current is not None and local_current is not default:
        return local_current
    if _override_provider is not None:
        val = _override_provider(name, default)
        if val is not None:
            return val
    return local_current if local_current is not None else default

APP_DIR = (
    Path(sys.executable).parent
    if (getattr(sys, "frozen", False) or "__compiled__" in globals() or hasattr(sys.modules.get("__main__"), "__compiled__"))
    else Path(__file__).resolve().parent.parent
)


def user_data_dir() -> Path:
    """Per-user, always writable folder (also works when the app is frozen / inside a .app)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "LuckyDownloader"


def legacy_user_data_dir() -> Path:
    """Legacy per-user folder used by LuckyTwitch (v1.x/v2.x prior to rebrand)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "LuckyTwitch"


TOOLS_DIR = Path(
    os.environ.get("LUCKYDOWNLOADER_TOOLS_DIR")
    or os.environ.get("LUCKYTWITCH_TOOLS_DIR")
    or user_data_dir() / "tools"
)
EXE = ".exe" if sys.platform == "win32" else ""
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
USER_AGENT = "LuckyDownloader/1.0 (+https://github.com/yt-dlp/yt-dlp)"


def find_tool(name: str) -> str | None:
    """
    Where is `name` (yt-dlp / ffmpeg / ffprobe)? Order: our tools folder, next to
    the script, ./bin, PyInstaller bundle, PATH and (macOS) the Homebrew folders
    (a GUI app on macOS does not inherit the shell's PATH).
    """
    dirs = [TOOLS_DIR, APP_DIR, APP_DIR / "bin"]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        dirs.append(Path(bundle))
    for d in dirs:
        cand = d / (name + EXE)
        if cand.is_file():
            return str(cand)
    exe = shutil.which(name)
    if exe:
        return exe
    if sys.platform == "darwin":
        for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
            cand = Path(d) / name
            if cand.is_file():
                return str(cand)
    return None


def _tool_env() -> dict[str, str]:
    """Environment for yt-dlp / ffmpeg: force UTF-8 so titles with emojis survive the pipe."""
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a process and its children (yt-dlp.exe spawns a child, and yt-dlp spawns ffmpeg)."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=_NO_WINDOW,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


class Ctx:
    def __init__(
        self,
        log: Callable[[str], None] | None = None,
        progress: Callable[[float, str], None] | None = None,
    ):
        self._log = log or (lambda m: None)
        self._progress = progress or (lambda f, t: None)
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self._lo, self._hi, self._label = 0.0, 1.0, ""
        self._log_step, self._log_t = -1, float("-inf")

    # -- logging / progress -- #
    def log(self, msg: str) -> None:
        import logging
        logging.getLogger("luckydownloader").info("%s", msg)
        self._log(msg)

    def stage(self, lo: float, hi: float, label: str) -> None:
        self._lo, self._hi, self._label = lo, hi, label
        self._log_step, self._log_t = -1, float("-inf")
        self._progress(lo, label)

    def span(self) -> tuple[float, float]:
        """The share of the progress bar the current stage owns, to split it into smaller stages."""
        return self._lo, self._hi

    def relabel(self, label: str) -> None:
        """New label for the current stage, keeping its share of the progress bar."""
        self.stage(self._lo, self._hi, label)

    def report(self, frac: float | None, extra: str = "") -> None:
        text = self._label + (f"  ·  {extra}" if extra else "")
        if frac is None:
            self._progress(-1, text)
        else:
            frac = min(max(frac, 0.0), 1.0)
            self._progress(self._lo + frac * (self._hi - self._lo), text)

    def log_progress(self, frac: float | None, extra: str = "") -> None:
        """Write a progress line to the log: every 10% (or every 30 s if there is no percentage)."""
        now = time.monotonic()
        step = int(min(max(frac, 0.0), 1.0) * 10) if frac is not None else None
        if (step is not None and step > self._log_step) or now - self._log_t >= 30:
            if step is not None:
                self._log_step = max(self._log_step, step)
            self._log_t = now
            pct = f"{min(max(frac, 0.0), 1.0) * 100:.0f}%" if frac is not None else ""
            body = " · ".join(x for x in (pct, extra) if x)
            self._log(f"{self._label}: {body}" if body else self._label)

    # -- cancel -- #
    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def attach_proc(self, proc: subprocess.Popen | None) -> None:
        with self._lock:
            self.proc = proc
            cancelled = self.cancel_event.is_set()
        if cancelled and proc is not None:
            kill_process_tree(proc)
            with self._lock:
                if self.proc is proc:
                    self.proc = None
            raise Cancelled("Cancelled.")

    def cancel(self) -> None:
        with self._lock:
            self.cancel_event.set()
            proc = self.proc
        if proc:
            kill_process_tree(proc)

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled("Cancelled.")
