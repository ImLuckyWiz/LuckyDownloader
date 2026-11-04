"""Make the project root importable (luckytwitch_engine, luckytwitch_qt, qt_ui, core) from the tests.

The Qt tests run on Qt's offscreen platform (no display, same result on every machine); set QT_QPA_PLATFORM
yourself to run them on a real one.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _data_folder_in_tmp(request, tmp_path, monkeypatch):
    """The Qt window saves its settings and removes the heartbeat file when it closes (Phase 3): keep that away from
    the real data folder (the app folder when run from source). Only for the Qt test files (test_qt_*.py): the
    tests of ``core`` itself check the real paths. Tests that want their own paths patch them again."""
    if not request.module.__name__.rsplit(".", 1)[-1].startswith("test_qt_"):
        return
    try:
        from core import paths
    except ImportError:  # pragma: no cover
        return
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    for name, leaf in (("SETTINGS_PATH", "luckytwitch_settings.json"), ("RECENT_PATH", "luckytwitch_recent.json"),
                       ("RECENT_SEARCHES_PATH", "recent_searches.json"),
                       ("CONFIG_PATH", "config.json"), ("LINKS_DIR", "links"), ("BEAT_PATH", "running.beat"),
                       ("UI_STATE_PATH", "luckytwitch_ui.json"), ("UPDATE_STATE_PATH", "luckytwitch_update.json"),
                       ("HISTORY_PATH", "luckytwitch_history.json"), ("WATCHLIST_PATH", "luckytwitch_watchlist.json"),
                       ("QUEUE_STATE_PATH", "queue_state.json"), ("QUEUE_STATE_FILE", "queue_state.json")):
        monkeypatch.setattr(paths, name, data_dir / leaf)
    try:
        import core.history
        monkeypatch.setattr(core.history, "HISTORY_PATH", data_dir / "luckytwitch_history.json")
    except Exception:
        pass
    try:
        import core.watchlist
        monkeypatch.setattr(core.watchlist, "WATCHLIST_PATH", data_dir / "luckytwitch_watchlist.json")
    except Exception:
        pass
    try:
        from qt_ui.motion import Motion

        Motion.set_enabled(False)
    except ImportError:  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def _collect_garbage_at_a_known_moment(request):
    """Run Python's garbage collector right after each Qt test, once pytest-qt has closed and deleted its widgets.

    A window or tab that sits in a reference cycle is cleaned up by the collector, which first empties the Python
    objects of its children; if Qt has not deleted the C++ widgets yet, it then calls virtual methods (a model's
    ``rowCount``, an event filter) on those emptied objects and an error shows up in whatever test happens to be
    running. Collecting here makes that moment the same on every run and every machine.
    """
    yield
    if not request.module.__name__.rsplit(".", 1)[-1].startswith("test_qt_"):
        return
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover
        pass
    import gc

    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    gc.collect()


def pytest_sessionfinish(session, exitstatus):
    try:
        import gc
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        try:
            from qt_ui.i18n_bus import language_bus
            language_bus().changed.disconnect()
        except Exception:
            pass

        app = QApplication.instance()
        if app is not None:
            app.closeAllWindows()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        gc.collect()
    except Exception:
        pass


def pytest_unconfigure(config):
    """On Linux and macOS headless runners, PySide6 offscreen teardown can trigger a SIGSEGV
    during Python interpreter shutdown (Py_FinalizeEx) after all tests have completely passed.
    Calling os._exit(0) when all tests passed with 0 failures/errors bypasses this C++ teardown crash.
    """
    tr = config.pluginmanager.get_plugin("terminalreporter")
    if tr:
        failed = len(tr.stats.get("failed", []))
        errors = len(tr.stats.get("error", []))
        passed = len(tr.stats.get("passed", []))
        session = getattr(tr, "_session", None)
        exitstatus = getattr(session, "exitstatus", None)
        if failed == 0 and errors == 0 and passed > 0 and (exitstatus == 0 or exitstatus is None):
            sys.stdout.flush()
            sys.stderr.flush()
            if sys.platform == "win32":
                import ctypes
                k32 = ctypes.windll.kernel32
                k32.GetCurrentProcess.restype = ctypes.c_void_p
                k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                k32.TerminateProcess(k32.GetCurrentProcess(), 0)
            os._exit(0)
