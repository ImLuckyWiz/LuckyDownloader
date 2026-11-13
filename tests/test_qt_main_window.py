"""The Qt main window (Phase 1: the frame only). Smoke tests with pytest-qt; no display needed (offscreen)."""

import types
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QProgressBar, QPushButton, QTabBar  # noqa: E402

import luckytwitch_qt  # noqa: E402
from core import paths, updates  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from qt_ui import dialogs  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui import theme  # noqa: E402
from qt_ui.bridge import Bridge  # noqa: E402
from qt_ui.tabs import OptionsTab, PlanTab, QueueTab, SearchTab  # noqa: E402


@pytest.fixture()
def themed(qtbot):
    app = QApplication.instance()
    saved = (app.palette(), app.font(), app.styleSheet())
    theme.apply_theme(app)
    yield app
    app.setStyleSheet(saved[2])
    app.setPalette(saved[0])
    app.setFont(saved[1])


@pytest.fixture()
def boxes(monkeypatch):
    calls = types.SimpleNamespace(log=[])
    for name in ("info", "warning", "error"):
        monkeypatch.setattr(dialogs, name, lambda parent, title, text, _n=name: calls.log.append((_n, title, text)))
    return calls


@pytest.fixture()
def win(qtbot, themed, boxes):
    w = mw.MainWindow(settings=dict(DEFAULTS), client=object())  # signed in: starts on the first tab
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_window_title_size_and_minimum(win):
    assert win.windowTitle() == "LuckyDownloader"
    assert mw.START_SIZE == (1040, 860)
    assert win.width() >= 950 and win.height() >= 560  # offscreen it is exactly 1040x860; a real screen may clamp it
    assert (win.minimumSize().width(), win.minimumSize().height()) == (950, 560)
    assert mw.START_SIZE == (1040, 860) and mw.MIN_SIZE == (950, 560)


def test_the_four_tabs_have_the_same_names_in_the_same_order(win):
    assert win.tab_names() == ["Browse", "Plan", "Options", "Queue & log"]
    assert [type(win.tabs.widget(i)) for i in range(4)] == [SearchTab, PlanTab, OptionsTab, QueueTab]
    # the ampersand shows as a real '&' (a single '&' would turn the next letter into a shortcut)
    assert win.tabs.tabText(3) == "Queue && log"


def test_all_four_tabs_are_populated(win):
    for i in range(4):  # Queue & log (Phase 3), Search (Phase 4), Options (Phase 5), Plan (Phase 6)
        assert win.tabs.widget(i).findChildren(QLabel) != []


def test_top_bar_texts_and_widgets(win):
    labels = [l.text() for l in win.findChildren(QLabel)]
    assert "VOD URL or ID:" in labels
    assert win.info_btn.text() == "Get info" and win.info_btn.property("variant") == "accent"
    assert win.api_btn.text() == "Twitch API…" and win.api_btn.property("variant") is None
    assert isinstance(win.vod_entry, QLineEdit) and win.vod_entry.text() == ""
    assert win.info_label.text() == "No VOD loaded." and win.info_label.property("role") == "muted"


def test_bottom_bar_has_a_progress_bar_and_the_ready_status(win):
    assert isinstance(win.progress, QProgressBar)
    assert (win.progress.minimum(), win.progress.maximum(), win.progress.value()) == (0, 100, 0)
    assert win.status_label.text() == "Ready. Paste a VOD URL or ID and press «Get info»."
    win.set_status("something else")
    assert win.status_label.text() == "something else"
    # always visible: below the tabs, whatever tab is open
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        assert win.progress.isVisible() and win.status_label.isVisible()
        assert win.status_label.y() > win.tabs.y()


def test_starts_on_the_plan_tab_without_a_twitch_client_and_on_search_with_one(qtbot, themed):
    no_client = mw.MainWindow(client=None)
    qtbot.addWidget(no_client)
    assert no_client.tabs.currentWidget() is no_client.tab_plan
    signed_in = mw.MainWindow(client=object())
    qtbot.addWidget(signed_in)
    assert signed_in.tabs.currentWidget() is signed_in.tab_search


def test_the_buttons_and_enter_call_the_stub_handlers(qtbot, themed, monkeypatch):
    calls = []
    monkeypatch.setattr(mw.MainWindow, "on_get_info", lambda self: calls.append("get_info"))
    monkeypatch.setattr(mw.MainWindow, "ask_credentials", lambda self: calls.append("credentials"))
    w = mw.MainWindow(client=object())
    qtbot.addWidget(w)
    w.show()
    w.info_btn.click()
    w.api_btn.click()
    qtbot.keyClick(w.vod_entry, qtbot_key("Return"))
    assert calls == ["get_info", "credentials", "get_info"]


