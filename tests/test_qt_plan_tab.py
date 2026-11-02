"""The Qt Plan tab (without the timeline, which is a placeholder until Phase 7), «Get info», adding jobs and clips to
the queue, and ``luckytwitch://`` links (Phase 6).

Ports of ``tests/test_gui_plan_tab.py`` (31), ``tests/test_gui_plan_redesign.py`` (10), ``tests/test_gui_weblink.py``
(16) and the Plan-tab tests of ``tests/test_gui_final_pass.py`` (5). Nothing touches the network: ``get_source_info``
and ``fetch_clips_for_vod`` are replaced by fakes in ``qt_ui.background_jobs``; message boxes and ``webbrowser.open``
are replaced too. Runs on Qt's offscreen platform.
"""

from __future__ import annotations

import threading
import types
import webbrowser

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QPushButton, QTableView,
    QWidget,
)

import luckytwitch_engine as eng  # noqa: E402
import luckytwitch_qt  # noqa: E402
import weblink  # noqa: E402
from core import paths  # noqa: E402
from core.palette import ERR, MUTED, OK  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from qt_ui import background_jobs, dialogs, theme  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui.tabs.plan import CLIP_COLUMNS, PlanTab  # noqa: E402
from qt_ui.widgets import Card, ScrollPage, SpinBox, Toggle, WrapLabel  # noqa: E402

SOURCE = dict(url="https://www.twitch.tv/videos/123", id="v123", title="Big Stream", uploader="Streamer",
              duration=7200.0, date="2026-10-01", twitch_vod_id="123")
VOD = "https://www.twitch.tv/videos/123"


def make_clips():
    return [
        {"id": "a", "vod_offset": 630.4, "view_count": 500, "duration": 30, "title": "Epic fail \U0001F602",
         "creator_name": "viewer1", "url": "https://clips.twitch.tv/a"},
        {"id": "b", "vod_offset": 3612, "view_count": 10, "duration": 12, "title": "Small one",
         "creator_name": "viewer2", "url": "https://clips.twitch.tv/b"},
        {"id": "c", "vod_offset": None, "view_count": 99, "duration": 20, "title": "No offset",
         "creator_name": "viewer3", "url": "https://clips.twitch.tv/c"},
    ]


def link(cuts: str = "", label: str = "") -> str:
    return weblink.build_link(VOD, cuts, label)


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
    calls = types.SimpleNamespace(log=[], opened=[])
    for name in ("info", "warning", "error"):
        monkeypatch.setattr(dialogs, name, lambda parent, title, text, _n=name: calls.log.append((_n, title, text)))
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda parent, title, text: True)
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: calls.opened.append(url))
    return calls


@pytest.fixture()
def win(qtbot, themed, boxes):
    w = mw.MainWindow(settings=dict(DEFAULTS), client=None)  # starts on the Plan tab
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def load_vod(win, **overrides):
    win.source = eng.SourceInfo(**{**SOURCE, **overrides})


def load_clips(win):
    win.clips, win.clips_loaded = make_clips(), True
    win.refresh_clips()


def rows_of(win) -> list[list[str]]:
    m = win.tab_plan.clip_model
    return [[m.index(r, c).data() for c in range(m.columnCount())] for r in range(m.rowCount())]


def preview_of(win) -> tuple[str, str]:
    return win.tab_plan.preview_text(), win.tab_plan.preview_kind


# --------------------------------------------------------------------------- structure (test_gui_plan_tab.py)
def test_app_uses_the_plan_tab_mixin(win):
    """In Qt, PlanTab is a widget class owned by MainWindow rather than a mixin; both expose the same methods."""
    assert isinstance(win.tab_plan, PlanTab)
    for name in ("set_preview", "update_preview", "refresh_clips", "open_clip", "split_at_clip"):
        assert hasattr(win.tab_plan, name)


def test_tabs_are_in_the_expected_order(win):
    assert win.tab_names() == ["Browse", "Plan", "Options", "Queue & log"]


def test_plan_tab_has_its_widgets(win):
    plan = win.tab_plan
    assert isinstance(plan.cuts, QPlainTextEdit)
    assert isinstance(plan.preview, QPlainTextEdit) and plan.preview.isReadOnly()
    assert [c[0] for c in CLIP_COLUMNS] == ["at", "views", "dur", "title", "creator", "chap"]
    button_texts = {b.text().replace("&&", "&") for b in plan.findChildren(QPushButton)}
    assert {"Split at selected clip", "Download only selected clip", "Add to queue", "Add & start"} <= button_texts


