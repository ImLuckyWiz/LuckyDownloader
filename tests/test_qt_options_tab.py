"""The Qt Options tab (Phase 5): layout, that every setting is bound to the same key, the Advanced areas, the {token}
chips and live examples, the settings binder, the tools setup and the overlay of a saved chat.

Ports of tests/test_gui_options_tab.py (the tkinter file stays until cutover) plus checks for the binder.
Nothing is downloaded: the engine functions are replaced by fakes in ``qt_ui.background_jobs``; message boxes and file
dialogs are replaced too. Runs on Qt's offscreen platform.
"""

import json
import threading
import types
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import luckytwitch_engine as eng  # noqa: E402
from core import examples  # noqa: E402
from core.options import AUDIO_FORMAT_NAMES, QUALITY_NAMES, build_options  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from qt_ui import dialogs, theme  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui.tabs.options import SECTIONS, OptionsTab  # noqa: E402
from qt_ui.widgets import Collapsible, ComboBox, SpinBox, Toggle  # noqa: E402

# every setting the Options tab edits (the other five of the 38 belong to the Plan tab)
OPTIONS_KEYS = {
    "out_dir", "container", "threads", "strategy", "threshold", "name_template", "clean_title", "subfolders", "folder_template",
    "exact", "keep_full", "title_tpl", "pad_after", "gap_title", "sidecar", "premiere_xml", "premiere_plugin",
    "game_markers", "muted_markers", "clip_name_template", "clip_pad_before", "clip_pad_after", "chat", "chat_format",
    "chat_embed", "auto_update", "check_app_updates",
    "chat_render", "chat_render_mode", "chat_render_look", "chat_render_width", "chat_render_height",
    "chat_render_font_size", "chat_render_fps", "chat_render_smooth",
    "default_quality", "audio_format", "cookies_from_browser",
}
PLAN_KEYS = {"chapters", "min_views", "min_duration", "top_n", "pad_before"}
SWITCHES = {"exact", "keep_full", "clean_title", "subfolders", "premiere_plugin", "game_markers", "muted_markers", "premiere_xml",
            "sidecar", "chat", "chat_embed", "chat_render", "chat_render_smooth", "auto_update", "check_app_updates"}


# ------------------------------------------------------------------ fixtures and helpers
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
    """Every message box and file dialog the code opens. ``boxes.log`` has (kind, title, text); ``boxes.picked`` is
    what the file dialog returns ('' = cancelled), ``boxes.folder`` what the folder dialog returns, ``boxes.confirm``
    the answer of the OK/Cancel question; ``boxes.asked`` lists the start folders the dialogs were given."""
    calls = types.SimpleNamespace(log=[], picked="", folder="", confirm=True, asked=[])
    for name in ("info", "warning", "error"):
        monkeypatch.setattr(dialogs, name, lambda parent, title, text, _n=name: calls.log.append((_n, title, text)))
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda parent, title, text: True)
    monkeypatch.setattr(dialogs, "ask_ok_cancel",
                        lambda parent, title, text: calls.log.append(("confirm", title, text)) or calls.confirm)
    monkeypatch.setattr(dialogs, "open_file",
                        lambda parent, title, start="", name_filter="": calls.asked.append(start) or calls.picked)
    monkeypatch.setattr(dialogs, "choose_folder",
                        lambda parent, title, start="": calls.asked.append(start) or calls.folder)
    return calls


@pytest.fixture()
def tab(qtbot, themed, boxes):
    t = OptionsTab(dict(DEFAULTS))
    qtbot.addWidget(t)
    t.resize(1000, 700)
    t.show()
    qtbot.waitExposed(t)
    return t


@pytest.fixture()
def win(qtbot, themed, boxes):
    w = mw.MainWindow(settings=dict(DEFAULTS), client=object())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def control(tab, key):
    return tab.binder.controls[key]


def chip(tab, key, token):
    return next(b for b in tab.chip_rows[key].chips if b.text() == "{" + token + "}")


def example(tab, key):
    return tab.example_labels[key].text()


# ------------------------------------------------------------------ structure
def test_the_sidebar_has_the_eight_sections_and_starts_on_output(tab):
    assert [k for k, _ in SECTIONS] == ["output", "cuts", "chapters", "premiere", "chat", "clips", "interface", "tools"]
    assert [b.text() for b in tab.nav.buttons.values()] == [
        "Output", "Cuts", "Chapters", "Premiere Pro", "Chat", "Clips", "Interface", "Tools"]
    assert set(tab.nav.buttons) == set(tab.sections)
    assert tab.visible_sections() == ["output"] and tab.nav.current == "output"


def test_only_one_section_is_visible_at_a_time(tab):
    for key, _ in SECTIONS:
        tab.nav.select(key)
        assert tab.visible_sections() == [key]
        assert tab.nav.current == key
        assert tab.nav.buttons[key].property("selected") is True
        assert all(b.property("selected") is False for k, b in tab.nav.buttons.items() if k != key)


def test_switching_sections_scrolls_back_to_the_top(tab, qtbot):
    tab.resize(1000, 300)
    tab.nav.select("chat")
    tab.advanced["chat"].set_opened(True)
    bar = tab.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    tab.nav.select("clips")
    assert bar.value() == 0


