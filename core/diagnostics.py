"""System diagnostics collection and rotating file logging for LuckyDownloader."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile

from core import paths
from core.runtime import _NO_WINDOW, _tool_env, find_tool

SENSITIVE_KEYWORDS = ("cookie", "token", "password", "secret", "auth", "credential", "key")


def setup_file_logging() -> Path:
    """Configure rotating file logging writing to paths.DATA_DIR / "logs" / "luckydownloader.log"."""
    log_dir = paths.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "luckydownloader.log"
    target_path = os.path.abspath(str(log_file))
    root = logging.getLogger()
    existing = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    if not any(os.path.abspath(getattr(h, "baseFilename", "")) == target_path for h in existing):
        for h in existing:
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        handler = RotatingFileHandler(
            log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        logging.getLogger("luckydownloader").setLevel(logging.INFO)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("PIL").setLevel(logging.WARNING)
    return log_file


def _get_tool_version(name: str, flag: str) -> str:
    tool_path = find_tool(name)
    if not tool_path:
        return "not installed"
    try:
        out = subprocess.run(
            [tool_path, flag],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=_tool_env(),
            creationflags=_NO_WINDOW,
            timeout=10,
        ).stdout
        return (out.strip().splitlines() or ["?"])[0].strip()
    except Exception as e:
        return f"error: {e}"


_SENSITIVE_PARAM_RE = re.compile(
    r"([?&](?:token|sig|key|Policy|X-Amz-Signature)=)[^&\s\"']+",
    re.IGNORECASE,
)


def _scrub_text(text: str) -> str:
    """Scrub user home directory paths and sensitive URL query parameters from text."""
    if not text:
        return text
    home_str = str(Path.home())
    if home_str:
        text = text.replace(home_str, "~")
        home_fwd = home_str.replace("\\", "/")
        if home_fwd != home_str:
            text = text.replace(home_fwd, "~")
    return _SENSITIVE_PARAM_RE.sub(r"\1[REDACTED]", text)


def redact_settings(settings: dict) -> dict:
    """Return a deep copy of settings with sensitive authentication / tokens / cookies redacted."""
    redacted = {}
    for k, v in settings.items():
        k_lower = str(k).lower()
        if any(kw in k_lower for kw in SENSITIVE_KEYWORDS):
            redacted[k] = "[REDACTED]"
        elif isinstance(v, dict):
            redacted[k] = redact_settings(v)
        elif isinstance(v, str):
            redacted[k] = _scrub_text(v)
        else:
            redacted[k] = v
    return redacted


def export_diagnostics_zip(dest_zip: Path | str) -> Path:
    """Create a diagnostic zip file containing system info, redacted settings, and log file."""
    from core.settings import load_settings

    dest = Path(dest_zip)
    dest.parent.mkdir(parents=True, exist_ok=True)

    app_version = paths.BUNDLED_VERSION or paths.read_bundled_version() or "dev"

    system_info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "app_version": app_version,
        "ytdlp_version": _get_tool_version("yt-dlp", "--version"),
        "ffmpeg_version": _get_tool_version("ffmpeg", "-version"),
    }

    raw_settings = load_settings()
    redacted_settings = redact_settings(raw_settings)

    log_file = paths.DATA_DIR / "logs" / "luckydownloader.log"

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system_info.json", json.dumps(system_info, indent=2))
        zf.writestr("settings_redacted.json", json.dumps(redacted_settings, indent=2))
        corrupt_files = sorted(p.name for p in paths.DATA_DIR.glob("*.corrupt*"))
        zf.writestr("persistence_health.json", json.dumps({"corrupt_backups": corrupt_files}, indent=2))
        if log_file.is_file():
            try:
                log_text = _scrub_text(log_file.read_text(encoding="utf-8", errors="replace"))
                zf.writestr("logs/luckydownloader.log", log_text)
            except OSError:
                pass

    return dest