# --------------------------------------------------------------------------- preview (test_gui_plan_tab.py)
def test_preview_empty_hint(win):
    win.update_preview()
    assert preview_of(win) == ("Write the cut points above (press «Get info» first so «end» works).", "muted")


def test_preview_end_needs_get_info(win):
    win.tab_plan.set_cut_text("0:00 - end")
    win.update_preview()
    assert preview_of(win) == ("\u26a0 «end» needs the VOD length: press «Get info» first.", "err")


def test_preview_lists_the_parts(win):
    load_vod(win)
    win.tab_plan.set_cut_text("0:00 - 30:00 - 1:30:00 - end")
    win.update_preview()
    text, kind = preview_of(win)
    assert kind == "ok"
    assert text == (
        "Part 1:  0:00:00 \u2192 0:30:00   (0:30:00)\n"
        "Part 2:  0:30:00 \u2192 1:30:00   (1:00:00)\n"
        "Part 3:  1:30:00 \u2192 2:00:00   (0:30:00)\n"
        "\u2192 download the full VOD once, then split it   (parts cover 100% of the VOD)"
    )


def test_preview_picks_sections_for_small_coverage(win):
    load_vod(win)
    win.tab_plan.set_cut_text("0:00 - 5:00")
    win.update_preview()
    text, kind = preview_of(win)
    assert kind == "ok"
    assert text.endswith("\u2192 download only these parts   (parts cover 4% of the VOD)")


def test_preview_follows_the_strategy_option(win):
    load_vod(win)
    win.tab_plan.set_cut_text("0:00 - 30:00 - end")
    win.tab_options.binder.set("strategy", "Download only the parts")
    win.update_preview()
    assert "download only these parts" in preview_of(win)[0]
    win.tab_options.binder.set("strategy", "Download full VOD, then split")
    win.update_preview()
    assert "download the full VOD once" in preview_of(win)[0]


@pytest.mark.parametrize(
    "text, message",
    [
        ("30:00 - 10:00", "\u26a0 Cut points must increase: 0:30:00 \u2192 0:10:00."),
        ("0:00 - 30:00 ; 20:00 - 40:00", "\u26a0 Parts overlap: 0:00:00\u20130:30:00 and 0:20:00\u20130:40:00."),
        ("0:00 - 3:00:00", "\u26a0 3:00:00 is beyond the end of the VOD (2:00:00)."),
        ("30:00", "\u26a0 «30:00»: a group needs at least two points (use 0 and end)."),
        ("banana - 10:00", "\u26a0 Invalid time: «banana». Use H:MM:SS, MM:SS, seconds or 1h30m."),
    ],
)
def test_preview_shows_errors(win, text, message):
    load_vod(win)
    win.tab_plan.set_cut_text(text)
    win.update_preview()
    assert preview_of(win) == (message, "err")


def test_typing_in_the_box_updates_the_preview(qtbot, win):
    load_vod(win)
    win.tab_plan.cuts.clear()
    qtbot.keyClicks(win.tab_plan.cuts, "0:00 - 10:00")
    assert preview_of(win)[0].startswith("Part 1:  0:00:00 \u2192 0:10:00")


def test_build_options_reads_the_cut_text_from_the_tab(win):
    win.tab_plan.set_cut_text("  0:00 - 10:00 - end  \n")
    assert win.build_options().cut_text == "0:00 - 10:00 - end"


def test_preview_colours_follow_the_kind(win):
    load_vod(win)
    for cut, kind, colour in (
        ("", "muted", MUTED),
        ("0:00 - 10:00", "ok", OK),
        ("nonsense", "err", ERR),
    ):
        win.tab_plan.set_cut_text(cut)
        win.update_preview()
        cursor = win.tab_plan.preview.textCursor()
        cursor.setPosition(1)
        fmt = cursor.charFormat()
        assert fmt.foreground().color() == QColor(colour), kind


# --------------------------------------------------------------------------- clips table (test_gui_plan_tab.py)
def test_clips_table_rows_and_label(win):
    load_clips(win)
    assert rows_of(win) == [
        ["0:10:00", "500", "30s", "Epic fail \U0001F602", "viewer1", "\u2713"],  # Qt keeps emoji (MIGRATION_LOG no. 8)
        ["1:00:00", "10", "12s", "Small one", "viewer2", "\u2713"],
        ["-", "99", "20s", "No offset", "viewer3", "?"],
    ]
    assert win.tab_plan.clips_label.text() == (
        "2 of 3 clips pass the filter \u2192 2 chapters  (1 can't be placed: no offset)  [chapters are OFF]"
    )