def test_arrow_keys_move_through_the_sidebar(tab):
    nav = tab.nav
    nav.step("output", 1)
    assert nav.current == "cuts"
    nav.step("cuts", -1)
    assert nav.current == "output"
    nav.step("output", -1)  # nothing above the first entry
    assert nav.current == "output"
    nav.step("tools", 1)  # nothing below the last one
    assert nav.current == "output"


def test_every_old_setting_has_a_control_bound_to_it(tab):
    assert set(tab.binder.controls) == OPTIONS_KEYS
    assert not (PLAN_KEYS & set(tab.binder.controls))  # the Plan tab owns these
    assert OPTIONS_KEYS | PLAN_KEYS == set(DEFAULTS) - {"generic_name_template"}  # nothing of the 38 is forgotten
    assert tab.tools_info_label is not None and tab.update_btn is not None


def test_booleans_are_switches(tab):
    assert {k for k, c in tab.binder.controls.items() if isinstance(c, Toggle)} == SWITCHES
    assert set(tab.toggles) == SWITCHES


def test_numbers_are_spin_boxes_and_lists_are_combo_boxes(tab):
    spins = {"threads", "threshold", "pad_after", "clip_pad_before", "clip_pad_after", "chat_render_width",
             "chat_render_height", "chat_render_font_size"}
    combos = {"container", "strategy", "chat_format", "chat_render_mode", "chat_render_look", "chat_render_fps",
              "default_quality", "audio_format", "cookies_from_browser"}
    assert {k for k, c in tab.binder.controls.items() if isinstance(c, SpinBox)} == spins
    assert {k for k, c in tab.binder.controls.items() if isinstance(c, ComboBox)} == combos


# ------------------------------------------------------------------ the approved split
UP_FRONT = {
    "output": {"out_dir", "container", "default_quality", "audio_format"},
    "cuts": {"strategy", "exact", "keep_full"},
    "premiere": {"premiere_plugin", "game_markers", "muted_markers"},
    "chat": {"chat", "chat_render"},
}
IN_ADVANCED = {
    "output": {"threads", "name_template", "subfolders", "folder_template"},
    "cuts": {"threshold"},
    "premiere": {"premiere_xml", "sidecar"},
    "chat": {"chat_format", "chat_embed", "chat_render_mode", "chat_render_look", "chat_render_width",
             "chat_render_height", "chat_render_font_size", "chat_render_fps", "chat_render_smooth"},
}


@pytest.mark.parametrize("key", list(UP_FRONT))
def test_up_front_and_advanced_settings_are_split_as_agreed(tab, key):
    adv, section = tab.advanced[key], tab.sections[key]
    for name in IN_ADVANCED[key]:
        assert adv.isAncestorOf(control(tab, name)), name
    for name in UP_FRONT[key]:
        assert section.isAncestorOf(control(tab, name)) and not adv.isAncestorOf(control(tab, name)), name


def test_chapters_clips_and_tools_have_no_advanced_area(tab):
    assert set(tab.advanced) == {"output", "cuts", "premiere", "chat"}
    for key in ("chapters", "clips", "tools"):
        assert not tab.sections[key].findChildren(Collapsible)


def test_advanced_starts_collapsed_and_opens_on_click(tab):
    adv = tab.advanced["output"]
    assert not adv.opened and adv.body.isHidden() and "\u25b8" in adv.header.text()
    adv.header.click()
    assert adv.opened and not adv.body.isHidden() and "\u25be" in adv.header.text()
    adv.header.click()
    assert not adv.opened and adv.body.isHidden()


def test_a_value_inside_a_collapsed_advanced_area_is_still_used(tab):
    control(tab, "threads").setValue(12)
    control(tab, "threshold").setValue(75)
    control(tab, "chat_format").setCurrentText("txt")
    assert not tab.advanced["output"].opened
    opts = build_options(tab.settings)
    assert (opts.threads, opts.full_threshold, opts.chat_format) == (12, 0.75, "txt")


def test_the_chat_overlay_settings_reach_the_options(tab):
    opts = build_options(tab.settings)
    assert opts.chat_render is False
    assert (opts.chat_render_mode, opts.chat_render_look, opts.chat_render_fps) == ("transparent", "outline", 0)
    assert (opts.chat_render_width, opts.chat_render_height, opts.chat_render_font_size) == (400, 0, 18)
    control(tab, "chat_render").click()
    mode, look = control(tab, "chat_render_mode"), control(tab, "chat_render_look")
    mode.setCurrentIndex(mode.count() - 1)
    look.setCurrentIndex(look.count() - 1)
    control(tab, "chat_render_width").setValue(500)
    control(tab, "chat_render_height").setValue(1080)
    control(tab, "chat_render_font_size").setValue(24)
    control(tab, "chat_render_fps").setCurrentText("60")
    control(tab, "chat_render_smooth").click()
    opts = build_options(tab.settings)
    assert opts.chat_render is True and opts.chat_render_smooth is True
    assert opts.chat_render_mode in eng.CHAT_RENDER_MODES and opts.chat_render_mode != "transparent"
    assert opts.chat_render_look == "panel"
    assert (opts.chat_render_width, opts.chat_render_height, opts.chat_render_font_size) == (500, 1080, 24)
    assert opts.chat_render_fps == 60


