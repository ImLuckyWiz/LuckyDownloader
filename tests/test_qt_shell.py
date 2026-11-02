"""Tests for Phase 9a (motion & button spike) and Phase 9b (The Shell: NavRail, PageStack,
CommandBar, VodStrip, Twitch Account Chip, Compact Status Bar, Keyboard Layer, UI State,
and Plan Onboarding Card).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from types import SimpleNamespace  # noqa: E402
from PySide6.QtCore import QMimeData, Qt, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import luckytwitch_engine as eng  # noqa: E402
from core import paths  # noqa: E402
from core.palette import ACCENT, BG3  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from core.ui_state import UIState, load_ui_state, save_ui_state  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui import notify, theme  # noqa: E402
from qt_ui.motion import ButtonHoverAnimator, Motion  # noqa: E402
from qt_ui.shell import NavRail, ShortcutsDialog  # noqa: E402
from qt_ui.widgets import Collapsible  # noqa: E402

SAMPLE_SOURCE = eng.SourceInfo(
    url="https://www.twitch.tv/videos/987654321",
    id="v987654321",
    title="Speedrun Any% PB Attempt",
    uploader="RunnerGuy",
    duration=5400.0,
    date="2026-10-20",
    twitch_vod_id="987654321",
)


@pytest.fixture(autouse=True)
def _themed(qtbot):
    app = QApplication.instance()
    saved = (app.palette(), app.font(), app.styleSheet())
    theme.apply_theme(app)
    notify.calls.clear()
    yield
    notify.calls.clear()
    app.setStyleSheet(saved[2])
    app.setPalette(saved[0])
    app.setFont(saved[1])


@pytest.fixture()
def win(qtbot):
    w = mw.MainWindow(settings=dict(DEFAULTS), client=None)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


# ------------------------------------------------------------------ 9a: Motion & Button Hover Spike
def test_motion_switch_and_duration_tokens():
    Motion.set_enabled(False)
    assert not Motion.enabled()
    assert Motion.duration(Motion.NORMAL_MS) == 0
    Motion.set_enabled(True)
    assert Motion.enabled()
    assert Motion.duration(Motion.FAST_MS) == 120
    assert Motion.duration(Motion.NORMAL_MS) == 180
    assert Motion.duration(Motion.SLIDE_MS) == 150
    Motion.set_enabled(False)


def test_button_hover_animator_interpolates_colours(qtbot):
    btn = QPushButton("Probe")
    qtbot.addWidget(btn)
    btn.show()
    qtbot.waitExposed(btn)

    anim = ButtonHoverAnimator(btn, BG3, ACCENT, duration_ms=40)
    assert anim.progress == 0.0 and anim.current_color.name() == BG3

    # Instant when Motion is disabled
    Motion.set_enabled(False)
    anim.set_hovered(True)
    assert anim.progress == 1.0 and anim.current_color.name() == ACCENT
    anim.set_hovered(False)
    assert anim.progress == 0.0 and anim.current_color.name() == BG3

    # Animated when Motion is enabled
    Motion.set_enabled(True)
    try:
        anim.set_hovered(True)
        qtbot.waitUntil(lambda: anim.progress == 1.0, timeout=1000)
        assert anim.current_color.name() == ACCENT
    finally:
        Motion.set_enabled(False)


def test_collapsible_animates_when_motion_enabled(qtbot):
    adv = Collapsible("Advanced")
    adv.add_row("Setting", "Hint")
    qtbot.addWidget(adv)
    adv.show()
    qtbot.waitExposed(adv)

    Motion.set_enabled(True)
    try:
        adv.set_opened(True)
        assert adv.opened and adv.body.isVisible()
        qtbot.waitUntil(lambda: getattr(adv.body, "_height_anim", None) is None, timeout=1000)
        adv.set_opened(False)
        qtbot.waitUntil(lambda: not adv.body.isVisible(), timeout=1000)
    finally:
        Motion.set_enabled(False)


# ------------------------------------------------------------------ 9b B1: NavRail & PageStack
def test_nav_rail_switches_pages_and_expands_and_collapses(win, qtbot):
    rail = win.rail
    assert isinstance(rail, NavRail)
    assert not rail.expanded and rail.width() == NavRail.COLLAPSED_WIDTH
    assert win.tabs.currentIndex() == 1  # starts on Plan when client is None
    assert rail.buttons[1].property("selected") is True

    # Click Search on the rail
    qtbot.mouseClick(rail.buttons[0], Qt.MouseButton.LeftButton)
    assert win.tabs.currentIndex() == 0 and win.tabs.currentWidget() is win.tab_search
    assert rail.buttons[0].property("selected") is True
    assert rail.buttons[1].property("selected") is False

    # Expand and collapse rail
    qtbot.mouseClick(rail.toggle_btn, Qt.MouseButton.LeftButton)
    assert rail.expanded and rail.width() == NavRail.EXPANDED_WIDTH
    assert "Browse" in rail.buttons[0].text()
    assert "Options" in rail.buttons[2].text()

    qtbot.mouseClick(rail.toggle_btn, Qt.MouseButton.LeftButton)
    assert not rail.expanded and rail.width() == NavRail.COLLAPSED_WIDTH


def test_nav_rail_up_and_down_arrow_keys_step_visually(win, qtbot):
    rail = win.rail
    rail.set_current_index(0)
    rail.buttons[0].setFocus()
    # Visual order is Search (0) -> Plan (1) -> Queue & log (3) -> Options (2)
    qtbot.keyClick(rail.buttons[0], Qt.Key.Key_Down)
    assert win.tabs.currentIndex() == 1
    qtbot.keyClick(rail.buttons[1], Qt.Key.Key_Down)
    assert win.tabs.currentIndex() == 3
    qtbot.keyClick(rail.buttons[3], Qt.Key.Key_Down)
    assert win.tabs.currentIndex() == 2
    qtbot.keyClick(rail.buttons[2], Qt.Key.Key_Up)
    assert win.tabs.currentIndex() == 3


def test_nav_rail_badges_for_loaded_vod_and_queue_count(win):
    assert not win.rail.vod_loaded and win.rail.queue_count == 0
    win.on_info_ok(SAMPLE_SOURCE, [], True, "")
    assert win.rail.vod_loaded and "\u25cf" in win.rail.buttons[1].text()

    win.tab_plan.set_cut_text("0:00:00 - 0:10:00")
    win.add_to_queue(start=False)
    assert win.rail.queue_count == 1
    assert "1" in win.rail.buttons[3].text()

    win.clear_vod()
    assert not win.rail.vod_loaded and "\u25cf" not in win.rail.buttons[1].text()


# ------------------------------------------------------------------ 9b B2, B3, B4: Command Bar, VodStrip & Account
def test_command_bar_paste_and_clear_action_button(win, qtbot):
    clip = QApplication.clipboard()
    clip.setText("https://www.twitch.tv/videos/555444333")
    assert win.vod_entry.text() == ""
    assert win.vod_action_btn.text() == "Paste"

    qtbot.mouseClick(win.vod_action_btn, Qt.MouseButton.LeftButton)
    assert win.vod_entry.text() == "https://www.twitch.tv/videos/555444333"
    assert win.vod_action_btn.text() == "\u2715"

    qtbot.mouseClick(win.vod_action_btn, Qt.MouseButton.LeftButton)
    assert win.vod_entry.text() == ""
    assert win.vod_action_btn.text() == "Paste"


def test_vod_strip_shows_on_load_switches_to_plan_and_clears(win, qtbot):
    assert not win.vod_strip.isVisible()
    win.on_info_ok(SAMPLE_SOURCE, [{"id": "c1", "vod_offset": 60, "duration": 10}], True, "")
    assert win.vod_strip.isVisible()
    assert win.vod_strip.title_label.text() == "Speedrun Any% PB Attempt"
    assert "RunnerGuy" in win.vod_strip.meta_label.text()
    assert "1 clips" in win.vod_strip.meta_label.text()

    # Switch away from Plan, then click the VOD strip to jump back to Plan
    win.tabs.setCurrentIndex(2)
    assert win.tabs.currentWidget() is win.tab_options
    qtbot.mouseClick(win.vod_strip, Qt.MouseButton.LeftButton)
    assert win.tabs.currentWidget() is win.tab_plan

    # Clear button resets the VOD and hides the strip
    qtbot.mouseClick(win.vod_strip.clear_btn, Qt.MouseButton.LeftButton)
    assert not win.vod_strip.isVisible()
    assert win.source is None
    assert win.info_label.text() == "No VOD loaded."


def test_account_status_follows_client_property(win):
    assert not win.command_bar.signed_in
    assert win.api_btn.property("signed_in") == "false"
    assert win.command_bar.account_dot.text() == "\u25cb"

    win.client = object()
    assert win.command_bar.signed_in
    assert win.api_btn.property("signed_in") == "true"
    assert win.command_bar.account_dot.text() == "\u25cf"

    win.client = None
    assert not win.command_bar.signed_in
    assert win.api_btn.property("signed_in") == "false"


def test_drag_and_drop_loads_vod_url(win, monkeypatch):
    fetched = []
    monkeypatch.setattr(win, "on_get_info", lambda: fetched.append(win.vod_entry.text()))

    mime = QMimeData()
    mime.setUrls([QUrl("https://www.twitch.tv/videos/11223344")])
    accepted = []
    fake_event = SimpleNamespace(
        mimeData=lambda: mime,
        acceptProposedAction=lambda: accepted.append(True),
    )
    win.dragEnterEvent(fake_event)
    assert accepted == [True]

    win.dropEvent(fake_event)
    assert fetched == ["https://www.twitch.tv/videos/11223344"]


def test_clipboard_vod_detection_shows_offer_toast_once(win, monkeypatch):
    fetched = []
    monkeypatch.setattr(win, "on_get_info", lambda: fetched.append(win.vod_entry.text()))
    QApplication.clipboard().setText("Check this out https://www.twitch.tv/videos/777888999 !")

    assert win.check_clipboard_for_vod() is True
    assert notify.calls[-1][:2] == ("info", "Twitch VOD in clipboard")
    # Second check with same clipboard text does not spam another toast
    assert win.check_clipboard_for_vod() is False

    # Clicking the toast's "Load VOD" action populates vod_entry and triggers on_get_info
    toast = win._toast_host.toasts[-1]
    toast.action_btn.click()
    assert fetched == ["https://www.twitch.tv/videos/777888999"]


# ------------------------------------------------------------------ 9b B7: Compact Status Bar & Activity Pill
def test_activity_pill_shows_progress_and_jumps_to_queue(win, qtbot):
    assert not win.activity_pill.isVisible()
    win.on_job(1, 2)
    win.set_progress(0.45, "Downloading")
    assert win.activity_pill.isVisible()
    assert win.activity_pill.text() == "Job 1/2 \u00b7 45%"

    win.tabs.setCurrentWidget(win.tab_plan)
    qtbot.mouseClick(win.activity_pill, Qt.MouseButton.LeftButton)
    assert win.tabs.currentWidget() is win.tab_queue

    win.on_queue_done()
    assert not win.activity_pill.isVisible()


# ------------------------------------------------------------------ 9b B8: Keyboard Layer
def test_keyboard_shortcuts_switch_pages_focus_vod_and_open_f1(win):
    win.vod_entry.setText("some text")
    win.shortcuts["Ctrl+L"].activated.emit()
    assert win.vod_entry.selectedText() == "some text"

    win.shortcuts["Ctrl+1"].activated.emit()
    assert win.tabs.currentIndex() == 0
    win.shortcuts["Ctrl+3"].activated.emit()
    assert win.tabs.currentIndex() == 2
    win.shortcuts["Ctrl+4"].activated.emit()
    assert win.tabs.currentIndex() == 3
    win.shortcuts["Ctrl+2"].activated.emit()
    assert win.tabs.currentIndex() == 1
    win.shortcuts["Ctrl+,"].activated.emit()
    assert win.tabs.currentIndex() == 2

    dlg = win.show_shortcuts()
    assert isinstance(dlg, ShortcutsDialog) and dlg.isVisible()
    dlg.close()


def test_plan_keyboard_shortcuts_enqueue_and_start(win, monkeypatch):
    win.on_info_ok(SAMPLE_SOURCE, [], True, "")
    win.tab_plan.set_cut_text("0:00:00 - 0:05:00")
    win.tabs.setCurrentWidget(win.tab_plan)

    started = []
    monkeypatch.setattr(win.tab_queue, "start_queue", lambda: started.append(True))

    win.shortcuts["Ctrl+Shift+Return"].activated.emit()
    assert len(win.tab_queue.items) == 1 and started == []

    win.shortcuts["Ctrl+Return"].activated.emit()
    assert len(win.tab_queue.items) == 2 and started == [True]


# ------------------------------------------------------------------ 9b B9 & B10: UI State & Plan Onboarding
def test_ui_state_persists_rail_and_active_tab_across_restarts(qtbot):
    save_ui_state(UIState(window_w=1100, window_h=820, active_tab="Options", rail_expanded=True))
    w = mw.MainWindow(settings=dict(DEFAULTS), client=None)
    qtbot.addWidget(w)
    assert w.rail.expanded is True
    assert w.tabs.currentWidget() is w.tab_options
    assert w.width() == 1100 and w.height() == 820

    w.rail.set_expanded(False, animate=False)
    w.tabs.setCurrentWidget(w.tab_queue)
    w.close()

    saved = load_ui_state(paths.UI_STATE_PATH)
    assert saved.rail_expanded is False
    assert saved.active_tab == "Queue & log"


def test_plan_onboarding_card_hides_when_vod_loads_and_buttons_work(win, qtbot):
    plan = win.tab_plan
    assert plan.onboarding_card.isVisible()

    # "Search streamers" switches to Search tab
    qtbot.mouseClick(plan.onboard_search_btn, Qt.MouseButton.LeftButton)
    assert win.tabs.currentWidget() is win.tab_search
    win.tabs.setCurrentWidget(plan)

    # Loading a VOD hides the onboarding card; clearing brings it back
    win.on_info_ok(SAMPLE_SOURCE, [], True, "")
    assert not plan.onboarding_card.isVisible()
    win.clear_vod()
    assert plan.onboarding_card.isVisible()