def test_clips_table_follows_the_filter_and_chapters_switch(win):
    load_clips(win)
    win.tab_plan.binder.set("chapters", True)
    win.tab_plan.binder.set("min_views", "100")
    win.refresh_clips()
    assert [r[5] for r in rows_of(win)] == ["\u2713", "\u2014", "?"]
    assert win.tab_plan.clips_label.text() == "1 of 3 clips pass the filter \u2192 1 chapters  (1 can't be placed: no offset)"


def test_clips_table_empty_messages(win):
    win.clips, win.clips_loaded = [], False
    win.refresh_clips()
    assert rows_of(win) == []
    assert win.tab_plan.clips_label.text() == "No clips loaded (sign in with the Twitch API… button, optional)."
    win.clips_loaded = True
    win.refresh_clips()
    assert win.tab_plan.clips_label.text() == "This VOD has no clips."


def test_double_click_target_opens_the_clip_url(win, boxes):
    load_clips(win)
    win.tab_plan.select_clips(1)
    win.tab_plan.open_clip()
    assert boxes.opened == ["https://clips.twitch.tv/b"]


# --------------------------------------------------------------------------- split at clip (test_gui_plan_tab.py)
def test_split_needs_a_selection(win, boxes):
    load_clips(win)
    win.tab_plan.split_at_clip()
    assert boxes.log == [("info", "Select a clip", "Select a clip in the table first.")]


def test_split_needs_exactly_one_clip(win, boxes):
    load_clips(win)
    win.tab_plan.select_clips(0, 1)
    win.tab_plan.split_at_clip()
    assert boxes.log == [("info", "Select one clip", "Splitting works with a single clip: select just one.")]


def test_split_needs_a_loaded_vod(win, boxes):
    load_clips(win)
    win.source = None
    win.tab_plan.select_clips(0)
    win.tab_plan.split_at_clip()
    assert boxes.log == [("info", "No VOD", "Press «Get info» first.")]


def test_split_needs_a_clip_with_a_position(win, boxes):
    load_vod(win)
    load_clips(win)
    win.tab_plan.select_clips(2)
    win.tab_plan.split_at_clip()
    assert boxes.log == [("info", "No offset", "That clip has no position in the VOD.")]


def test_split_inserts_a_cut_point_before_the_clip_and_refreshes_the_preview(win, boxes):
    load_vod(win)
    load_clips(win)
    win.tab_plan.set_cut_text("0:00:00 - end")
    win.tab_plan.select_clips(1)  # clip at 1:00:00, default lead-in 3 s
    win.tab_plan.split_at_clip()
    assert boxes.log == []
    assert win.cut_text() == "0:00:00 - 0:59:57 - end"
    assert preview_of(win)[0].startswith("Part 1:  0:00:00 \u2192 0:59:57   (0:59:57)\nPart 2:  0:59:57 \u2192 2:00:00")


def test_split_with_empty_text_starts_from_the_whole_vod(win):
    load_vod(win)
    load_clips(win)
    win.tab_plan.set_cut_text("")
    win.tab_plan.select_clips(1)
    win.tab_plan.split_at_clip()
    assert win.cut_text() == "0:00:00 - 0:59:57 - end"


def test_split_outside_every_part_explains_why(win, boxes):
    load_vod(win)
    load_clips(win)
    win.tab_plan.set_cut_text("0:00:00 - 0:10:00")
    win.tab_plan.select_clips(1)
    win.tab_plan.split_at_clip()
    assert boxes.log == [("info", "Can't split here", "That moment is not inside any of your parts.")]
    assert win.cut_text() == "0:00:00 - 0:10:00"


def test_split_respects_the_lead_in_setting(win):
    load_vod(win)
    load_clips(win)
    win.tab_plan.set_cut_text("0:00:00 - end")
    win.tab_plan.binder.set("pad_before", "10")
    win.tab_plan.select_clips(1)
    win.tab_plan.split_at_clip()
    assert win.cut_text() == "0:00:00 - 0:59:50 - end"


def test_splitting_twice_at_the_same_clip_keeps_a_valid_plan(win):
    load_vod(win)
    load_clips(win)
    win.tab_plan.set_cut_text("0:00:00 - end")
    win.tab_plan.select_clips(1)
    win.tab_plan.split_at_clip()
    once = win.cut_text()
    win.tab_plan.split_at_clip()
    assert win.cut_text() == once
    assert preview_of(win)[1] == "ok"