def test_the_default_overlay_type_is_animation(tab):
    assert control(tab, "chat_render_mode").currentText().startswith("Transparent · Animation")
    assert build_options(tab.settings).chat_render_mode == "transparent"


# ------------------------------------------------------------------ the binder
def test_a_switch_writes_a_real_boolean_and_a_number_field_writes_a_string(tab):
    assert tab.settings["exact"] is False
    control(tab, "exact").click()
    assert tab.settings["exact"] is True
    control(tab, "threads").setValue(12)
    assert tab.settings["threads"] == "12"
    control(tab, "container").setCurrentText("mkv")
    assert tab.settings["container"] == "mkv"
    control(tab, "out_dir").setText("D:/x")
    assert tab.settings["out_dir"] == "D:/x"


def test_changing_a_setting_from_code_updates_the_control_and_says_so(tab, qtbot):
    with qtbot.waitSignal(tab.binder.changed) as sig:
        tab.binder.set("threads", "20")
    assert sig.args == ["threads"]
    assert control(tab, "threads").value() == 20 and tab.settings["threads"] == "20"
    tab.binder.set("exact", True)
    assert control(tab, "exact").isChecked()


def test_loading_a_value_never_writes_it_back(qtbot, themed, boxes):
    """A saved value the control cannot show stays in the dictionary until the person changes that control."""
    saved = dict(DEFAULTS, threads="7.5", strategy="Some old word", chat_render_width=300, exact="yes")
    t = OptionsTab(saved)
    qtbot.addWidget(t)
    assert saved["threads"] == "7.5" and saved["strategy"] == "Some old word" and saved["chat_render_width"] == 300
    assert saved["exact"] == "yes"
    assert control(t, "threads").value() == 7 and control(t, "chat_render_width").value() == 300
    assert control(t, "strategy").currentIndex() == -1 and control(t, "exact").isChecked()
    control(t, "threads").setValue(9)
    assert saved["threads"] == "9"


def test_an_empty_settings_dictionary_shows_the_defaults_and_fills_in_only_what_is_edited(qtbot, themed, boxes):
    empty = {}
    t = OptionsTab(empty)
    qtbot.addWidget(t)
    assert control(t, "threads").value() == 8 and control(t, "container").currentText() == "mp4"
    assert empty == {}
    control(t, "threads").setValue(3)
    assert empty == {"threads": "3"}


def test_a_key_that_is_not_a_setting_cannot_be_bound(tab):
    with pytest.raises(KeyError):
        tab.binder.bind("nonsense", Toggle())
    with pytest.raises(ValueError):
        tab.binder.bind("exact", Toggle())  # already bound


# ------------------------------------------------------------------ wheel and keyboard order
def wheel(widget, delta=-120):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    event = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, delta),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def test_the_wheel_over_a_drop_down_or_number_field_changes_nothing_without_focus(tab):
    """tkinter let the wheel change a combo box while the page scrolled (MIGRATION_LOG no. 14)."""
    for key in ("container", "chat_format"):
        box = control(tab, key)
        assert not box.hasFocus()
        before = box.currentText()
        wheel(box)
        assert box.currentText() == before, key
    threads = control(tab, "threads")
    before = threads.value()
    wheel(threads)
    wheel(threads, 120)
    assert threads.value() == before and tab.settings["threads"] == DEFAULTS["threads"]


def test_the_tab_order_has_nothing_decorative(tab):
    """tkinter test_tab_order_of_search_queue_and_options_has_nothing_decorative: the scroll area and the cards must not
    take the keyboard; only real controls are Tab stops."""
    from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QWidget

    assert tab.scroll.focusPolicy() == Qt.FocusPolicy.NoFocus
    stops = [w for w in tab.findChildren(QWidget) if w.focusPolicy() != Qt.FocusPolicy.NoFocus and w.isVisibleTo(tab)]
    assert stops
    for w in stops:
        assert isinstance(w, (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox)) and w is not tab.scroll, w


# ------------------------------------------------------------------ signals to the window
def test_the_premiere_switches_ask_for_a_clip_refresh_only_when_clicked(tab, qtbot):
    for key in ("premiere_plugin", "premiere_xml"):
        with qtbot.waitSignal(tab.refresh_clips_requested, timeout=1000):
            control(tab, key).click()
    with qtbot.assertNotEmitted(tab.refresh_clips_requested):
        tab.binder.set("premiere_plugin", False)
    assert tab.settings["premiere_xml"] is True


def test_the_chapter_title_and_tail_ask_for_a_clip_refresh(tab, qtbot):
    tab.nav.select("chapters")
    with qtbot.waitSignal(tab.refresh_clips_requested, timeout=1000):
        qtbot.keyClick(control(tab, "title_tpl"), "x")
    with qtbot.waitSignal(tab.refresh_clips_requested, timeout=1000):
        control(tab, "pad_after").setValue(5)
    with qtbot.assertNotEmitted(tab.refresh_clips_requested):
        control(tab, "title_tpl").setText("{title}")  # typed by code: no refresh


