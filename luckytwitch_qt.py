"""LuckyTwitch Downloader, PySide6 version (legacy compatibility facade for luckydownloader_qt.py).
Kept for backward-compatible test monkeypatching. (default entry point from v2.0.0; packaged by build_windows.bat and
build_mac.sh).

    python luckytwitch_qt.py

The legacy tkinter entry point (luckytwitch_downloader.py) stays in the repository for one release cycle before
removal. Both use the same data folder (except packaged pre-release builds with a hyphen in the version, which use
LuckyTwitch-beta); the settings are saved when the window closes. The tools (yt-dlp, ffmpeg) are prepared in the
background right after the window opens. A ``luckytwitch://`` link passed on the command line is handed to an
already-open window when one is running, or opened here after start-up; on macOS, ``QFileOpenEvent`` delivers links
to the running app.
"""

from __future__ import annotations

import os
import signal
import sys

if "__compiled__" in globals() or hasattr(sys.modules.get("__main__"), "__compiled__"):
    sys.frozen = True

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import QApplication

import weblink
from core import paths
from core.config import make_client
from core.settings import load_settings
from qt_ui.main_window import MainWindow
from qt_ui.theme import apply_theme, set_app_icon


class LuckyApplication(QApplication):
    """``QApplication`` that also turns macOS ``QFileOpenEvent`` URL events into ``link_opened(str)`` (replaces
    tkinter's ``::tk::mac::LaunchURL``)."""

    link_opened = Signal(str)

    def event(self, ev) -> bool:  # noqa: N802 (Qt name)
        if ev.type() == QEvent.Type.FileOpen:
            url = ev.url().toString() if hasattr(ev, "url") else ""
            if not url and hasattr(ev, "file"):
                url = ev.file()
            if url:
                self.link_opened.emit(url)
                return True
        return super().event(ev)


def i18n_selftest() -> int:
    """``--i18n-selftest``: prove that a (packaged) build finds its Spanish catalog and Qt's Spanish strings.

    The build workflow runs it against the frozen binary: a build that forgot to bundle ``locale/`` would otherwise
    ship silently in English only. Prints ``i18n ok`` and returns 0, or says what is missing and returns 1.
    """
    from core import i18n
    from qt_ui import i18n_qt

    problems = []
    i18n.set_language("es")
    if i18n.t("Search") != "Buscar":
        problems.append(f"Spanish catalog not found in {i18n.LOCALE_DIR}")
    if any(i18n_qt.load_qt_translator(name, "es") is None for name in i18n_qt.QT_CATALOGS):
        problems.append(f"Qt Spanish translations not found in {i18n_qt._qt_translations_dirs()}")
    if problems:
        print("i18n FAILED: " + "; ".join(problems))
        return 1
    print("i18n ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--help" in argv or "-h" in argv:
        print("LuckyDownloader - VOD & Video Downloader & Cutter")
        print("Usage: LuckyDownloader [options] [luckytwitch://...]")
        print("Options:")
        print("  --help, -h       Show this help message and exit")
        print("  --version        Show version and exit")
        print("  --welcome        Open first-run welcome dialog")
        return 0

    if "--version" in argv:
        ver = paths.BUNDLED_VERSION or "dev build"
        print(f"LuckyDownloader {ver}")
        return 0

    paths.ensure_data_dir()
    from core.diagnostics import setup_file_logging
    setup_file_logging()
    from core.ui_state import load_ui_state
    from core.i18n import LANG_AUTO, resolve_language, set_language
    from qt_ui import i18n_qt
    _ui_st = load_ui_state()
    _lang_setting = getattr(_ui_st, "language", None) or LANG_AUTO
    if "--lang" in argv:
        idx = argv.index("--lang")
        if idx + 1 < len(argv):
            _lang_setting = argv[idx + 1]
    elif os.environ.get("LUCKYDOWNLOADER_LANG") or os.environ.get("LUCKYTWITCH_LANG"):
        _lang_setting = (os.environ.get("LUCKYDOWNLOADER_LANG") or os.environ.get("LUCKYTWITCH_LANG") or "").strip()
    set_language(resolve_language(_lang_setting, i18n_qt.system_language()))  # early: messages before the window exists
    if "--i18n-selftest" in argv:
        return i18n_selftest()
    link = weblink.find_link(argv[1:])  # started by a luckytwitch:// link?
    if link and weblink.hand_off(link, paths.LINKS_DIR, paths.BEAT_PATH):
        return 0  # the window that is already open took it
    app = LuckyApplication(argv)
    app.setApplicationName("LuckyDownloader")
    i18n_qt.apply_language(_lang_setting, announce=False)  # also installs Qt's own translations (needs the app object)
    apply_theme(app)
    set_app_icon(app)
    show_welcome = True if "--welcome" in argv else None
    window = MainWindow(settings=load_settings(), client=make_client(), show_welcome=show_welcome)
    if hasattr(app, "link_opened"):
        app.link_opened.connect(window.open_link)
    window.show()
    window.start_tools_setup()
    QTimer.singleShot(3000, window.start_update_check)
    if link:
        QTimer.singleShot(300, lambda: window.open_link(link))

    # Allow closing cleanly via Ctrl+C from a terminal without spamming tracebacks
    def _sigint_handler(*_args):
        window.close()
        app.quit()

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except (ValueError, AttributeError):
        pass

    def _excepthook(exc_type, exc_val, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            window.close()
            app.quit()
            return
        sys.__excepthook__(exc_type, exc_val, tb)

    sys.excepthook = _excepthook

    # Wake Python interpreter periodically so SIGINT / Ctrl+C is caught during Qt's event loop
    sig_timer = QTimer(window)
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(200)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