# --------------------------------------------------------------------------- Get info & queue (test_gui_plan_tab.py)
def test_get_info_result_fills_the_plan_tab(win):
    info = eng.SourceInfo(url="https://www.twitch.tv/videos/9", id="v9", title="Other", uploader="Someone",
                          duration=3600.0, date="2026-09-09", twitch_vod_id="9")
    win.on_info_ok(info, make_clips()[:2], True, "")
    assert win.info_label.text() == "Someone \u00b7 Other \u00b7 1:00:00 \u00b7 2026-09-09 \u00b7 2 clips"
    assert win.cut_text() == "0:00:00 - end"
    assert preview_of(win)[0].startswith("Part 1:  0:00:00 \u2192 1:00:00   (1:00:00)")
    assert len(rows_of(win)) == 2
    assert "Someone" in win.tab_options.example_for("name_template")  # live examples now use the loaded VOD


def test_get_info_keeps_cut_points_the_user_already_typed(win):
    win.tab_plan.set_cut_text("0:00 - 10:00")
    info = eng.SourceInfo(**{**SOURCE, "duration": 3600.0})
    win.on_info_ok(info, [], True, "")
    assert win.cut_text() == "0:00 - 10:00"


def test_get_info_runs_in_a_worker_and_animates_while_busy(qtbot, win, monkeypatch):
    gate = threading.Event()

    def slow_info(text):
        gate.wait(5)
        return eng.SourceInfo(**SOURCE)

    monkeypatch.setattr(background_jobs, "get_source_info", slow_info)
    win.vod_entry.setText(VOD)
    win.on_get_info()
    assert win._info_busy and not win.info_btn.isEnabled()
    assert win.info_btn.text().startswith("Loading")
    assert win.info_label.text().startswith("Reading VOD info")
    assert (win.progress.minimum(), win.progress.maximum()) == (0, 0)  # indeterminate bar
    gate.set()
    qtbot.waitUntil(lambda: not win._info_busy and win.source is not None, timeout=5000)
    assert win.info_btn.isEnabled() and win.info_btn.text() == "Get info"
    assert "Big Stream" in win.info_label.text()
    assert win.status_label.text() == "VOD loaded. Set your cut points and add it to the queue."


def test_download_selected_clips_queues_one_job_per_clip(win):
    load_vod(win, duration=3600.0)
    load_clips(win)
    win.tab_plan.set_cut_text("0:00 - end")
    win.tab_plan.select_clips(0, 1)
    win.download_clips()
    jobs = [(it.job.opts.cut_text, it.job.opts.strategy) for it in win.tab_queue.items]
    assert jobs == [("0:09:57 - 0:10:34", "sections"), ("0:59:57 - 1:00:00", "sections")]


def test_add_to_queue_and_add_and_start(win, boxes, monkeypatch):
    win.tab_plan.queue_btn.click()
    assert boxes.log == [("info", "No VOD", "Paste a VOD and press «Get info» first.")]
    boxes.log.clear()
    load_vod(win)
    win.tab_plan.set_cut_text("bad")
    win.tab_plan.queue_btn.click()
    assert boxes.log and boxes.log[-1][:2] == ("warning", "Cut points")
    boxes.log.clear()
    win.tab_plan.set_cut_text("0:00:00 - 0:10:00")
    win.tab_plan.queue_btn.click()
    assert len(win.tab_queue.items) == 1
    assert win.status_label.text() == "Added to queue (1 item(s))."
    started = []
    monkeypatch.setattr(win.tab_queue, "start_queue", lambda: started.append(True))
    win.tab_plan.start_btn.click()
    assert len(win.tab_queue.items) == 2 and started == [True]


# --------------------------------------------------------------------------- redesign checks (test_gui_plan_redesign.py)
def test_the_plan_tab_is_a_scroll_page_with_a_footer(win):
    page = win.tab_plan
    assert isinstance(page, ScrollPage)
    assert page.body is page.scroll.body
    texts = {b.text().replace("&&", "&") for b in page.footer.findChildren(QPushButton)}
    assert texts == {"Add to queue", "Add & start"}


def test_the_footer_stays_visible_when_the_page_scrolls(qtbot, win):
    win.resize(1000, 500)
    win.tabs.setCurrentWidget(win.tab_plan)
    QApplication.processEvents()
    page = win.tab_plan
    bar = page.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    assert page.footer.y() >= page.scroll.y() + page.scroll.height()
    assert page.footer.y() + page.queue_btn.y() + page.queue_btn.height() <= page.height()


