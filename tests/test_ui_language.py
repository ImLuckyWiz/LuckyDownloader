"""Tests for UI language selection, live retranslation, and persistence."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from core import paths
from core.i18n import get_language, set_language
from core.ui_state import UIState, load_ui_state, save_ui_state
from qt_ui.main_window import MainWindow


def test_ui_language_persistence_and_live_switch(qtbot, tmp_path, monkeypatch):
    test_ui_path = tmp_path / "luckytwitch_ui.json"
    monkeypatch.setattr(paths, "UI_STATE_PATH", test_ui_path)

    # 1. Start with saved language = 'es'
    st = UIState(language="es")
    save_ui_state(st, test_ui_path)

    win = MainWindow()
    qtbot.addWidget(win)

    assert get_language() == "es"
    assert win.tab_options.lang_combo.currentText() == "Español"
    assert win.command_bar.prompt_label.text() == "URL o ID del VOD:"
    assert win.command_bar.info_btn.text() == "Obtener información"
    assert win.tab_queue.start_btn.text() == "Iniciar cola"
    assert win.tabs.tabText(0) == "Explorar"
    assert win.tabs.tabText(3) == "Cola y registros"

    # 2. Live switch to English
    win.tab_options.lang_combo.setCurrentIndex(win.tab_options.lang_combo.findData("en"))
    assert get_language() == "en"

    saved_st = load_ui_state(test_ui_path)
    assert saved_st.language == "en"
    assert win.command_bar.prompt_label.text() == "VOD URL or ID:"
    assert win.command_bar.info_btn.text() == "Get info"
    assert win.tab_queue.start_btn.text() == "Start queue"
    assert win.tabs.tabText(0) == "Browse"
    assert win.tabs.tabText(3) == "Queue && log"

    # 3. Live switch back to Spanish
    win.tab_options.lang_combo.setCurrentIndex(win.tab_options.lang_combo.findData("es"))
    assert get_language() == "es"
    saved_st2 = load_ui_state(test_ui_path)
    assert saved_st2.language == "es"
    assert win.command_bar.prompt_label.text() == "URL o ID del VOD:"
    assert win.tab_queue.start_btn.text() == "Iniciar cola"
    assert win.tabs.tabText(0) == "Explorar"

    win.close()


def _window(qtbase, tmp_path, monkeypatch, language=None):
    ui_path = tmp_path / "luckytwitch_ui.json"
    monkeypatch.setattr(paths, "UI_STATE_PATH", ui_path)
    if language is not None:
        save_ui_state(UIState(language=language), ui_path)
    win = MainWindow()
    qtbase.addWidget(win)
    return win, ui_path


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    from qt_ui import i18n_qt

    i18n_qt.apply_language("en", announce=False)


def test_new_installs_follow_the_system_language(qtbot, tmp_path, monkeypatch):
    from qt_ui import i18n_qt

    monkeypatch.setattr(i18n_qt, "system_language", lambda: "es")
    win, ui_path = _window(qtbot, tmp_path, monkeypatch)  # nothing saved yet
    assert i18n_qt.current_setting() == "auto"
    assert get_language() == "es"
    assert win.tab_options.lang_combo.currentData() == "auto"
    assert win.tab_options.lang_combo.itemText(0) == "Automático (sistema)"
    assert win.tabs.tabText(0) == "Explorar"
    win.close()


def test_auto_setting_is_saved_and_follows_the_system(qtbot, tmp_path, monkeypatch):
    from qt_ui import i18n_qt

    monkeypatch.setattr(i18n_qt, "system_language", lambda: "en")
    win, ui_path = _window(qtbot, tmp_path, monkeypatch, language="es")
    assert get_language() == "es"
    combo = win.tab_options.lang_combo
    combo.setCurrentIndex(combo.findData("auto"))
    assert load_ui_state(ui_path).language == "auto"
    assert get_language() == "en"  # the system says English
    assert win.command_bar.info_btn.text() == "Get info"
    assert combo.itemText(0) == "Auto (system)"
    win.close()


def test_switching_needs_no_restart_and_shows_no_restart_notice(qtbot, tmp_path, monkeypatch):
    from qt_ui import notify

    shown = []
    monkeypatch.setattr(notify, "info", lambda *a, **k: shown.append(a))
    win, _ = _window(qtbot, tmp_path, monkeypatch, language="en")
    combo = win.tab_options.lang_combo
    combo.setCurrentIndex(combo.findData("es"))
    assert win.tabs.tabText(0) == "Explorar"
    assert shown == []


def test_save_keeps_the_setting_not_the_resolved_language(qtbot, tmp_path, monkeypatch):
    from qt_ui import i18n_qt

    monkeypatch.setattr(i18n_qt, "system_language", lambda: "es")
    win, ui_path = _window(qtbot, tmp_path, monkeypatch)
    win._save_ui_state()
    assert load_ui_state(ui_path).language == "auto"
    win.close()


def test_empty_vod_sentence_follows_the_language_without_hard_coded_text(qtbot, tmp_path, monkeypatch):
    win, _ = _window(qtbot, tmp_path, monkeypatch, language="es")
    assert win.info_label.text() == "Ningún VOD cargado."
    from qt_ui import i18n_qt

    i18n_qt.apply_language("en")
    assert win.info_label.text() == "No VOD loaded."
    win.info_label.setText("streamer · title · 1:00:00")  # a real VOD is shown: must not be touched
    i18n_qt.apply_language("es")
    assert win.info_label.text() == "streamer · title · 1:00:00"
    win.clear_vod()
    assert win.info_label.text() == "Ningún VOD cargado."
    win.close()


def test_language_bus_notifies_and_window_refreshes(qtbot, tmp_path, monkeypatch):
    from qt_ui import i18n_qt

    win, _ = _window(qtbot, tmp_path, monkeypatch, language="en")
    with qtbot.waitSignal(i18n_qt.language_bus().changed, timeout=1000) as blocker:
        i18n_qt.apply_language("es")
    assert blocker.args == ["es"]
    assert win.command_bar.prompt_label.text() == "URL o ID del VOD:"
    win.close()
