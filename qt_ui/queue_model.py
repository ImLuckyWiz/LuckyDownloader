"""The queue as a table model (decision D5): five columns, one row per queued job.

``QueueItem`` keeps what the tkinter app kept in its ``items`` dicts: the job, the row id, the plain status word
(«done (3 files)» is stored as «done») and the files a finished job made. Phase 9c adds per-item progress
(``progress``, ``progress_text``), optional thumbnail preview (``thumb``), ``ITEM_ROLE`` / ``PROGRESS_ROLE`` for
the rich row delegate (F1), real-time status counters for the header banner (F2), and thread-safe reordering and
retry of waiting/failed/cancelled jobs (F4).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from core import paths
from core.files import atomic_write_json
from core.i18n import N_, t, tn
from core.job import Job, deserialize_job, serialize_job
from core.status import FINISHED, STATUS_COLOURS, queue_summary, status_label, status_word

COLUMNS = (  # key, heading, width, alignment, stretches
    ("n", "#", 40, "center", False),
    ("video", N_("Video"), 420, "w", True),
    ("parts", N_("Parts"), 70, "center", False),
    ("mode", N_("Strategy"), 140, "center", False),
    ("status", N_("Status"), 200, "w", False),
)
STATUS_ROLE = Qt.ItemDataRole.UserRole + 1  # the plain status word of the row («done»)
IID_ROLE = Qt.ItemDataRole.UserRole + 2  # the row id
ITEM_ROLE = Qt.ItemDataRole.UserRole + 3  # the QueueItem object (Phase 9c rich delegate)
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 4  # float 0.0..1.0 (or -1.0 indeterminate) for running row


def _alignment(kind: str) -> Qt.AlignmentFlag:
    return (Qt.AlignmentFlag.AlignHCenter if kind == "center" else Qt.AlignmentFlag.AlignLeft) | \
        Qt.AlignmentFlag.AlignVCenter


@dataclass
class QueueItem:
    job: object
    iid: str
    n: int  # the number shown in the «#» column when the row was added (not renumbered afterwards)
    label: str
    parts: int
    strategy: str
    status: str = "queued"  # the plain word: queued | running | done | failed | cancelled
    shown_status: str = "queued"  # the full text the job reported, e.g. «done (3 files)»
    files: list[str] = field(default_factory=list)
    progress: float = 0.0
    progress_text: str = ""
    thumb: object = None  # QPixmap or None (populated from job storyboard / thumbnail if available)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this QueueItem for persistent queue recovery."""
        # Any item that was running when the app closed/crashed is stored as queued so it can resume cleanly.
        persisted_status = "queued" if self.status == "running" else self.status
        persisted_shown = "queued" if self.status == "running" else self.shown_status
        return {
            "iid": self.iid,
            "n": int(self.n),
            "label": self.label,
            "parts": int(self.parts),
            "strategy": self.strategy,
            "status": persisted_status,
            "shown_status": persisted_shown,
            "files": list(self.files),
            "job": serialize_job(self.job) if isinstance(self.job, Job) else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], client: Any = None) -> QueueItem:
        raw_status = str(data.get("status", "queued"))
        raw_shown = str(data.get("shown_status", raw_status))
        if raw_status == "running":
            raw_status = "queued"
            raw_shown = "queued"
        job_data = data.get("job")
        job_obj = deserialize_job(job_data, client=client) if isinstance(job_data, dict) else None
        return cls(
            job=job_obj,
            iid=str(data.get("iid", "I001")),
            n=int(data.get("n", 1)),
            label=str(data.get("label", "")),
            parts=int(data.get("parts", 1)),
            strategy=str(data.get("strategy", "full")),
            status=raw_status,
            shown_status=raw_shown,
            files=[str(f) for f in (data.get("files") or [])],
            progress=1.0 if raw_status == "done" else 0.0,
            progress_text="",
            thumb=None,
        )


class QueueModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[QueueItem] = []
        self._counter = 0
        self._lock = threading.RLock()

    # ---- model interface ---- #
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(COLUMNS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            col_label = COLUMNS[section][1]
            return t(col_label) if col_label else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:  # the heading lines up with its column
            return int(_alignment(COLUMNS[section][3]))
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        it, col = self.items[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return (str(it.n), it.label, str(it.parts), it.strategy, status_label(it.shown_status))[col]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(_alignment(COLUMNS[col][3]))
        if role == Qt.ItemDataRole.ForegroundRole:  # each row is coloured by how its job is doing
            colour = STATUS_COLOURS.get(it.status)
            return QColor(colour) if colour else None
        if role == STATUS_ROLE:
            return it.status
        if role == IID_ROLE:
            return it.iid
        if role == ITEM_ROLE:
            return it
        if role == PROGRESS_ROLE:
            return it.progress
        return None

    # ---- the queue ---- #
    def add(self, job: object, label: str, n_parts: int, strategy: str, thumb: object = None) -> QueueItem:
        with self._lock:
            self._counter += 1
            item = QueueItem(job, f"I{self._counter:03d}", len(self.items) + 1, label, n_parts, strategy, thumb=thumb)
            row = len(self.items)
            self.beginInsertRows(QModelIndex(), row, row)
            self.items.append(item)
            self.endInsertRows()
            self.save_state()
            return item

    def find(self, iid: str) -> QueueItem | None:
        with self._lock:
            return next((i for i in self.items if i.iid == iid), None)

    def row_of(self, iid: str) -> int:
        with self._lock:
            return next((r for r, i in enumerate(self.items) if i.iid == iid), -1)

    def running_item(self) -> QueueItem | None:
        with self._lock:
            return next((i for i in self.items if i.status == "running"), None)

    def next_queued(self) -> QueueItem | None:
        """Thread-safely return the next waiting item in the current table order (Phase 9c, F4)."""
        with self._lock:
            return next((i for i in self.items if i.status == "queued"), None)

    def set_status(self, iid: str, status: str) -> bool:
        """«done (3 files)» -> the row says that, the stored status is «done». False when the row is gone."""
        with self._lock:
            row = self.row_of(iid)
            if row < 0:
                return False
            item = self.items[row]
            item.status = status_word(status)
            item.shown_status = status
            if item.status == "done":
                item.progress = 1.0
            elif item.status in ("queued", "failed", "cancelled"):
                item.progress = 0.0
                item.progress_text = ""
            self.save_state()
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))
        return True

    def set_progress(self, iid: str, frac: float, text: str = "") -> bool:
        """Update the in-row progress of ``iid`` (Phase 9c, F1)."""
        with self._lock:
            row = self.row_of(iid)
            if row < 0:
                return False
            item = self.items[row]
            item.progress = float(frac)
            item.progress_text = text
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))
        return True

    def set_running_progress(self, frac: float, text: str = "") -> bool:
        """Update the in-row progress of whichever item is currently ``running``."""
        with self._lock:
            item = self.running_item()
            if item is None:
                return False
            iid = item.iid
        return self.set_progress(iid, frac, text)

    def set_thumbnail(self, iid: str, thumb: object) -> bool:
        with self._lock:
            row = self.row_of(iid)
            if row < 0:
                return False
            self.items[row].thumb = thumb
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))
        return True

    def move_row(self, source_row: int, target_row: int) -> bool:
        """Reorder a waiting («queued») row to ``target_row`` (Phase 9c, F4). Never moves a running row."""
        with self._lock:
            n = len(self.items)
            if not (0 <= source_row < n and 0 <= target_row < n) or source_row == target_row:
                return False
            item = self.items[source_row]
            if item.status != "queued":
                return False
            if self.items[target_row].status == "running":
                return False
            dest = target_row + 1 if target_row > source_row else target_row
            if not self.beginMoveRows(QModelIndex(), source_row, source_row, QModelIndex(), dest):
                return False
            moved = self.items.pop(source_row)
            self.items.insert(target_row, moved)
            self.endMoveRows()
            self.save_state()
            return True

    def move_item(self, iid: str, delta: int) -> bool:
        """Step a waiting («queued») item up (``delta < 0``) or down (``delta > 0``) among waiting rows."""
        with self._lock:
            row = self.row_of(iid)
            if row < 0 or self.items[row].status != "queued":
                return False
            step = -1 if delta < 0 else 1
            target = row + step
            while 0 <= target < len(self.items):
                if self.items[target].status == "queued":
                    return self.move_row(row, target)
                target += step
            return False

    def retry_item(self, iid: str) -> QueueItem | None:
        """Reset a ``failed`` or ``cancelled`` item back to ``queued`` and move it to the end of the queue (F4)."""
        with self._lock:
            row = self.row_of(iid)
            if row < 0:
                return None
            item = self.items[row]
            if item.status not in ("failed", "cancelled"):
                return None
            item.status = "queued"
            item.shown_status = "queued"
            item.progress = 0.0
            item.progress_text = ""
            item.files = []
            last = len(self.items) - 1
            if row != last:
                self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), last + 1)
                moved = self.items.pop(row)
                self.items.append(moved)
                self.endMoveRows()
                row = last
            self.save_state()
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))
        return item

    def remove(self, iid: str) -> None:
        with self._lock:
            row = self.row_of(iid)
            if row >= 0:
                self.beginRemoveRows(QModelIndex(), row, row)
                del self.items[row]
                self.endRemoveRows()
                self.save_state()

    def clear_finished(self) -> None:
        with self._lock:
            finished_iids = [i.iid for i in self.items if i.status in FINISHED]
        for iid in finished_iids:
            self.remove(iid)

    def clear_all(self, keep_running: bool = False) -> list[str]:
        """Atomically clear items from the queue. If keep_running is True, the running job is preserved."""
        with self._lock:
            if keep_running:
                running = [i for i in self.items if i.status == "running"]
                removed = [i.iid for i in self.items if i.status != "running"]
                self.beginResetModel()
                self.items = running
                for idx, item in enumerate(self.items, start=1):
                    item.n = idx
                self.endResetModel()
                self.save_state()
                return removed
            else:
                removed = [i.iid for i in self.items]
                self.beginResetModel()
                self.items.clear()
                self.endResetModel()
                self.save_state()
                return removed

    def save_state(self, path: Path | None = None) -> None:
        """Persist real Job items to disk so unfinished downloads survive app restarts or updates."""
        target = path or getattr(paths, "QUEUE_STATE_FILE", paths.DATA_DIR / "queue_state.json")
        with self._lock:
            serializable = [it.to_dict() for it in self.items if isinstance(it.job, Job)]
            counter = self._counter
        try:
            atomic_write_json(target, {"version": 1, "counter": counter, "items": serializable})
        except Exception:  # noqa: BLE001
            pass

    def load_state(self, path: Path | None = None, client: Any = None, only_unfinished: bool = False) -> list[QueueItem]:
        """Restore saved QueueItems from disk into the model. Running items are recovered as 'queued'."""
        target = path or getattr(paths, "QUEUE_STATE_FILE", paths.DATA_DIR / "queue_state.json")
        if not target.is_file():
            return []
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(raw, dict):
            return []
        items_raw = raw.get("items")
        if not isinstance(items_raw, list):
            return []
        restored: list[QueueItem] = []
        for entry in items_raw:
            if not isinstance(entry, dict) or not isinstance(entry.get("job"), dict):
                continue
            try:
                item = QueueItem.from_dict(entry, client=client)
            except Exception:  # noqa: BLE001
                continue
            if only_unfinished and item.status == "done":
                continue
            restored.append(item)
        if not restored:
            return []
        with self._lock:
            self.beginResetModel()
            self.items = list(restored)
            max_num = max(
                (int(it.iid[1:]) for it in restored if it.iid.startswith("I") and it.iid[1:].isdigit()),
                default=0,
            )
            self._counter = max(int(raw.get("counter", 0)), max_num, len(restored))
            for idx, item in enumerate(self.items, start=1):
                item.n = idx
            self.endResetModel()
            self.save_state(target)
        return restored

    def summary(self) -> str:
        with self._lock:
            return queue_summary([i.status for i in self.items])

    def counts(self) -> dict[str, int]:
        """Return ``{"done": N, "running": N, "waiting": N, "failed": N, "cancelled": N}`` (Phase 9c, F2)."""
        with self._lock:
            statuses = [i.status for i in self.items]
        return {
            "done": statuses.count("done"),
            "running": statuses.count("running"),
            "waiting": statuses.count("queued"),
            "failed": statuses.count("failed"),
            "cancelled": statuses.count("cancelled"),
        }

    def refresh_language(self) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)

    def header_summary(self) -> str:
        """Real-time counter banner text: ``N done · N running · N waiting · N failed`` (Phase 9c, F2)."""
        c = self.counts()
        return f"{c['done']} {t('done')} · {c['running']} {t('running')} · {c['waiting']} {t('waiting')} · {c['failed']} {t('failed')}"