def test_the_three_sections_are_cards(win):
    page = win.tab_plan
    cards = [page.timeline_card, page.cuts_card, page.clips_card]
    assert all(isinstance(c, Card) and c.parent() is page.body for c in cards)


def test_the_chapters_switch_drives_the_clips_table(win):
    load_vod(win)
    load_clips(win)
    assert "[chapters are OFF]" in win.tab_plan.clips_label.text()
    win.tab_plan.chapters_toggle.click()
    assert win.settings["chapters"] is True
    assert "[chapters are OFF]" not in win.tab_plan.clips_label.text()


def test_the_footer_summary_follows_the_cut_points(win):
    load_vod(win)
    win.tab_plan.set_cut_text("0:00 - 30:00 - 1:30:00 - end")
    win.update_preview()
    assert win.tab_plan.plan_summary_lbl.text() == "3 parts \u00b7 2:00:00 in total"
    win.tab_plan.set_cut_text("0:00 - 30:00 ; 1:00:00 - end")
    win.update_preview()
    assert win.tab_plan.plan_summary_lbl.text() == "2 parts \u00b7 1:30:00 in total"
    win.tab_plan.set_cut_text("0:00 - 0:00")
    win.update_preview()
    assert preview_of(win)[1] == "err"
    assert win.tab_plan.plan_summary_lbl.text() == "Fix the cut points to add this VOD"
    win.tab_plan.set_cut_text("")
    win.update_preview()
    assert win.tab_plan.plan_summary_lbl.text() == ""


def test_the_summary_is_red_only_while_the_cuts_are_wrong(win):
    win.tab_plan.set_cut_text("nonsense")
    win.update_preview()
    assert win.tab_plan.plan_summary_lbl.property("role") == "err"
    load_vod(win)
    win.tab_plan.set_cut_text("0:00 - 30:00")
    win.update_preview()
    assert win.tab_plan.plan_summary_lbl.property("role") == "muted"


def test_table_headings_line_up_with_their_columns(win):
    load_clips(win)
    m = win.tab_plan.clip_model
    for col in range(m.columnCount()):
        assert m.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole) == \
            m.index(0, col).data(Qt.ItemDataRole.TextAlignmentRole)


def test_the_chapter_column_is_wide_enough_for_its_title(win):
    head = win.tab_plan.tree.horizontalHeader()
    chap_col = [c[0] for c in CLIP_COLUMNS].index("chap")
    text_w = win.tab_plan.tree.fontMetrics().horizontalAdvance("Chapter")
    assert head.sectionSize(chap_col) >= 84 and head.sectionSize(chap_col) >= text_w + 16


def test_hints_wrap_to_the_width_of_their_card(win):
    assert isinstance(win.tab_plan.cuts_hint, WrapLabel) and win.tab_plan.cuts_hint.wordWrap()
    assert isinstance(win.tab_plan.clips_label, WrapLabel) and win.tab_plan.clips_label.wordWrap()


def test_nothing_on_the_plan_tab_is_wider_than_the_page(win):
    win.resize(950, 700)
    load_vod(win)
    load_clips(win)
    win.tab_plan.set_cut_text("0:00:00 - 0:30:00 - end")
    win.tabs.setCurrentWidget(win.tab_plan)
    win.update_preview()
    QApplication.processEvents()
    page = win.tab_plan
    limit = page.scroll.viewport().width()
    for card in (page.timeline_card, page.cuts_card, page.clips_card):
        assert card.width() <= limit + 1


def test_clips_table_columns_adapt_to_available_width(win):
    load_vod(win)
    load_clips(win)
    win.tabs.setCurrentWidget(win.tab_plan)
    page = win.tab_plan
    head = page.tree.horizontalHeader()

    # Narrow layout (950px min width)
    win.resize(950, 560)
    QApplication.processEvents()
    viewport_w = page.tree.viewport().width()
    title_w = head.sectionSize(3)
    fixed_sum = sum(head.sectionSize(c) for c in (0, 1, 2, 4, 5))
    assert fixed_sum == 473  # 80 + 70 + 75 + 140 + 108
    assert title_w == max(140, viewport_w - 473)
    assert head.length() <= viewport_w

    # Standard launch size (1040x860)
    win.resize(1040, 860)
    QApplication.processEvents()
    viewport_w = page.tree.viewport().width()
    title_w = head.sectionSize(3)
    assert title_w == max(140, viewport_w - 473)
    assert head.length() <= viewport_w

    # Wide layout (1200px)
    win.resize(1200, 800)
    QApplication.processEvents()
    viewport_w = page.tree.viewport().width()
    title_w = head.sectionSize(3)
    assert title_w == max(140, viewport_w - 473)
    assert head.length() <= viewport_w or title_w == 140
    # Card does not exceed scroll viewport in two-column mode
    assert page.clips_card.width() <= page.scroll.viewport().width()


