"""The worker threads that run the queue (port of ``App.start_queue`` and ``cancel_current``).

``QueueRunner.start(items, model=..., max_concurrent=...)`` runs ``run_job`` for waiting items.
When ``max_concurrent == 1`` (default), items run sequentially on a single worker.
When ``max_concurrent > 1``, up to N workers run in parallel, pulling dynamically from ``model``
in current row order. Nothing here touches a widget directly: worker threads report through the
Bridge (``job``, ``item``, ``log``, ``progress``, ``queue_done``) and the slots run on the GUI thread.
``run_job`` is looked up in this module when a job starts, so tests replace ``qt_ui.queue_runner.run_job``
with a fake (nothing is downloaded).
"""

from __future__ import annotations

import copy
import dataclasses
import re
import threading
from typing import Sequence

from PySide6.QtCore import QObject

from luckytwitch_engine import Cancelled, Ctx, run_job
from qt_ui.bridge import Bridge
from core.i18n import N_, t
from qt_ui.queue_model import QueueItem, QueueModel


def split_rate_limit(rate_limit: str, workers: int) -> str:
    """Divide a yt-dlp rate limit string (e.g. '10M', '5M', '500K') across ``workers``."""
    raw = (rate_limit or "").strip()
    if not raw or workers <= 1:
        return raw
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGkmg]?)$", raw)
    if not m:
        return raw
    val = float(m.group(1))
    unit = m.group(2).upper()
    per_worker = val / workers
    if per_worker >= 1.0 and per_worker.is_integer():
        return f"{int(per_worker)}{unit}"
    if unit == "G":
        kb = round(val * 1024 * 1024 / workers)
        return f"{kb // 1024}M" if kb % 1024 == 0 else f"{kb}K"
    if unit == "M":
        kb = round(val * 1024 / workers)
        return f"{max(1, kb)}K"
    if unit == "K":
        return f"{max(1, round(per_worker))}K"
    return f"{max(1, round(per_worker))}"