def test_strategy_and_threshold_ask_for_a_preview(tab, qtbot):
    with qtbot.waitSignal(tab.preview_requested, timeout=1000):
        control(tab, "threshold").setValue(70)
    box = control(tab, "strategy")
    with qtbot.assertNotEmitted(tab.preview_requested):
        box.setCurrentIndex(1)  # by code
    with qtbot.waitSignal(tab.preview_requested, timeout=1000):
        box.activated.emit(1)  # a choice by the person


def test_the_buttons_send_their_signals(tab, qtbot):
    with qtbot.waitSignal(tab.output_folder_requested, timeout=1000):
        tab.open_folder_btn.click()
    with qtbot.waitSignal(tab.update_tools_requested, timeout=1000):
        tab.update_btn.click()
    with qtbot.waitSignal(tab.saved_chat_requested, timeout=1000):
        tab.saved_chat_btn.click()


def test_browse_puts_the_chosen_folder_in_the_field_and_cancel_changes_nothing(tab, boxes):
    boxes.folder = "D:/Chosen"
    tab.browse_btn.click()
    assert control(tab, "out_dir").text() == "D:/Chosen" and tab.settings["out_dir"] == "D:/Chosen"
    assert boxes.asked[-1] == DEFAULTS["out_dir"]  # the dialog starts in the current folder
    boxes.folder = ""
    tab.browse_btn.click()
    assert tab.settings["out_dir"] == "D:/Chosen"


# ------------------------------------------------------------------ chips and live examples
def test_clicking_a_chip_inserts_the_token_at_the_cursor(tab):
    entry = tab.template_entries["name_template"]
    entry.setText("A - B")
    entry.setCursorPosition(4)
    chip(tab, "name_template", "title").click()
    assert entry.text() == "A - {title}B" and tab.settings["name_template"] == "A - {title}B"


def test_a_chip_replaces_the_selected_text(tab):
    entry = tab.template_entries["folder_template"]
    entry.setText("xxx - {id}")
    entry.setSelection(0, 3)
    chip(tab, "folder_template", "date").click()
    assert entry.text() == "{date} - {id}"


def test_every_template_field_has_chips_for_its_tokens(tab):
    expected = {
        "name_template": {
            "streamer", "stream_date", "download_date", "date", "year", "month",
            "day", "game", "quality", "id", "title",
            "duration", "n", "total", "start", "end",
        },
        "folder_template": {
            "streamer", "stream_date", "download_date", "date", "year", "month", "day",
            "game", "quality", "id", "title", "duration",
        },
        "title_tpl": {"title", "creator", "views", "duration"},
        "clip_name_template": {"clip_title", "creator", "views", "clip_id", "clip_duration",
                               "streamer", "date", "id", "title", "start", "end"},
    }
    assert set(tab.chip_rows) == set(expected)
    for key, tokens in expected.items():
        assert {b.text().strip("{}") for b in tab.chip_rows[key].chips} == tokens, key


def test_examples_use_a_sample_vod_until_one_is_loaded_then_the_real_one(tab):
    assert example(tab, "name_template") == "Example:  Streamer - 2026-10-01 - 123 - part1.mp4"
    assert example(tab, "folder_template") == "Example:  Streamer/2026-10-01 - Big Stream - 123"
    real = eng.SourceInfo(**dict(examples.SAMPLE_SOURCE, uploader="Zed", title="Late night", date="2026-12-24",
                                 twitch_vod_id="999"))
    tab.source_provider = lambda: real
    tab.refresh_name_examples()
    assert example(tab, "name_template") == "Example:  Zed - 2026-12-24 - 999 - part1.mp4"
    assert example(tab, "folder_template") == "Example:  Zed/2026-12-24 - Late night - 999"


def test_the_example_line_follows_the_template_and_the_format_as_you_type(tab):
    tab.template_entries["name_template"].setText("{n} of {total} - {title}")
    assert example(tab, "name_template") == "Example:  1 of 3 - Big Stream.mp4"
    control(tab, "container").setCurrentText("mkv")
    assert example(tab, "name_template") == "Example:  1 of 3 - Big Stream.mkv"
    tab.template_entries["name_template"].setText("{game} - {duration} - {quality}")
    assert example(tab, "name_template") == "Example:  Just Chatting - 01h00m00s - 1080p60.mkv"


def test_a_half_typed_template_never_breaks_the_example(tab):
    for bad in ("{", "{title", "{0}", "}{", ""):
        for key in ("name_template", "folder_template", "clip_name_template", "title_tpl"):
            tab.template_entries[key].setText(bad)
    assert all(label.text().startswith("Example:") for label in tab.example_labels.values())


def test_the_example_matches_what_the_engine_really_names_the_file(tab):
    tab.template_entries["name_template"].setText("{streamer}_{start}-{end}")
    src = eng.SourceInfo(**examples.SAMPLE_SOURCE)
    opts = eng.JobOptions(cut_text="", out_dir="OUT", name_template="{streamer}_{start}-{end}")
    assert tab.example_for("name_template") == eng.part_stem(src, opts, eng.Part(1, 0, 3600), 3) + ".mp4"


def test_clip_and_chapter_examples(tab):
    tab.template_entries["clip_name_template"].setText("{clip_title} by {creator} ({views})")
    assert tab.example_for("clip_name_template") == "Epic fail by viewer1 (500).mp4"
    assert tab.example_for("title_tpl") == "Epic fail (viewer1, 500 views)"
    tab.template_entries["title_tpl"].setText("{title} - {nope}")
    assert tab.example_for("title_tpl") == "Epic fail - {nope}"