# --------------------------------------------------------------------------- final pass (test_gui_final_pass.py)
def test_plan_tab_footer_buttons_are_the_last_stops_left_to_right(win):
    win.tabs.setCurrentWidget(win.tab_plan)
    QApplication.processEvents()
    stops = win.tab_plan.tab_stops()
    assert len(stops) >= 10
    assert stops[-2:] == [win.tab_plan.queue_btn, win.tab_plan.start_btn]
    assert stops.index(win.tab_plan.queue_btn) > stops.index(win.tab_plan.download_clips_btn)
    assert stops[0] is win.tab_plan.timeline.btn_out


def test_plan_tab_shift_tab_is_the_exact_reverse(win):
    win.tabs.setCurrentWidget(win.tab_plan)
    QApplication.processEvents()
    page = win.tab_plan
    stops = page.tab_stops()
    for before, w in zip(stops, stops[1:]):
        prev = w.previousInFocusChain()
        for _ in range(1000):
            if (page.body.isAncestorOf(prev) or page.footer.isAncestorOf(prev)) \
                    and (prev.focusPolicy() & Qt.FocusPolicy.TabFocus):
                break
            prev = prev.previousInFocusChain()
        assert prev is before


def test_plan_tab_footer_is_still_packed_at_the_bottom(win):
    page = win.tab_plan
    assert page.queue_btn.x() < page.start_btn.x()
    assert page.footer.y() >= page.scroll.y() + page.scroll.height()


def test_plan_tab_order_has_nothing_decorative(win):
    for w in win.tab_plan.tab_stops():
        assert isinstance(w, (QAbstractButton, QLineEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox, QTableView)) \
            or w is win.tab_plan.timeline.canvas, w


def test_timeline_hint_wraps_to_the_width_of_the_strip(win):
    win.resize(900, 560)
    QApplication.processEvents()
    hint = win.tab_plan.timeline.hint_label
    assert isinstance(hint, WrapLabel) and hint.wordWrap()
    assert hint.width() <= win.tab_plan.timeline.width()


# --------------------------------------------------------------------------- luckytwitch:// links (test_gui_weblink.py)
@pytest.fixture()
def reads(win, monkeypatch):
    calls: list[str] = []

    def fake_info(text):
        calls.append(text)
        return eng.SourceInfo(**SOURCE)

    monkeypatch.setattr(background_jobs, "get_source_info", fake_info)
    win._read_calls = calls
    return win


def test_a_link_fills_the_plan_tab_and_reads_the_vod(qtbot, reads, boxes):
    reads.open_link(link("0:20:00 to 3:30:00", "Big Stream"))
    qtbot.waitUntil(lambda: reads.source is not None, timeout=3000)
    assert reads.vod_entry.text() == VOD
    assert reads.cut_text() == "0:20:00 to 3:30:00"
    assert reads._read_calls == [VOD]
    assert reads.source.title == "Big Stream"
    assert reads.tabs.currentWidget() is reads.tab_plan
    assert "opened from a link (Big Stream)" in reads.status_label.text()
    assert boxes.log == []


def test_without_cut_points_the_default_is_the_whole_vod(qtbot, reads):
    reads.open_link(link())
    qtbot.waitUntil(lambda: reads.source is not None, timeout=3000)
    assert reads.cut_text() == "0:00:00 - end"


def test_a_link_replaces_the_cut_points_that_were_there(qtbot, reads):
    reads.tab_plan.set_cut_text("1:00:00 - 2:00:00")
    reads.open_link(link("5:00 - 10:00"))
    qtbot.waitUntil(lambda: reads.source is not None, timeout=3000)
    assert reads.cut_text() == "5:00 - 10:00"


def test_a_link_never_adds_to_the_queue_or_starts_a_download(qtbot, reads, monkeypatch):
    started = []
    monkeypatch.setattr(reads.tab_queue, "start_queue", lambda *a, **k: started.append(1))
    reads.open_link(link("0:00 - 30:00"))
    qtbot.waitUntil(lambda: reads.source is not None, timeout=3000)
    assert reads.tab_queue.items == [] and started == []
    assert not reads.tab_queue.runner.is_running()