def qtbot_key(name):
    from PySide6.QtCore import Qt

    return getattr(Qt.Key, f"Key_{name}")


def test_the_stub_handlers_do_nothing_and_do_not_raise(win):
    before = (win.status_label.text(), win.info_label.text(), win.tabs.currentIndex())
    win.on_get_info()  # the Twitch API dialog (the other stub of Phase 1) was built in Phase 4
    assert (win.status_label.text(), win.info_label.text(), win.tabs.currentIndex()) == before


def test_keyboard_order_is_entry_then_get_info_then_twitch_api_then_the_tabs(win):
    chain, w = [], win.vod_entry
    for _ in range(12):  # follow the focus chain a few steps, keeping only the stops we care about
        if w in (win.vod_entry, win.info_btn, win.api_btn) or isinstance(w, QTabBar):
            chain.append(w)
        w = w.nextInFocusChain()
    assert chain[:4] == [win.vod_entry, win.info_btn, win.api_btn, win.tabs.tabBar()]


def test_the_window_can_be_shrunk_to_the_minimum_without_hiding_the_bottom_bar(win):
    win.resize(950, 560)
    QApplication.processEvents()
    assert win.size().width() >= 950 and win.size().height() >= 560
    assert win.status_label.geometry().bottom() <= win.centralWidget().height()
    assert win.progress.isVisible()


def test_the_window_makes_its_own_bridge_or_uses_the_one_it_is_given(qtbot, themed):
    own = mw.MainWindow()
    qtbot.addWidget(own)
    assert isinstance(own.bridge, Bridge)
    bridge = Bridge()
    given = mw.MainWindow(bridge=bridge)
    qtbot.addWidget(given)
    assert given.bridge is bridge


# ------------------------------------------------------------------ the entry point
def test_main_builds_the_window_from_the_saved_settings_and_saves_them_on_close(qtbot, themed, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "SETTINGS_PATH", tmp_path / "data" / "luckytwitch_settings.json")
    monkeypatch.setattr(paths, "CONFIG_PATH", tmp_path / "data" / "config.json")
    app = QApplication.instance()
    made = []
    real_init = mw.MainWindow.__init__

    def spy(self, *a, **k):
        real_init(self, *a, **k)
        made.append((self, k))

    class FakeApp:  # main() builds its own QApplication and runs its loop: hand it the test one, with no loop
        def __new__(cls, argv):
            return app

    monkeypatch.setattr(luckytwitch_qt, "LuckyApplication", FakeApp)
    monkeypatch.setattr(type(app), "exec", lambda self: 0)
    monkeypatch.setattr(mw.MainWindow, "__init__", spy)
    tools = []
    monkeypatch.setattr(mw.MainWindow, "start_tools_setup", lambda self, force=False: tools.append(force))  # nothing real runs
    assert luckytwitch_qt.main(["luckytwitch_qt.py"]) == 0
    window, kwargs = made[0]
    qtbot.addWidget(window)
    assert tools == [False]  # Phase 5: the tools are prepared in the background right after the window opens
    assert kwargs["settings"] == DEFAULTS and kwargs["client"] is None
    assert (tmp_path / "data").is_dir()  # the data folder is created
    assert not paths.SETTINGS_PATH.exists()  # nothing is written until the window closes
    window.close()
    assert paths.SETTINGS_PATH.exists()  # Phase 3: saved on close, same file and keys as the tkinter app

def test_extract_channel_input_and_get_info_auto_search(win, monkeypatch):
    searches = []
    monkeypatch.setattr(win.tab_search, "on_search", lambda: searches.append(win.tab_search.search_edit.text()))

    # Switch to Plan tab first
    win.show_plan_tab()
    assert win.tabs.currentIndex() == 1

    # Enter a streamer name into VOD bar and click Get info
    win.vod_entry.setText("illojuan")
    win.on_get_info()

    # Automatically switches to Search tab, populates search input, and starts search
    assert win.tabs.currentIndex() == 0
    assert win.tab_search.search_edit.text() == "illojuan"
    assert searches == ["illojuan"]


def test_extract_channel_input_handles_urls_and_handles():
    from qt_ui.main_window import extract_channel_input
    assert extract_channel_input("illojuan") == "illojuan"
    assert extract_channel_input("@illojuan") == "illojuan"
    assert extract_channel_input("https://www.twitch.tv/illojuan") == "illojuan"
    assert extract_channel_input("twitch.tv/illojuan") == "illojuan"
    assert extract_channel_input("https://twitch.tv/illojuan?test=1") == "illojuan"
    assert extract_channel_input("2281234567") is None
    assert extract_channel_input("https://www.twitch.tv/videos/2281234567") is None