def test_an_example_that_raises_is_shown_as_cant_be_shown(tab, monkeypatch):
    monkeypatch.setattr(examples, "example_file_name", lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    tab.refresh_name_examples()
    assert example(tab, "name_template") == "Example:  (can't be shown: boom)"


def test_turning_subfolders_off_greys_out_the_stream_folder_field(tab):
    entry = tab.template_entries["folder_template"]
    assert entry.isEnabled()
    control(tab, "subfolders").click()
    assert not entry.isEnabled() and all(not b.isEnabled() for b in tab.chip_rows["folder_template"].chips)
    before = tab.settings["folder_template"]
    tab.chip_rows["folder_template"].insert("id")  # a disabled field ignores chip clicks
    assert tab.settings["folder_template"] == before
    control(tab, "subfolders").click()
    assert entry.isEnabled() and all(b.isEnabled() for b in tab.chip_rows["folder_template"].chips)


def test_a_saved_file_with_subfolders_off_starts_with_the_field_greyed_out(qtbot, themed, boxes):
    t = OptionsTab(dict(DEFAULTS, subfolders=False))
    qtbot.addWidget(t)
    assert not t.template_entries["folder_template"].isEnabled()


# ------------------------------------------------------------------ tools section
def test_the_tools_text_comes_from_the_window_and_the_button_follows_the_busy_state(tab):
    assert tab.tools_info_label.text() == "Checking…"
    tab.set_tools_info("yt-dlp 2026.01.01 and ffmpeg OK")
    assert tab.tools_info_label.text() == "yt-dlp 2026.01.01 and ffmpeg OK"
    tab.set_tools_running(True)
    assert not tab.update_btn.isEnabled()
    tab.set_tools_running(False)
    assert tab.update_btn.isEnabled()


def test_the_links_card_says_what_this_system_can_do(tab, monkeypatch):
    import weblink

    for state, text, button in (("ok", "Set up: these links open this app.", "Set up again"),
                                ("other", "These links currently open another copy", "Use this copy"),
                                ("missing", "Not set up: these links do nothing", "Set up links")):
        monkeypatch.setattr(weblink, "registration", lambda _s=state: weblink.Registration(True, _s))
        tab.refresh_link_state()
        assert tab.link_info_label.text().startswith(text) and tab.link_btn.text() == button
        assert not tab.link_btn.isHidden()
    monkeypatch.setattr(weblink, "registration", lambda: weblink.Registration(False, "unsupported"))
    tab.refresh_link_state()
    assert tab.link_btn.isHidden()


def test_setting_up_links_reports_success_and_failure(tab, boxes, monkeypatch):
    import weblink

    seen = []
    tab.status_message.connect(seen.append)
    monkeypatch.setattr(weblink, "register", lambda: None)
    tab.register_links()
    assert seen == ["Links are set up: luckytwitch:// links now open this app."]

    def refuse():
        raise OSError("denied")

    monkeypatch.setattr(weblink, "register", refuse)
    tab.register_links()
    assert boxes.log[-1] == ("error", "Links", "Windows did not accept the setting:\ndenied")


# ------------------------------------------------------------------ the window: tools setup
@pytest.fixture()
def fake_tools(monkeypatch):
    calls = types.SimpleNamespace(ensure=[], error=None, release=threading.Event())
    calls.release.set()

    def ensure_tools(ctx, update_ytdlp=True, force=False):
        calls.ensure.append((update_ytdlp, force))
        calls.release.wait(5)
        if calls.error:
            raise RuntimeError(calls.error)

    monkeypatch.setattr("qt_ui.background_jobs.ensure_tools", ensure_tools)
    monkeypatch.setattr("qt_ui.background_jobs.describe_tools", lambda: "yt-dlp 1 and ffmpeg OK")
    return calls


def test_the_tools_setup_runs_in_the_background_and_gives_the_controls_back(win, qtbot, fake_tools):
    fake_tools.release.clear()
    win.start_tools_setup()
    assert win.tools_busy and win.tools_ctx is not None
    assert not win.info_btn.isEnabled() and not win.tab_options.update_btn.isEnabled()
    assert win.status_label.text() == "Preparing tools (yt-dlp, ffmpeg)…"
    fake_tools.release.set()
    qtbot.waitUntil(lambda: not win.tools_busy, timeout=5000)
    assert win.info_btn.isEnabled() and win.tab_options.update_btn.isEnabled() and win.tools_ctx is None
    assert win.tab_options.tools_info_label.text() == "yt-dlp 1 and ffmpeg OK"
    assert win.status_label.text() == mw.READY_TEXT
    assert fake_tools.ensure == [(True, False)]  # «check for updates on startup» is on by default


def test_the_startup_check_follows_the_auto_update_switch_and_the_button_forces_it(win, qtbot, fake_tools):
    win.tab_options.binder.set("auto_update", False)
    win.start_tools_setup()
    qtbot.waitUntil(lambda: not win.tools_busy, timeout=5000)
    win.tab_options.update_btn.click()
    qtbot.waitUntil(lambda: len(fake_tools.ensure) == 2 and not win.tools_busy, timeout=5000)
    assert fake_tools.ensure == [(False, False), (True, True)]


def test_a_second_setup_does_not_start_while_one_runs(win, qtbot, fake_tools):
    fake_tools.release.clear()
    win.start_tools_setup()
    win.start_tools_setup()
    fake_tools.release.set()
    qtbot.waitUntil(lambda: not win.tools_busy, timeout=5000)
    assert len(fake_tools.ensure) == 1


def test_a_failed_setup_shows_the_reason_and_frees_the_controls(win, qtbot, boxes, fake_tools):
    fake_tools.error = "no internet"
    win.start_tools_setup()
    qtbot.waitUntil(lambda: not win.tools_busy, timeout=5000)
    assert boxes.log[-1] == ("warning", "Tools", "no internet")
    assert win.status_label.text() == "Some tools are missing. See the log."
    assert "Tools: no internet" in win.tab_queue.log_view.log_text()
    assert win.info_btn.isEnabled()


def test_update_now_waits_while_a_job_runs(win, boxes, fake_tools, monkeypatch):
    monkeypatch.setattr(type(win.tab_queue.runner), "is_running", lambda self: True)
    win.update_tools_now()
    assert boxes.log[-1] == ("info", "Running", "Wait for the running job to finish (or cancel it) first.")
    assert fake_tools.ensure == []


def test_a_worker_that_outlives_its_window_ends_quietly(qtbot, themed, fake_tools):
    """The Bridge is deleted while the thread is still working: the thread must not raise (found with the first run)."""
    fake_tools.release.clear()
    w = mw.MainWindow(settings=dict(DEFAULTS), client=object())
    qtbot.addWidget(w)
    w.start_tools_setup()
    thread = w.tools_runner.thread
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, 0)
    fake_tools.release.set()
    thread.join(5)
    assert not thread.is_alive()


