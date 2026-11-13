"""Open a folder in the platform's file manager (copied from luckytwitch_downloader.py; no Qt, no tkinter)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def atomic_write_json(
    path: Path | str,
    data: object,
    *,
    indent: int = 2,
    ensure_ascii: bool = True,
    chmod_mode: int | None = None,
) -> None:
    """Atomically serialize *data* as UTF-8 JSON to *path* via temp file + os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if chmod_mode is not None and sys.platform != "win32":
            try:
                os.chmod(tmp_name, chmod_mode)
            except OSError:
                pass
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def backup_corrupt_json(path: Path | str, max_backups: int = 3) -> None:
    """Rename a corrupted JSON file to <name>.corrupt.<timestamp> keeping at most max_backups."""
    import time
    target = Path(path)
    if not target.exists():
        return
    try:
        ts = time.strftime("%Y%m%d%H%M%S")
        backup = target.with_name(f"{target.name}.corrupt.{ts}")
        n = 1
        while backup.exists():
            backup = target.with_name(f"{target.name}.corrupt.{ts}_{n}")
            n += 1
        os.replace(target, backup)
        pattern = f"{target.name}.corrupt*"
        backups = sorted(target.parent.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[max_backups:]:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass




def open_in_file_manager(path: Path, select: bool = False) -> None:
    """Open a folder in Explorer / Finder / the file manager. With select=True and a file, highlight that file."""
    path = Path(path)
    if sys.platform == "win32":
        if select and path.is_file():
            # Explorer wants  /select,"C:\full path\file.mp4"  as ONE command line. Passing a list lets
            # Python quote the whole "/select,..." argument when the path has spaces, and Explorer then
            # ignores it and opens the Documents folder. So the command line is built by hand.
            norm = os.path.normpath(str(path)).replace('"', "")
            subprocess.Popen(f'explorer /select,"{norm}"')
        else:
            os.startfile(os.path.normpath(str(path if path.is_dir() else path.parent)))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if select and path.is_file() else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
