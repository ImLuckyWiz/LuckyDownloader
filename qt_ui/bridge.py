"""Worker threads -> GUI thread.

The tkinter app puts tagged tuples on a queue that ``poll_queue`` empties every 100 ms. Here every message kind
is one typed Qt signal on a ``Bridge``. A worker thread calls ``bridge.<kind>.emit(...)``; the slots run on the
GUI thread (queued connection), so a slot may touch widgets, QPixmap and dialogs.

Rules:
  * Create the Bridge on the GUI thread (a QObject belongs to the thread it was created in).
  * Connect to a method of a QObject that lives on the GUI thread (a widget, the main window): then Qt knows
    which thread the slot must run in. (tests/test_qt_bridge.py also checks that, with PySide6 6.12, a plain
    function or lambda is delivered on the GUI thread too. Prefer methods anyway.)
  * Workers emit plain Python data only. Never hand a widget or a QPixmap to a worker (QImage is fine).
  * "No value" is an empty string where the tkinter message carried None (``tools_done``, ``saved_chat_done``).

The kinds are the ones in PLAN.md section 3.4. The Twitch sign-in dialog has its own messages (code, ok, error,
cancelled); they come with the dialog in Phase 4.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

# the tkinter message kinds, in the order of poll_queue; ``Bridge.KINDS`` and the tests use this
KINDS = (
    "info_ok", "error", "log", "search_ok", "search_err", "videos_ok", "videos_err", "thumb", "frames",
    "progress", "job", "item", "tools_info", "tools_done", "saved_chat_done", "queue_done", "update_checked",
    "update_download_done",
)


class Bridge(QObject):
    KINDS = KINDS

    # Get info finished: (SourceInfo, clips: list[dict], clips_loaded: bool, warning: str | None)
    info_ok = Signal(object, object, object, object)
    # a worker failed in a way that needs a message box: (message)
    error = Signal(str)
    # one line for the log (message)
    log = Signal(str)
    # streamer search: (query, results: list[dict]) / (message)
    search_ok = Signal(str, object)
    search_err = Signal(str)
    # a page of VODs: (generation, videos: list[dict], next cursor: str | None) / (generation, message)
    videos_ok = Signal(int, object, object)
    videos_err = Signal(int, str)
    # a thumbnail was fetched to disk: (generation, row id, file path)
    thumb = Signal(int, str, str)
    # timeline frames: (SourceInfo the frames belong to, frames)
    frames = Signal(object, object)
    # progress of a job or of the tools setup: (fraction 0..1, or a negative number for «unknown»; text)
    progress = Signal(float, str)
    # per-item progress for QueueModel on the GUI thread: (row id, fraction, text)
    item_progress = Signal(str, float, str)
    # a queue job starts: (number, how many in this run)
    job = Signal(int, int)
    # a queue item changed: (row id, status text, e.g. "running…", "done (3 files)")
    item = Signal(str, str)
    # tools status text for the Options tab (text)
    tools_info = Signal(str)
    # tools setup finished: (error text, "" when it went fine)
    tools_done = Signal(str)
    # saved-chat overlay finished: (output file path or "", error text or "")
    saved_chat_done = Signal(str, str)
    # the queue run is over
    queue_done = Signal()
    # update check finished: (UpdateInfo or None, error text or "")
    update_checked = Signal(object, str)
    # update installer download finished: (dest_path or "", error text or "")
    update_download_done = Signal(str, str)