class QueueRunner(QObject):
    def __init__(self, bridge: Bridge, parent: QObject | None = None, max_concurrent: int = 1):
        super().__init__(parent)
        self.bridge = bridge
        self.max_concurrent = max(1, int(max_concurrent))
        self.ctx: Ctx | None = None  # the context of the running job (for cancel button backward compatibility)
        self.active_contexts: dict[str, Ctx] = {}  # iid -> Ctx for currently running jobs
        self._worker_progress: dict[str, float] = {}  # iid -> progress fraction for active jobs
        self.worker: threading.Thread | None = None  # coordinator thread (joined by tests)
        self.workers: list[threading.Thread] = []  # active worker threads
        self._lock = threading.RLock()
        self._cancel_all_event = threading.Event()

    def is_running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start(
        self,
        items: Sequence[QueueItem],
        model: QueueModel | None = None,
        max_concurrent: int | None = None,
        rate_limit: str = "",
    ) -> None:
        """Run ``items`` (or pull dynamically from ``model`` in current row order). Returns at once."""
        if self.is_running():
            return
        concurrency = max(1, int(max_concurrent if max_concurrent is not None else self.max_concurrent))
        self._cancel_all_event.clear()
        with self._lock:
            self._worker_progress.clear()
        bridge = self.bridge
        fallback = list(items)
        seen: set[str] = set()
        pick_lock = threading.Lock()
        counter_lock = threading.Lock()
        job_counter = [0]

        def pick_next() -> tuple[QueueItem | None, int]:
            with pick_lock:
                if model is not None:
                    with model._lock:
                        candidates = [it for it in model.items if it.status == "queued" and it.iid not in seen]
                        total = len(seen) + len(candidates)
                        if not candidates:
                            return None, total
                        nxt = candidates[0]
                        seen.add(nxt.iid)
                        return nxt, total
                candidates = [it for it in fallback if it.status == "queued" and it.iid not in seen]
                total = len(seen) + len(candidates)
                if not candidates:
                    return None, total
                nxt = candidates[0]
                seen.add(nxt.iid)
                return nxt, total

        def on_item_progress(iid: str, frac: float, text: str) -> None:
            with self._lock:
                self._worker_progress[iid] = float(frac)
                if len(self._worker_progress) > 1:
                    vals = list(self._worker_progress.values())
                    if all(v < 0 for v in vals):
                        overall_frac = -1.0
                    else:
                        overall_frac = sum(max(0.0, min(1.0, v)) for v in vals) / len(vals)
                else:
                    overall_frac = float(frac)
            bridge.progress.emit(overall_frac, text)
            if model is not None:
                bridge.item_progress.emit(iid, float(frac), text)

        def worker_loop():
            while not self._cancel_all_event.is_set():
                it, total = pick_next()
                if it is None:
                    break
                with counter_lock:
                    job_counter[0] += 1
                    cur_n = job_counter[0]

                ctx = Ctx(
                    log=lambda m, item_label=it.label: bridge.log.emit(
                        f"[{item_label}] {m}" if concurrency > 1 else m
                    ),
                    progress=lambda f, msg, item_id=it.iid: on_item_progress(item_id, f, msg),
                )
                with self._lock:
                    self.active_contexts[it.iid] = ctx
                    self._worker_progress[it.iid] = 0.0
                    self.ctx = ctx

                job_to_run = it.job
                opts = getattr(job_to_run, "opts", None)
                effective_limit = (rate_limit or "").strip() or (
                    getattr(opts, "rate_limit", "") if opts is not None else ""
                )
                if opts is not None and effective_limit:
                    per_worker = split_rate_limit(effective_limit, concurrency)
                    if dataclasses.is_dataclass(job_to_run) and dataclasses.is_dataclass(opts):
                        job_to_run = dataclasses.replace(
                            job_to_run,
                            opts=dataclasses.replace(opts, rate_limit=per_worker),
                        )
                    elif dataclasses.is_dataclass(opts):
                        job_to_run = copy.copy(job_to_run)
                        job_to_run.opts = dataclasses.replace(opts, rate_limit=per_worker)
                    else:
                        job_to_run = copy.copy(job_to_run)
                        new_opts = copy.copy(opts)
                        new_opts.rate_limit = per_worker
                        job_to_run.opts = new_opts
                bridge.job.emit(cur_n, total)
                bridge.item.emit(it.iid, N_("running…"))
                try:
                    results = run_job(job_to_run, ctx)
                    files_list = [str(p) for p in results]
                    if model is not None:
                        with model._lock:
                            it.files = files_list
                    else:
                        it.files = files_list
                    bridge.item.emit(it.iid, N_("done ({} files)").format(len(results)))
                except Cancelled:
                    bridge.item.emit(it.iid, "cancelled")
                    bridge.log.emit(f"Cancelled: {it.label}" if concurrency > 1 else "Cancelled.")
                    if concurrency == 1:
                        # Sequential queue stops on cancel
                        break
                except Exception as e:  # noqa: BLE001
                    bridge.item.emit(it.iid, "failed")
                    bridge.log.emit(t("ERROR: {error}", error=e))
                finally:
                    with self._lock:
                        self.active_contexts.pop(it.iid, None)
                        self._worker_progress.pop(it.iid, None)
                        self.ctx = next(iter(self.active_contexts.values()), None)

        def coordinator():
            workers = []
            for _ in range(concurrency):
                th = threading.Thread(target=worker_loop, daemon=True)
                workers.append(th)
                th.start()
            with self._lock:
                self.workers = workers
            for th in workers:
                th.join()
            with self._lock:
                self.workers = []
                self.active_contexts.clear()
                self._worker_progress.clear()
                self.ctx = None
            bridge.queue_done.emit()

        self.worker = threading.Thread(target=coordinator, daemon=True)
        self.worker.start()

    def cancel(self, iid: str | None = None) -> bool:
        """Cancel a running job (by iid) or all running jobs. False when there is none."""
        with self._lock:
            if iid is not None:
                ctx = self.active_contexts.get(iid)
                if ctx is not None:
                    ctx.cancel()
                    return True
                return False
            if not self.active_contexts and self.ctx is None:
                return False
            self._cancel_all_event.set()
            if self.ctx is not None:
                self.ctx.cancel()
            for ctx in list(self.active_contexts.values()):
                ctx.cancel()
            return True

    def finish(self) -> None:
        """The run is over (called on the GUI thread when ``queue_done`` arrives)."""
        with self._lock:
            self.ctx = None
            self.active_contexts.clear()
            self.workers = []