def test_is_valid_url():
    from qt_ui.main_window import is_valid_url
    assert is_valid_url("https://www.twitch.tv/videos/123456789")
    assert is_valid_url("twitch.tv/videos/123456789")
    assert is_valid_url("123456789")
    assert is_valid_url("https://youtu.be/xyz")
    assert is_valid_url("luckytwitch://videos/12345")
    assert not is_valid_url("downloading part 1/1: 10%\ndownload complete")
    assert not is_valid_url("some words not a url")
    assert not is_valid_url("")


def test_on_get_info_with_invalid_input_shows_warning(win, boxes):
    win.vod_entry.setText("Downloading part 1/1: 10% · 63 MiB")
    win.on_get_info()

    assert not win._info_busy
    assert any("Please enter a valid video URL" in text for _n, _t, text in boxes.log)
    assert "Please enter a valid video URL" in win.status_label.text()


def test_drop_event_with_multiline_log_shows_warning_and_does_not_fetch(win, boxes):
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setText("ality: 480p\n[20:09:06] Downloading part 1/1: 2% · 15 MiB\n[20:09:23] Downloading part 1/1: 10% · 63 MiB")
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.dropEvent(event)

    assert win.vod_entry.text() == ""
    assert not win._info_busy
    assert any("The dropped text is not a valid video URL" in text for _n, _t, text in boxes.log)


def test_main_window_update_check_startup_guards(win, monkeypatch):
    started = []
    monkeypatch.setattr(win.update_check_runner, "start", lambda force=False: started.append(force))

    # Guard 1: setting turned off
    win.settings["check_app_updates"] = False
    monkeypatch.setattr(paths, "BUNDLED_VERSION", "v2.2.0")
    win.start_update_check(manual=False)
    assert len(started) == 0

    # Guard 2: dev build (no bundled version)
    win.settings["check_app_updates"] = True
    monkeypatch.setattr(paths, "BUNDLED_VERSION", "")
    win.start_update_check(manual=False)
    assert len(started) == 0

    # Manual check overrides dev build
    win.start_update_check(manual=True)
    assert len(started) == 1
    assert started[0] is True


def test_main_window_on_update_checked_flows(win, monkeypatch, tmp_path):
    state_file = tmp_path / "luckytwitch_update.json"
    monkeypatch.setattr(paths, "UPDATE_STATE_PATH", state_file)
    monkeypatch.setattr(paths, "BUNDLED_VERSION", "v2.2.0")

    info = updates.UpdateInfo(
        tag="v2.3.0",
        notes="Notes",
        page_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/v2.3.0",
    )

    # 1. Update found (automatic) -> pill shown, toast shown
    toast_calls = []
    from qt_ui import notify
    monkeypatch.setattr(notify, "info", lambda parent, title, text, action=None, duration_ms=0: toast_calls.append((title, text, action)))

    win.on_update_checked(info, "")
    assert win.update_pill.isVisible()
    assert "v2.3.0" in win.update_pill.text()
    assert len(toast_calls) == 1
    assert "v2.3.0" in toast_calls[0][1]

    # Clicking the pill opens dialog
    dlg_opened = []
    monkeypatch.setattr(win, "open_update_dialog", lambda inf=None: dlg_opened.append(inf))
    win.update_pill.click()
    assert len(dlg_opened) == 1

    # 2. Skipped version -> automatic check hides pill and suppresses toast
    state = updates.load_state()
    state["skipped_tag"] = "v2.3.0"
    updates.save_state(state)
    toast_calls.clear()

    win.on_update_checked(info, "")
    assert not win.update_pill.isVisible()
    assert len(toast_calls) == 0

    # 3. Up to date -> pill hidden
    win.on_update_checked(None, "")
    assert not win.update_pill.isVisible()



def test_close_event_cancels_runner_directly(qtbot, monkeypatch):
    from unittest.mock import MagicMock
    from PySide6.QtGui import QCloseEvent
    from qt_ui.main_window import MainWindow

    monkeypatch.setattr("qt_ui.main_window.dialogs.ask_yes_no", lambda *a, **k: True)
    win = mw.MainWindow(settings=dict(DEFAULTS), client=object())
    qtbot.addWidget(win)

    cancelled = []
    fake_runner = MagicMock()
    fake_runner.is_running.side_effect = [True, False]
    fake_runner.cancel = lambda: cancelled.append(True)
    fake_runner.ctx = None
    win.tab_queue.runner = fake_runner

    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted()
    assert cancelled == [True]