# ------------------------------------------------------------------ the window: overlay of a saved chat
def saved_chat(tmp_path, name="Streamer - part1.chat.json"):
    path = tmp_path / name
    path.write_text(json.dumps({
        "streamer": {"name": "Streamer"}, "video": {"id": "42", "start": 100, "end": 160, "title": "t"},
        "comments": [{"content_offset_seconds": 100}], "embeddedData": None}), encoding="utf-8")
    return path


def last(boxes, kind):
    return [c for c in boxes.log if c[0] == kind][-1]


def test_the_saved_chat_button_is_in_the_chat_section_up_front(tab):
    assert tab.sections["chat"].isAncestorOf(tab.saved_chat_btn)
    assert not tab.advanced["chat"].isAncestorOf(tab.saved_chat_btn)


def test_choosing_a_chat_asks_for_confirmation_with_what_it_will_do(win, boxes, tmp_path, monkeypatch):
    boxes.picked, boxes.confirm = str(saved_chat(tmp_path)), False
    started = []
    monkeypatch.setattr(win, "start_saved_chat_render", lambda *a: started.append(a))
    win.render_saved_chat()
    title, text = last(boxes, "confirm")[1:]
    assert title == "Draw the chat overlay?"
    assert "Streamer · VOD 42" in text and "Covers 0:01:40 to 0:02:40" in text and "chat-overlay.mov" in text
    assert text.endswith("\n\nIt can take a while for a long chat.")
    assert started == []  # «Cancel»: nothing happens


def test_cancelling_the_file_dialog_does_nothing(win, boxes):
    win.render_saved_chat()
    assert not [c for c in boxes.log if c[0] == "confirm"] and not win.saved_chat_busy