def test_the_previous_vod_is_forgotten_so_its_cuts_cannot_be_reused(qtbot, win, boxes, monkeypatch):
    load_vod(win, title="Old stream")
    monkeypatch.setattr(background_jobs, "get_source_info",
                        lambda text: (_ for _ in ()).throw(eng.EngineError("no such VOD")))
    win.open_link(link("1:00 - 2:00"))
    assert win.source is None
    qtbot.waitUntil(lambda: bool(boxes.log), timeout=3000)
    assert win.source is None
    assert boxes.log[0][0] == "error"
    assert win._info_from_link is None


def test_a_bad_link_says_why_and_changes_nothing(reads, boxes):
    reads.tab_plan.set_cut_text("keep me")
    reads.open_link("luckytwitch://open?url=file:///etc/passwd")
    assert boxes.log and boxes.log[0][0] == "warning" and "http" in boxes.log[0][2]
    assert reads.cut_text() == "keep me" and reads._read_calls == []


def test_a_link_waits_while_the_tools_are_being_prepared(qtbot, reads):
    reads.tools_busy = True
    reads.open_link(link("0:00 - 10:00"))
    qtbot.wait(200)
    assert reads._read_calls == [] and reads.vod_entry.text() == ""
    reads.tools_busy = False
    qtbot.waitUntil(lambda: reads.source is not None, timeout=3000)
    assert reads._read_calls == [VOD] and reads.cut_text() == "0:00 - 10:00"


def test_a_link_left_in_the_folder_is_picked_up_by_the_window(qtbot, reads):
    weblink._drop(paths.LINKS_DIR, link("0:10:00 - 0:20:00", "From a file"))
    qtbot.waitUntil(lambda: reads.source is not None, timeout=3000)
    assert reads.cut_text() == "0:10:00 - 0:20:00"
    assert not list(paths.LINKS_DIR.glob("*.link"))


def test_the_window_says_it_is_alive_and_stops_saying_so_when_it_closes(reads):
    assert weblink.is_running(paths.BEAT_PATH)
    reads.close()
    assert not paths.BEAT_PATH.exists()


def test_a_second_launch_hands_its_link_to_the_open_window(qtbot, reads, monkeypatch):
    assert weblink.is_running(paths.BEAT_PATH)
    created = []
    monkeypatch.setattr(luckytwitch_qt, "LuckyApplication", lambda *a, **k: created.append(1))
    done = []
    t = threading.Thread(target=lambda: done.append(luckytwitch_qt.main(["LuckyTwitch.exe", link("0:00 - 5:00")])))
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=4000)
    t.join(5)
    assert done == [0] and created == []
    qtbot.waitUntil(lambda: reads.cut_text() == "0:00 - 5:00", timeout=3000)
    assert reads.cut_text() == "0:00 - 5:00"


# --------------------------------------------------------------------------- Phase 9e: Plan page polish (D1-D5)
def test_responsive_two_column_vs_stacked_layout(win):
    page = win.tab_plan
    win.tabs.setCurrentWidget(page)
    win.resize(1150, 750)
    QApplication.processEvents()
    assert page.is_two_column()
    assert page.cuts_card.x() < page.clips_card.x()

    win.resize(1000, 700)
    QApplication.processEvents()
    assert not page.is_two_column()
    assert page.cuts_card.y() < page.clips_card.y()

    win.resize(900, 700)
    QApplication.processEvents()
    assert not page.is_two_column()
    assert page.cuts_card.y() < page.clips_card.y()


def test_part_cards_and_coverage_bar_follow_plan_and_support_skip(win):
    segments = [
        eng.GameSegment(0.0, 1800.0, "Just Chatting"),
        eng.GameSegment(1800.0, 7200.0, "Elden Ring: Shadow of the Erdtree Edition"),
    ]
    load_vod(win, segments=segments, muted=[(60.0, 180.0)])
    page = win.tab_plan
    page.set_cut_text("0:00:00 - 0:30:00 - 1:30:00 - end")
    win.update_preview()

    assert len(page.part_cards) == 3
    assert page.part_cards[0].badge_lbl.text() == "P1"
    assert page.part_cards[0].game_name == "Just Chatting"
    assert page.part_cards[0].game_lbl.text() == "Just Chatting"
    assert page.part_cards[0].muted_lbl is not None
    assert page.part_cards[1].game_name == "Elden Ring: Shadow of the Erdtree Edition"
    assert page.part_cards[1].game_lbl.text() == "Elden Ring: Shadow of the Erdtree Edition"
    assert page.coverage_bar.value() == 100
    assert page.coverage_badge.text() == "100% of VOD"

    # Clicking skip on Part 2 removes that middle stretch
    page.part_cards[1].skip_btn.click()
    assert len(page.part_cards) == 2
    assert page.coverage_bar.value() == 50
    assert page.coverage_badge.text() == "50% of VOD"