def test_vod_with_muted_audio_adds_to_queue_and_starts(win, monkeypatch):
    from core.source_info import SourceInfo
    info = SourceInfo(
        url="https://www.twitch.tv/videos/2905959676",
        id="2905959676",
        title="Stream with muted sections",
        uploader="Streamer",
        duration=3600.0,
        date="2026-11-04",
        muted=[(100.0, 200.0), (1500.0, 1800.0)],
    )

    # 1. on_info_ok should format muted duration without tuple attribute errors
    win.on_info_ok(info, [], False, "")
    assert "2 muted (0:06:40)" in win.vod_strip.meta_label.text()

    # 2. add_to_queue(start=False) should serialize job and enqueue without error
    win.add_to_queue(start=False)
    assert len(win.tab_queue.items) == 1
    assert win.tab_queue.items[0].job.source.muted == [(100.0, 200.0), (1500.0, 1800.0)]

    # 3. add_to_queue(start=True) should succeed and trigger runner
    started = []
    monkeypatch.setattr(win.tab_queue, "start_queue", lambda: started.append(True))
    win.add_to_queue(start=True)
    assert len(win.tab_queue.items) == 2
    assert started == [True]


def test_save_ui_state_preserves_queue_and_layout_fields(qtbot, tmp_path, monkeypatch):
    """G-01: _save_ui_state() preserves log_open, splitter_sizes, max_concurrent_jobs, and rate_limit."""
    import core.paths as paths
    from core.ui_state import UIState, load_ui_state, save_ui_state

    ui_path = tmp_path / "luckytwitch_ui.json"
    monkeypatch.setattr(paths, "UI_STATE_PATH", ui_path)
    save_ui_state(
        UIState(
            log_open=True,
            splitter_sizes=[320, 180],
            max_concurrent_jobs=3,
            rate_limit="5M",
            has_completed_onboarding=True,
        ),
        path=ui_path,
    )

    win = mw.MainWindow(settings=dict(DEFAULTS), client=object())
    qtbot.addWidget(win)
    win.tab_queue.max_concurrent_jobs = 4
    win.tab_queue.rate_limit = "10M"
    win._save_ui_state()

    loaded = load_ui_state(path=ui_path)
    assert loaded.log_open is True
    assert loaded.splitter_sizes == [320, 180]
    assert loaded.max_concurrent_jobs == 4
    assert loaded.rate_limit == "10M"


def test_vod_strip_uses_date_and_twitch_vod_id_and_about_wired(qtbot):
    from core.source_info import SourceInfo
    from qt_ui.main_window import MainWindow

    win = MainWindow(settings=dict(DEFAULTS), client=None)
    qtbot.addWidget(win)
    src = SourceInfo(
        url="https://www.twitch.tv/videos/555666",
        id="555666",
        title="Speedrun Day 1",
        uploader="Runner",
        duration=3600.0,
        date="2026-11-10",
        twitch_vod_id="555666",
    )
    win.vod_strip.set_vod(src)
    assert "2026-11-10" in win.vod_strip.meta_label.text()
    assert hasattr(win.rail, "about_btn")
    assert hasattr(win.tab_options, "about_btn")
    assert hasattr(win.tab_options, "clear_data_btn")
    assert "save_history" in win.tab_options.toggles
    win.vod_strip.clear()
    assert win.vod_strip._expected_thumb_url == ""
    win.close()


def test_enqueue_dropped_urls_adds_jobs_to_queue(qtbot, monkeypatch):
    import core.source_info as source_info
    from core.source_info import SourceInfo
    from qt_ui.main_window import MainWindow

    fake_src = SourceInfo(
        url="https://www.twitch.tv/videos/777888",
        id="777888",
        title="Dropped VOD",
        uploader="StreamerX",
        duration=1200.0,
        date="2026-11-11",
        twitch_vod_id="777888",
    )
    monkeypatch.setattr(source_info, "get_source_info", lambda url, **kw: fake_src)

    win = MainWindow(settings=dict(DEFAULTS), client=None)
    qtbot.addWidget(win)
    win.tab_queue.urls_dropped.emit(["https://www.twitch.tv/videos/777888"])
    qtbot.waitUntil(lambda: len(win.tab_queue.items) == 1, timeout=3000)
    assert win.tab_queue.items[0].label == "StreamerX · Dropped VOD"
    assert win.tab_queue.items[0].job.source.id == "777888"
    win.close()