def test_a_file_that_is_not_a_chat_shows_why_and_starts_nothing(win, boxes, tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{}", encoding="utf-8")
    boxes.picked = str(bad)
    win.render_saved_chat()
    assert not [c for c in boxes.log if c[0] == "confirm"] and not win.saved_chat_busy
    kind, title, text = boxes.log[-1]
    assert (kind, title) == ("error", "Chat overlay") and "not a chat file" in text


def test_the_file_dialog_opens_in_the_output_folder(win, boxes, tmp_path):
    win.tab_options.binder.set("out_dir", str(tmp_path))
    win.render_saved_chat()
    assert boxes.asked == [str(tmp_path)]


def test_drawing_a_saved_chat_runs_in_the_background_and_gives_the_controls_back(win, boxes, qtbot, tmp_path, monkeypatch):
    chat = saved_chat(tmp_path)
    boxes.picked = str(chat)
    win.tab_options.binder.set("chat_render_font_size", "33")
    got = {}

    def fake_render(ctx, tool, chat_json, opts, cache):
        got.update(tool=tool, chat=chat_json, opts=opts, cache_exists=Path(cache).is_dir(), busy=win.saved_chat_busy)
        ctx.log("drawing…")
        return tmp_path / "Streamer - part1.chat-overlay.mov"

    monkeypatch.setattr("qt_ui.background_jobs.ensure_tdcli", lambda ctx: "the-cli")
    monkeypatch.setattr("qt_ui.background_jobs.render_existing_chat", fake_render)
    win.render_saved_chat()
    assert win.saved_chat_busy  # the window stays responsive: the work is in a thread
    assert not win.tab_queue.start_btn.isEnabled() and win.tab_queue.cancel_btn.isEnabled()
    assert not win.tab_options.saved_chat_btn.isEnabled()
    assert win.tabs.currentWidget() is win.tab_queue  # the log and «Cancel current» live there
    qtbot.waitUntil(lambda: not win.saved_chat_busy, timeout=5000)
    assert got["tool"] == "the-cli" and got["chat"] == chat and got["opts"].chat_render_font_size == 33
    assert got["cache_exists"] and got["busy"]
    assert win.saved_chat_ctx is None
    assert win.tab_queue.start_btn.isEnabled() and not win.tab_queue.cancel_btn.isEnabled()
    assert win.tab_options.saved_chat_btn.isEnabled()
    assert "Streamer - part1.chat-overlay.mov" in win.status_label.text()
    assert "drawing…" in win.tab_queue.log_view.log_text()


def test_a_failed_render_shows_the_reason_and_frees_the_controls(win, boxes, qtbot, tmp_path, monkeypatch):
    boxes.picked = str(saved_chat(tmp_path))
    monkeypatch.setattr("qt_ui.background_jobs.ensure_tdcli", lambda ctx: "the-cli")

    def boom(*a):
        raise eng.EngineError("Chat render failed: no internet")

    monkeypatch.setattr("qt_ui.background_jobs.render_existing_chat", boom)
    win.render_saved_chat()
    qtbot.waitUntil(lambda: not win.saved_chat_busy, timeout=5000)
    assert boxes.log[-1] == ("error", "Chat overlay", "Chat render failed: no internet")
    assert win.status_label.text() == "Chat overlay failed. See the log."
    assert win.tab_options.saved_chat_btn.isEnabled() and win.tab_queue.start_btn.isEnabled()


def test_cancelling_a_saved_chat_render_is_quiet(win, boxes, qtbot, tmp_path, monkeypatch):
    boxes.picked = str(saved_chat(tmp_path))
    monkeypatch.setattr("qt_ui.background_jobs.ensure_tdcli", lambda ctx: "the-cli")

    def stopped(*a):
        raise eng.Cancelled("Cancelled.")

    monkeypatch.setattr("qt_ui.background_jobs.render_existing_chat", stopped)
    win.render_saved_chat()
    qtbot.waitUntil(lambda: not win.saved_chat_busy, timeout=5000)
    assert not [c for c in boxes.log if c[0] == "error"]  # no error box for a cancel
    assert win.status_label.text() == "Chat overlay cancelled." and win.tab_options.saved_chat_btn.isEnabled()
    assert "Cancelled." in win.tab_queue.log_view.log_text()


def test_cancel_current_stops_a_chat_overlay(win, boxes, qtbot, tmp_path, monkeypatch):
    boxes.picked = str(saved_chat(tmp_path))
    monkeypatch.setattr("qt_ui.background_jobs.ensure_tdcli", lambda ctx: "the-cli")

    def slow(ctx, tool, chat_json, opts, cache):
        ctx.cancel_event.wait(5)
        raise eng.Cancelled("Cancelled.")

    monkeypatch.setattr("qt_ui.background_jobs.render_existing_chat", slow)
    win.render_saved_chat()
    qtbot.waitUntil(lambda: win.tab_queue.cancel_btn.isEnabled(), timeout=2000)
    win.tab_queue.cancel_btn.click()
    assert win.status_label.text() == "Cancelling…"
    qtbot.waitUntil(lambda: not win.saved_chat_busy, timeout=5000)
    assert win.status_label.text() == "Chat overlay cancelled."


def test_only_one_thing_runs_at_a_time(win, boxes, tmp_path):
    boxes.picked = str(saved_chat(tmp_path))
    win.saved_chat_busy = True
    win.render_saved_chat()
    assert boxes.asked == [] and boxes.log[-1][:2] == ("info", "Busy")
    win.saved_chat_busy, win.tools_busy = False, True
    win.render_saved_chat()
    assert boxes.asked == []
    win.tools_busy = False


def test_the_window_builds_the_same_options_as_core_from_its_settings(win):
    win.tab_options.binder.set("threads", "5")
    assert win.build_options().threads == 5
    assert win.build_options() == build_options(win.settings, "")
    assert win.build_filter() == build_options(win.settings).clip_filter


def test_the_settings_the_options_tab_edits_are_saved_when_the_window_closes(win, tmp_path):
    from core import paths

    win.tab_options.binder.set("threads", "6")
    control(win.tab_options, "exact").click()
    win.close()
    saved = json.loads(paths.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert saved["threads"] == "6" and saved["exact"] is True and set(saved) == set(DEFAULTS)


# ------------------------------------------------------------------ Phase 9d (G1 to G5)
def test_search_settings_filters_rows_and_shows_match_count(tab):
    assert tab.search_entry is not None
    assert not tab.match_counter.isVisible()

    tab.search_entry.setText("ffmpeg")
    assert tab.match_counter.isVisible()
    assert "match" in tab.match_counter.text()

    tab.search_entry.setText("")
    assert not tab.match_counter.isVisible()
    assert tab.sections["output"].isVisible()


def test_changed_from_default_marker_and_reset(tab, qtbot):
    tab.advanced["output"].set_opened(True)
    row, section = tab.rows_by_key["threads"]
    assert not row.changed_dot.isVisible()
    assert not row.reset_btn.isVisible()

    tab.binder.set("threads", "16")
    assert row.changed_dot.isVisible()
    assert row.reset_btn.isVisible()
    assert "(1)" in tab.nav.buttons["output"].text()

    # Reset reverts to default
    row.reset_btn.click()
    assert control(tab, "threads").value() == 8
    assert tab.settings["threads"] == "8"
    assert not row.changed_dot.isVisible()
    assert not row.reset_btn.isVisible()
    assert "(1)" not in tab.nav.buttons["output"].text()


def test_files_will_be_saved_as_preview_card_and_disk_space(tab):
    assert hasattr(tab, "save_preview_card")
    assert tab.save_preview_path.text() != ""
    assert "Drive free space" in tab.disk_space_label.text() or "Destination folder" in tab.disk_space_label.text()

    tab.binder.set("container", "mkv")
    assert tab.save_preview_path.text().endswith(".mkv")
    assert not tab.save_preview_path.text().endswith(".mkv.mkv")
    tab.binder.set("container", "mp4")
    assert tab.save_preview_path.text().endswith(".mp4")
    assert not tab.save_preview_path.text().endswith(".mp4.mp4")


def test_tools_status_rows_show_individual_versions(tab):
    assert hasattr(tab, "ytdlp_status_label")
    assert hasattr(tab, "ffmpeg_status_label")

    tab.set_tools_info("yt-dlp 2024.10.22 · ffmpeg 7.0")
    assert "2024.10.22" in tab.ytdlp_status_label.text()
    assert "7.0" in tab.ffmpeg_status_label.text()


def test_tools_status_rows_with_long_paths_keep_scroll_width_compact(tab):
    raw_info = (
        "yt-dlp 2026.08.19 (C:\\Users\\Lucky\\AppData\\Local\\Programs\\Python\\Python314\\Scripts\\yt-dlp.EXE)\n"
        "ffmpeg N-125875-g5d4d3bdc61-20260731 (C:\\Users\\Lucky\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
        "yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-N-125875-g5d4d3bdc61-win64-gpl\\bin\\ffmpeg.EXE)\n"
        "TwitchDownloaderCLI 1.56.5 (managed by LuckyTwitch)"
    )
    tab.set_tools_info(raw_info)
    assert tab.ytdlp_status_label.text() == "2026.08.19"
    assert tab.ffmpeg_status_label.text() == "N-125875-g5d4d3bdc61-20260731"
    # Status labels must not expand beyond 280 px
    assert tab.ytdlp_status_label.maximumWidth() <= 280
    assert tab.ffmpeg_status_label.maximumWidth() <= 280


def test_quality_and_audio_combos_exist_and_bind(tab, qtbot):
    q_combo = control(tab, "default_quality")
    a_combo = control(tab, "audio_format")
    assert isinstance(q_combo, ComboBox)
    assert isinstance(a_combo, ComboBox)
    assert [q_combo.itemText(i) for i in range(q_combo.count())] == QUALITY_NAMES
    assert [a_combo.itemText(i) for i in range(a_combo.count())] == AUDIO_FORMAT_NAMES
    assert q_combo.currentText() == DEFAULTS["default_quality"]
    assert a_combo.currentText() == DEFAULTS["audio_format"]

    # Changing selection writes to settings
    q_combo.setCurrentText("720p")
    assert tab.settings["default_quality"] == "720p"

    a_combo.setCurrentText("mp3 · converted")
    assert tab.settings["audio_format"] == "mp3 · converted"


def test_quality_and_audio_rows_found_by_search(tab):
    tab.search_entry.setText("quality")
    assert tab.match_counter.isVisible()
    row, _ = tab.rows_by_key["default_quality"]
    assert row.isVisible()

    tab.search_entry.setText("audio")
    assert tab.match_counter.isVisible()
    row, _ = tab.rows_by_key["audio_format"]
    assert row.isVisible()

    tab.search_entry.setText("")


def test_quality_and_audio_changed_marker_and_reset(tab):
    row, _ = tab.rows_by_key["default_quality"]
    assert not row.changed_dot.isVisible()
    assert not row.reset_btn.isVisible()

    tab.binder.set("default_quality", "720p")
    assert row.changed_dot.isVisible()
    assert row.reset_btn.isVisible()

    row.reset_btn.click()
    assert control(tab, "default_quality").currentText() == DEFAULTS["default_quality"]
    assert tab.settings["default_quality"] == DEFAULTS["default_quality"]
    assert not row.changed_dot.isVisible()


def test_app_updates_card_and_check_now_signal(tab, qtbot):
    assert hasattr(tab, "check_app_updates_btn")
    assert hasattr(tab, "app_version_label")
    assert tab.check_app_updates_btn.isEnabled()

    signal_emitted = []
    tab.check_app_updates_requested.connect(lambda: signal_emitted.append(True))

    tab.check_app_updates_btn.click()
    assert len(signal_emitted) == 1

    # Toggle check_app_updates
    assert tab.settings["check_app_updates"] is True
    tab.binder.set("check_app_updates", False)
    assert tab.settings["check_app_updates"] is False
    tab.binder.set("check_app_updates", True)
    assert tab.settings["check_app_updates"] is True

