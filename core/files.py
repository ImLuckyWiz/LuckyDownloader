"""File manager opener, atomic JSON persistence, locking, and JsonStore helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Generic, Mapping, TypeVar

T = TypeVar("T")

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def get_path_lock(path: Path | str) -> threading.RLock:
    """Return a shared re-entrant lock keyed by normalized absolute file path."""
    key = os.path.normcase(os.path.abspath(str(path)))
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


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


def backup_corrupt_json(path: Path | str, max_backups: int = 3) -> Path | None:
    """Rename a corrupted JSON file to <name>.corrupt.<YYYYMMDD-HHMMSS> keeping at most max_backups."""
    target = Path(path)
    if not target.exists():
        return None
    try:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = target.with_name(f"{target.name}.corrupt.{ts}")
        n = 1
        while backup.exists():
            backup = target.with_name(f"{target.name}.corrupt.{ts}_{n}")
            n += 1
        os.replace(target, backup)
        pattern = f"{target.name}.corrupt*"

        def _sort_key(p: Path) -> tuple[int, str]:
            try:
                return (p.stat().st_mtime_ns, p.name)
            except OSError:
                return (0, p.name)

        backups = sorted(target.parent.glob(pattern), key=_sort_key, reverse=True)
        for old in backups[max(0, max_backups):]:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass
        return backup
    except OSError:
        return None


class JsonStore(Generic[T]):
    """Typed JSON file store with per-path RLock, atomic writes, corrupt backup rotation, and schema migrations."""

    def __init__(
        self,
        path: Path | str | Callable[[], Path | str],
        default_factory: Callable[[], T],
        *,
        expected_type: type | tuple[type, ...] = (dict, list),
        schema_version: int | None = None,
        migrations: Mapping[int, Callable[[Any], Any]] | None = None,
        wrap_envelope: bool = False,
        serializer: Callable[[T], Any] | None = None,
        deserializer: Callable[[Any], T] | None = None,
        indent: int = 2,
        ensure_ascii: bool = True,
        chmod_mode: int | None = None,
        max_backups: int = 3,
    ) -> None:
        self._path = path
        self.default_factory = default_factory
        self.expected_type = expected_type
        self.schema_version = schema_version
        self.migrations: dict[int, Callable[[Any], Any]] = dict(migrations) if migrations else {}
        self.wrap_envelope = wrap_envelope
        self.serializer = serializer
        self.deserializer = deserializer
        self.indent = indent
        self.ensure_ascii = ensure_ascii
        self.chmod_mode = chmod_mode
        self.max_backups = max_backups

    def resolve_path(self, path: Path | str | None = None) -> Path:
        if path is not None:
            return Path(path)
        raw = self._path() if callable(self._path) else self._path
        return Path(raw)

    def lock(self, path: Path | str | None = None) -> threading.RLock:
        return get_path_lock(self.resolve_path(path))

    def register_migration(self, from_version: int, fn: Callable[[Any], Any]) -> None:
        self.migrations[int(from_version)] = fn

    def _write_raw(self, target: Path, raw: Any) -> None:
        if self.wrap_envelope and self.schema_version is not None:
            out: Any = {"schema_version": self.schema_version, "data": raw}
        elif self.schema_version is not None and (self.schema_version > 1 or bool(self.migrations)):
            if isinstance(raw, dict):
                out = {"schema_version": self.schema_version, **raw}
            else:
                out = {"schema_version": self.schema_version, "data": raw}
        else:
            out = raw
        atomic_write_json(
            target,
            out,
            indent=self.indent,
            ensure_ascii=self.ensure_ascii,
            chmod_mode=self.chmod_mode,
        )

    def _migrate_payload(self, payload: Any, file_version: int) -> Any:
        if self.schema_version is None or file_version >= self.schema_version:
            return payload
        if self.migrations:
            target_keyed = self.schema_version in self.migrations and file_version not in self.migrations
            for cur in range(file_version, self.schema_version):
                fn = (
                    self.migrations.get(cur + 1)
                    if target_keyed
                    else (self.migrations.get(cur) or self.migrations.get(cur + 1))
                )
                if fn is not None:
                    payload = fn(payload)
        return payload

    def load(self, path: Path | str | None = None) -> T:
        target = self.resolve_path(path)
        with get_path_lock(target):
            if not target.is_file():
                return self.default_factory()
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                backup_corrupt_json(target, max_backups=self.max_backups)
                return self.default_factory()
            except OSError:
                return self.default_factory()

            if (
                isinstance(raw, dict)
                and "schema_version" in raw
                and isinstance(raw["schema_version"], int)
                and not isinstance(raw["schema_version"], bool)
            ):
                file_version = int(raw["schema_version"])
                if "data" in raw and (
                    self.wrap_envelope
                    or not isinstance(raw.get("data"), dict)
                    or set(raw.keys()) <= {"schema_version", "data"}
                ):
                    payload = raw["data"]
                else:
                    payload = {k: v for k, v in raw.items() if k != "schema_version"}
            else:
                payload = raw
                file_version = 0 if (self.migrations and 0 in self.migrations) else 1

            needs_migration = self.schema_version is not None and file_version < self.schema_version
            if not isinstance(payload, self.expected_type) and not (needs_migration and self.migrations):
                backup_corrupt_json(target, max_backups=self.max_backups)
                return self.default_factory()

            if needs_migration:
                try:
                    payload = self._migrate_payload(payload, file_version)
                except Exception:
                    backup_corrupt_json(target, max_backups=self.max_backups)
                    return self.default_factory()
                if not isinstance(payload, self.expected_type):
                    backup_corrupt_json(target, max_backups=self.max_backups)
                    return self.default_factory()
                try:
                    self._write_raw(target, payload)
                except OSError:
                    pass

            if self.deserializer is not None:
                try:
                    return self.deserializer(payload)
                except Exception:
                    backup_corrupt_json(target, max_backups=self.max_backups)
                    return self.default_factory()
            return payload

    def save(self, data: T, path: Path | str | None = None) -> None:
        target = self.resolve_path(path)
        with get_path_lock(target):
            raw = self.serializer(data) if self.serializer is not None else data
            try:
                self._write_raw(target, raw)
            except OSError:
                pass

    def update(self, fn: Callable[[T], T | None], path: Path | str | None = None) -> T:
        target = self.resolve_path(path)
        with get_path_lock(target):
            current = self.load(path=target)
            updated = fn(current)
            if updated is None:
                updated = current
            self.save(updated, path=target)
            return updated

    def clear(self, path: Path | str | None = None) -> None:
        target = self.resolve_path(path)
        with get_path_lock(target):
            try:
                if target.is_file():
                    target.unlink()
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