def test_strategy_segmented_control_syncs_settings_and_preview(win):
    load_vod(win)
    page = win.tab_plan
    page.set_cut_text("0:00:00 - 0:30:00 - end")
    win.update_preview()

    page.strategy_buttons["sections"].click()
    assert win.settings["strategy"] == "Download only the parts"
    assert page.strategy_buttons["sections"].isChecked()
    assert "download only these parts" in preview_of(win)[0]

    page.strategy_buttons["full"].click()
    assert win.settings["strategy"] == "Download full VOD, then split"
    assert page.strategy_buttons["full"].isChecked()
    assert "download the full VOD once" in preview_of(win)[0]


def test_clip_multi_select_toolbar_and_download_n_clips_label(win):
    load_clips(win)
    page = win.tab_plan
    assert page.download_clips_btn.text() == "Download only selected clip"

    page.select_all_clips_btn.click()
    assert page.selected_clip_rows() == [0, 1, 2]
    assert page.download_clips_btn.text() == "Download 3 clips"

    page.select_clips(0)
    assert page.download_clips_btn.text() == "Download 1 clip"

    page.invert_clips_btn.click()
    assert page.selected_clip_rows() == [1, 2]
    assert page.download_clips_btn.text() == "Download 2 clips"

    page.clear_clips_btn.click()
    assert page.selected_clip_rows() == []
    assert page.download_clips_btn.text() == "Download only selected clip"


def test_clips_table_duration_header_and_tooltips(win):
    load_clips(win)
    page = win.tab_plan
    dur_col = [c[0] for c in CLIP_COLUMNS].index("dur")
    assert CLIP_COLUMNS[dur_col][1] == "Duration"

    # Tooltip on model
    m = page.clip_model
    assert m.data(m.index(0, 3), Qt.ItemDataRole.ToolTipRole) == "Epic fail \U0001F602"

    # Header interactive resize mode
    head = page.tree.horizontalHeader()
    for col in range(len(CLIP_COLUMNS)):
        assert head.sectionResizeMode(col) == head.ResizeMode.Interactive


def test_plan_tab_title_editing_and_reset(win, qtbot):
    page = win.tab_plan
    assert page.title_entry.text() == ""
    assert not page.title_entry.isEnabled()
    assert not page.reset_title_btn.isEnabled()

    from luckytwitch_engine import SourceInfo
    src = SourceInfo("https://twitch.tv/videos/1", "1", "Original Title", "Streamer", 3600.0, "2026-10-01", "1")
    page.source = src
    page.set_title("Original Title", "Original Title")
    assert page.title_entry.isEnabled()
    assert page.title_entry.text() == "Original Title"

    # User edits title
    signals = []
    page.title_changed.connect(signals.append)
    page.title_entry.setText("Custom Stream Title")
    assert signals == ["Custom Stream Title"]
    assert src.title == "Custom Stream Title"

    # Reset title
    page.reset_title()
    assert page.title_entry.text() == "Original Title"
    assert src.title == "Original Title"


def test_main_window_auto_clean_title_setting(win, qtbot):
    from luckytwitch_engine import SourceInfo
    raw_title = "🐍 Pretty face, tragic reactions. BIG ANNOUNCEMENT! 🐍 !gsupps !links !clash"
    src = SourceInfo("https://twitch.tv/videos/1", "1", raw_title, "Streamer", 3600.0, "2026-10-01", "1")

    # With clean_title = True (default)
    win.settings["clean_title"] = True
    win.on_info_ok(src, [], False, "")
    assert win.tab_plan.title_entry.text() == "Pretty face, tragic reactions. BIG ANNOUNCEMENT!"
    assert win.source.title == "Pretty face, tragic reactions. BIG ANNOUNCEMENT!"

    # With clean_title = False
    win.settings["clean_title"] = False
    src2 = SourceInfo("https://twitch.tv/videos/2", "2", raw_title, "Streamer", 3600.0, "2026-10-01", "2")
    win.on_info_ok(src2, [], False, "")
    assert win.tab_plan.title_entry.text() == raw_title
    assert win.source.title == raw_title


