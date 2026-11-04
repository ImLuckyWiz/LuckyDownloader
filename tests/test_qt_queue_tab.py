"""The Qt Queue & log tab (Phase 3): the table, its buttons, the coloured log, the worker thread, the progress bar and
status line, and closing the window. Ports of tests/test_gui_queue_tab.py plus the checks the plan asks for.

Nothing is downloaded: ``qt_ui.queue_runner.run_job`` is replaced by a fake. Message boxes are replaced too (a real
one would wait for a click). Runs on Qt's offscreen platform.
"""

import threading
import types

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import palette, paths, status  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from qt_ui import dialogs, queue_model, theme  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui.queue_model import QueueModel  # noqa: E402
from qt_ui.tabs import queue as queue_tab  # noqa: E402
from qt_ui.tabs.queue import QueueTab  # noqa: E402
from qt_ui.widgets import Card  # noqa: E402

STATUS_ROLE, IID_ROLE = queue_model.STATUS_ROLE, queue_model.IID_ROLE


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
    """Every message box the code opens, as (kind, title, text); yes/no questions answer ``boxes.answer``."""
    calls = types.SimpleNamespace(log=[], answer=True)
    for name in ("info", "warning", "error"):
        monkeypatch.setattr(dialogs, name, lambda parent, title, text, _n=name: calls.log.append((_n, title, text)))
    monkeypatch.setattr(dialogs, "ask_yes_no",
                        lambda parent, title, text: calls.log.append(("yesno", title, text)) or calls.answer)
    return calls


@pytest.fixture()
def tab(qtbot, themed, boxes):
    t = QueueTab()
    qtbot.addWidget(t)
    t.resize(1000, 800)
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


def add(tab, n=1, label="Streamer · Stream", job=None):
    """Queue n stand-in jobs (the job object is never run unless a test replaces run_job)."""
    return [tab.enqueue(job if job is not None else object(), f"{label} {i + 1}", 3, "full VOD + split").iid
            for i in range(n)]


def cell(tab, iid, col, role=Qt.ItemDataRole.DisplayRole):
    return tab.model.index(tab.model.row_of(iid), col).data(role)


def row(tab, iid):
    """(what the Status column shows, the plain status word the row is coloured by)."""
    return cell(tab, iid, 4), cell(tab, iid, 0, STATUS_ROLE)


def log_lines(tab):
    """[(whole line, colour of the time stamp, colour of the message)] for every log line."""
    doc, out = tab.log_view.document(), []
    for i in range(doc.blockCount()):
        block = doc.findBlockByNumber(i)
        if not block.text():
            continue
        cur = QTextCursor(block)
        cur.setPosition(block.position() + 2)  # a character inside «[hh:mm:ss]»
        stamp = cur.charFormat().foreground().color().name()
        cur.setPosition(block.position() + block.length() - 1)  # the last character of the message
        out.append((block.text(), stamp, cur.charFormat().foreground().color().name()))
    return out


def fake_jobs(monkeypatch, fn):
    monkeypatch.setattr("qt_ui.queue_runner.run_job", fn)


def run_all(qtbot, tab):
    """Press «Start queue» and wait until the worker says the run is over."""
    with qtbot.waitSignal(tab.bridge.queue_done, timeout=5000):
        tab.start_queue()


# ------------------------------------------------------------------ the pure helpers (core/status.py)
@pytest.mark.parametrize("text, word", [
    ("queued", "queued"), ("running…", "running"), ("done (3 files)", "done"), ("failed", "failed"),
    ("cancelled", "cancelled"), ("", ""), ("waiting: x", "waiting"),
])
def test_status_word_is_the_first_word(text, word):
    assert status.status_word(text) == word


def test_status_label_puts_an_icon_in_front_of_known_statuses():
    assert status.status_label("queued") == "○ queued"
    assert status.status_label("running…") == "▶ running…"
    assert status.status_label("done (3 files)") == "✓ done (3 files)"
    assert status.status_label("failed") == "✕ failed"
    assert status.status_label("cancelled") == "■ cancelled"
    assert status.status_label("something new") == "something new"  # unknown words are shown as they are


def test_every_status_has_an_icon_and_a_colour():
    assert set(status.STATUS_ICONS) == set(status.STATUS_COLOURS) == {"queued", "running", "done", "failed", "cancelled"}
    assert set(status.FINISHED) == {"done", "failed", "cancelled"}


@pytest.mark.parametrize("msg, kind", [
    ("ERROR: ffmpeg exited with code 1", "err"),
    ("Warning: ffprobe was not found next to ffmpeg", "warn"),
    ("Could not use the segment download (HTTP 403)", "warn"),
    ("Cancelled.", "warn"),
    ("Chat for part 2 failed (the video is still being recorded)", "warn"),
    ("Chat download skipped: it only works for Twitch VODs", "warn"),
    ("Server busy (usher.ttvnw.net), retrying", "warn"),
    ("✔ Big Stream part 1.mp4", "ok"),
    ("yt-dlp 2026.10.01 installed.", "ok"),
    ("yt-dlp is up to date (2026.10.01).", "ok"),
    ("Queued: Streamer · Stream (3 parts, full VOD + split)", "muted"),
    ("yt-dlp: 10% of 4.2GiB at 12MiB/s", "plain"),
    ("Starting job 1/5", "plain"),
    ("", "plain"),
])
def test_log_lines_are_classified(msg, kind):
    assert status.log_kind(msg) == kind


def test_queue_summary_counts_in_a_fixed_order():
    assert status.queue_summary([]) == ""
    assert status.queue_summary(["queued", "queued"]) == "2 queued"
    assert status.queue_summary(["done", "failed", "queued", "running", "cancelled", "done"]) == \
        "1 running  ·  1 queued  ·  2 done  ·  1 failed  ·  1 cancelled"
    assert status.queue_summary(["done (3 files)", "running…"]) == "1 running  ·  1 done"


# ------------------------------------------------------------------ the list
def test_the_empty_queue_says_what_to_do_and_the_button_goes_to_the_plan_tab(tab, qtbot):
    assert tab.empty.shown
    assert tab.empty.texts() == ["Nothing in the queue yet", "Set your cut points in the Plan tab and press «Add to queue»."]
    assert tab.empty.button.text() == "Go to the Plan tab"
    assert tab.summary_label.text() == ""
    with qtbot.waitSignal(tab.plan_requested, timeout=1000):
        tab.empty.button.click()


def test_in_the_window_the_empty_state_button_selects_the_plan_tab(win):
    win.tabs.setCurrentWidget(win.tab_queue)
    win.tab_queue.empty.button.click()
    assert win.tabs.currentWidget() is win.tab_plan


def test_a_queued_job_is_listed_with_its_icon_colour_and_count(tab):
    (iid,) = add(tab)
    assert not tab.empty.shown
    assert row(tab, iid) == ("○ queued", "queued")
    assert tab.items[0].status == "queued"  # the stored status stays the plain word
    assert cell(tab, iid, 0, Qt.ItemDataRole.ForegroundRole).name() == QColor(palette.MUTED).name()
    assert tab.summary_label.text() == "1 queued"
    assert [cell(tab, iid, c) for c in range(4)] == ["1", "Streamer · Stream 1", "3", "full VOD + split"]


@pytest.mark.parametrize("text, word, shown", [
    ("running…", "running", "▶ running…"),
    ("done (3 files)", "done", "✓ done (3 files)"),
    ("failed", "failed", "✕ failed"),
    ("cancelled", "cancelled", "■ cancelled"),
])
def test_a_job_changes_colour_and_icon_with_its_status(tab, text, word, shown):
    (iid,) = add(tab)
    tab.set_item_status(iid, text)
    assert row(tab, iid) == (shown, word)
    assert tab.items[0].status == word
    assert cell(tab, iid, 1, Qt.ItemDataRole.ForegroundRole).name() == QColor(status.STATUS_COLOURS[word]).name()
    assert tab.summary_label.text() == f"1 {word}"


def test_the_row_colours_match_the_palette(tab):
    (iid,) = add(tab)
    for word, colour in status.STATUS_COLOURS.items():
        tab.set_item_status(iid, word)
        assert cell(tab, iid, 4, Qt.ItemDataRole.ForegroundRole).name() == QColor(colour).name()
    assert status.STATUS_COLOURS["done"] == palette.OK and status.STATUS_COLOURS["failed"] == palette.ERR
    tab.set_item_status(iid, "weird words")  # a word with no colour keeps the default text colour
    assert cell(tab, iid, 4, Qt.ItemDataRole.ForegroundRole) is None
    assert cell(tab, iid, 4) == "weird words"


def test_the_summary_follows_every_change_of_the_queue(tab):
    a, b, c = add(tab, 3)
    tab.set_item_status(a, "done (1 files)")
    tab.set_item_status(b, "failed")
    assert tab.summary_label.text() == "1 queued  ·  1 done  ·  1 failed"
    tab.clear_finished()
    assert [it.iid for it in tab.items] == [c]
    assert tab.summary_label.text() == "1 queued"
    tab.select_item(c)
    tab.remove_selected()
    assert not tab.items and tab.empty.shown and tab.summary_label.text() == ""


def test_a_running_job_cannot_be_removed(tab, boxes):
    (iid,) = add(tab)
    tab.set_item_status(iid, "running…")
    tab.select_item(iid)
    tab.remove_selected()
    assert len(tab.items) == 1
    assert boxes.log == [("info", "Running", "Cancel the running job first.")]


def test_remove_selected_without_a_selection_does_nothing(tab, boxes):
    add(tab, 2)
    tab.remove_selected()
    assert len(tab.items) == 2 and boxes.log == []


def test_row_ids_are_never_used_twice_and_the_number_column_is_not_renumbered(tab):
    a, b, c = add(tab, 3)
    tab.select_item(a)
    tab.remove_selected()
    (d,) = add(tab, 1, label="Later")
    assert len({a, b, c, d}) == 4
    assert [cell(tab, i, 0) for i in (b, c, d)] == ["2", "3", "3"]  # as in tkinter: the number is set when the row is added


def test_headings_line_up_with_their_columns(tab):
    model = tab.model
    assert [model.headerData(c, Qt.Orientation.Horizontal) for c in range(5)] == ["#", "Video", "Parts", "Strategy", "Status"]
    (iid,) = add(tab)
    for col in range(5):
        assert model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole) == \
            cell(tab, iid, col, Qt.ItemDataRole.TextAlignmentRole)
    head = tab.table.horizontalHeader()
    assert [head.sectionSize(c) for c in (0, 2, 3, 4)] == [40, 70, 140, 200]
    assert head.sectionResizeMode(1) == head.ResizeMode.Stretch  # only «Video» stretches


def test_the_table_cannot_be_edited_and_selects_whole_rows_one_at_a_time(tab):
    a, b = add(tab, 2)
    assert tab.table.editTriggers() == tab.table.EditTrigger.NoEditTriggers
    tab.select_item(a)
    tab.select_item(b)
    assert tab.selected_iid() == b and len(tab.table.selectionModel().selectedRows()) == 1


# ------------------------------------------------------------------ running (worker thread, fake run_job)
def test_the_queue_still_runs_on_the_plain_status_words(tab, qtbot, monkeypatch):
    fake_jobs(monkeypatch, lambda job, ctx: ["a.mp4", "b.mp4"])
    a, b = add(tab, 2)
    tab.set_item_status(b, "done (1 files)")  # already finished: must not run again
    run_all(qtbot, tab)
    assert row(tab, a) == ("✓ done (2 files)", "done")
    assert row(tab, b) == ("✓ done (1 files)", "done")
    assert tab.items[0].files == ["a.mp4", "b.mp4"]
    assert tab.summary_label.text() == "2 done"
    assert tab.start_btn.isEnabled() and not tab.cancel_btn.isEnabled()


def test_a_failing_job_is_marked_failed_logged_in_red_and_the_run_goes_on(tab, qtbot, monkeypatch):
    def run(job, ctx):
        if job == "bad":
            raise RuntimeError("ffmpeg exited with code 1")
        return ["ok.mp4"]

    fake_jobs(monkeypatch, run)
    bad = add(tab, 1, job="bad")[0]
    good = add(tab, 1, label="Good", job="fine")[0]
    run_all(qtbot, tab)
    assert row(tab, bad) == ("✕ failed", "failed")
    assert row(tab, good) == ("✓ done (1 files)", "done")
    errors = [line for line in log_lines(tab) if line[0].endswith("ERROR: ffmpeg exited with code 1")]
    assert errors and errors[0][2] == QColor(palette.ERR).name()


def test_a_cancelled_job_ends_the_run_and_the_rest_stays_queued(tab, qtbot, monkeypatch):
    started = threading.Event()

    def run(job, ctx):
        started.set()
        ctx.cancel_event.wait(5)
        ctx.check_cancel()
        return []

    fake_jobs(monkeypatch, run)
    first, second = add(tab, 2)
    seen = []
    tab.status_message.connect(seen.append)
    with qtbot.waitSignal(tab.bridge.queue_done, timeout=5000):
        tab.start_queue()
        assert started.wait(5)
        qtbot.waitUntil(lambda: tab.items[0].status == "running", timeout=2000)
        assert tab.cancel_btn.isEnabled() and not tab.start_btn.isEnabled()
        tab.cancel_current()
    assert seen[-1] == "Cancelling…"
    assert row(tab, first) == ("■ cancelled", "cancelled")
    assert row(tab, second) == ("○ queued", "queued")
    assert log_lines(tab)[-1][0].endswith("Cancelled.") and log_lines(tab)[-1][2] == QColor(palette.WARN).name()
    assert tab.start_btn.isEnabled() and not tab.cancel_btn.isEnabled()
    assert tab.runner.ctx is None


def test_cancel_with_nothing_running_does_nothing(tab):
    seen = []
    tab.status_message.connect(seen.append)
    tab.cancel_current()
    assert seen == []


def test_start_with_nothing_queued_says_so(tab):
    seen = []
    tab.status_message.connect(seen.append)
    tab.start_queue()
    add(tab)
    tab.set_item_status(tab.items[0].iid, "done")
    tab.start_queue()
    assert seen == ["Nothing queued.", "Nothing queued."] and not tab.runner.is_running()


def test_start_waits_while_the_tools_or_a_chat_overlay_are_busy(tab, monkeypatch):
    calls = []
    fake_jobs(monkeypatch, lambda job, ctx: calls.append(job) or [])
    add(tab)
    seen = []
    tab.status_message.connect(seen.append)
    tab.blocked_reason = lambda: "Still preparing yt-dlp / ffmpeg, start the queue again in a moment."
    tab.start_queue()
    assert seen == ["Still preparing yt-dlp / ffmpeg, start the queue again in a moment."]
    assert calls == [] and tab.items[0].status == "queued" and tab.start_btn.isEnabled()


def test_the_window_gives_the_two_busy_reasons(win):
    assert win.queue_blocked_reason() == ""
    win.tools_busy = True
    assert win.queue_blocked_reason() == "Still preparing yt-dlp / ffmpeg, start the queue again in a moment."
    win.tools_busy, win.saved_chat_busy = False, True
    assert win.queue_blocked_reason() == "A chat overlay is being drawn, start the queue when it finishes."


def test_starting_shows_the_queue_tab_and_pressing_start_twice_runs_nothing_twice(win, qtbot, monkeypatch):
    release, runs = threading.Event(), []

    def run(job, ctx):
        runs.append(job)
        release.wait(5)
        return []

    fake_jobs(monkeypatch, run)
    tab = win.tab_queue
    add(tab)
    win.tabs.setCurrentWidget(win.tab_search)
    with qtbot.waitSignal(tab.bridge.queue_done, timeout=5000):
        tab.start_queue()
        assert win.tabs.currentWidget() is tab
        tab.start_queue()  # a second press while it runs is ignored
        release.set()
    assert len(runs) == 1


def test_a_worker_reports_only_through_signals_and_the_slots_run_on_the_gui_thread(tab, qtbot, monkeypatch):
    main = threading.current_thread()
    where = []
    real_add = tab.log_view.add_line
    monkeypatch.setattr(tab.log_view, "add_line", lambda msg: (where.append(threading.current_thread()), real_add(msg)))

    def run(job, ctx):
        ctx.log("from the worker")
        return []

    fake_jobs(monkeypatch, run)
    add(tab)
    run_all(qtbot, tab)
    assert where and all(t is main for t in where)
    assert any(line[0].endswith("from the worker") for line in log_lines(tab))


# ------------------------------------------------------------------ the log
def test_log_lines_get_a_muted_time_stamp_and_a_colour_by_kind(tab):
    for msg in ("Starting job 1/1", "ERROR: it broke", "Cancelled.", "✔ part 1.mp4", "Queued: x (1 parts, y)"):
        tab.log(msg)
    lines = log_lines(tab)
    muted = QColor(palette.MUTED).name()
    assert [stamp for _, stamp, _ in lines] == [muted] * 5  # the «[hh:mm:ss]» part is muted
    assert [colour for _, _, colour in lines] == [QColor(c).name() for c in (
        palette.FG, palette.ERR, palette.WARN, palette.OK, palette.MUTED)]
    assert lines[0][0].startswith("[") and lines[0][0][3] == ":" and lines[0][0][9:11] == "] "


def test_the_log_is_read_only_and_follows_the_newest_line(tab, qtbot):
    for i in range(80):
        tab.log(f"line {i}")
    assert tab.log_view.isReadOnly()
    qtbot.waitUntil(lambda: tab.log_view.verticalScrollBar().value() == tab.log_view.verticalScrollBar().maximum())
    assert tab.log_view.verticalScrollBar().maximum() > 0


def test_clear_log_empties_it_and_it_keeps_working(tab):
    tab.log("something")
    tab.clear_log()
    assert tab.log_view.toPlainText().strip() == "" and tab.log_view.isReadOnly()
    tab.log("after")
    assert "after" in tab.log_view.toPlainText()


def test_copy_log_puts_the_text_on_the_clipboard(tab, qtbot):
    tab.log("first")
    tab.log("ERROR: second")
    seen = []
    tab.status_message.connect(seen.append)
    tab.copy_btn.click()
    clip = QApplication.clipboard().text()
    assert clip.splitlines()[-2].endswith("first") and clip.splitlines()[-1].endswith("ERROR: second")
    assert not clip.endswith("\n")
    assert seen == ["Log copied to the clipboard."]


def test_the_log_buttons_work(tab):
    tab.log("a")
    tab.clear_log_btn.click()
    assert tab.log_view.toPlainText().strip() == ""


def test_a_queued_job_is_logged_as_muted_queued_line(tab):
    add(tab)
    text, _, colour = log_lines(tab)[-1]
    assert text.endswith("Queued: Streamer · Stream 1 (3 parts, full VOD + split)")
    assert colour == QColor(palette.MUTED).name()


def test_the_two_sections_are_cards(tab):
    cards = [w for w in tab.scroll.body.children() if isinstance(w, Card)]
    assert [c.title_label.text() for c in cards] == ["Queue", "Log"]
    assert [b.text() for b in (tab.start_btn, tab.cancel_btn, tab.remove_btn, tab.clear_btn, tab.folder_btn)] == [
        "Start queue", "Cancel current", "Remove selected", "Clear finished", "Open folder"]
    assert tab.start_btn.property("variant") == "accent" and not tab.cancel_btn.isEnabled()
    assert tab.table.parentWidget() is not None and tab.log_view.parentWidget() is not None


def test_the_tab_scrolls_when_the_window_is_short(tab, qtbot):
    tab.resize(1000, 300)
    qtbot.waitUntil(lambda: tab.scroll.is_scrollable(), timeout=2000)


# ------------------------------------------------------------------ the folders
def test_open_folder_highlights_the_first_file_of_the_selected_item(tab, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(queue_tab, "open_in_file_manager", lambda path, select=False: opened.append((path, select)))
    f = tmp_path / "part1.mp4"
    f.write_text("x")
    a, b = add(tab, 2)
    tab.items[0].files = [str(f)]
    tab.select_item(a)
    tab.open_queue_folder()
    assert opened == [(f, True)]
    tab.select_item(b)  # a selected item that has no files yet: its output folder
    job = types.SimpleNamespace(source=None, opts=types.SimpleNamespace(out_dir=str(tmp_path / "out")))
    tab.items[1].job = job
    tab.open_queue_folder()
    assert opened[-1] == (tmp_path / "out", False) and (tmp_path / "out").is_dir()


def test_open_folder_without_a_selection_uses_the_last_finished_item_then_the_output_folder(tab, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(queue_tab, "open_in_file_manager", lambda path, select=False: opened.append((path, select)))
    tab.output_dir = lambda: str(tmp_path / "downloads")
    tab.open_queue_folder()  # nothing queued: the output folder, created if missing
    assert opened == [(tmp_path / "downloads", False)] and (tmp_path / "downloads").is_dir()
    f = tmp_path / "done.mp4"
    f.write_text("x")
    add(tab, 2)
    tab.items[0].files = [str(f)]
    tab.open_queue_folder()
    assert opened[-1] == (f, True)


def test_open_folder_tells_the_user_when_it_cannot(tab, tmp_path, monkeypatch, boxes):
    def boom(path, select=False):
        raise OSError("no file manager")

    monkeypatch.setattr(queue_tab, "open_in_file_manager", boom)
    tab.output_dir = lambda: str(tmp_path / "x")
    tab.open_queue_folder()
    kind, title, text = boxes.log[-1]
    assert (kind, title) == ("info", "Open folder") and "no file manager" in text and str(tmp_path / "x") in text


# ------------------------------------------------------------------ progress bar and status line (main window)
def test_progress_is_determinate_with_a_percentage_and_indeterminate_when_unknown(win):
    win.set_progress(0.5, "Downloading")
    assert (win.progress.minimum(), win.progress.maximum(), win.progress.value()) == (0, 100, 50)
    assert win.status_label.text() == "Downloading  —  50%"
    win.set_progress(-1, "Waiting for the stream")
    assert (win.progress.minimum(), win.progress.maximum()) == (0, 0)  # busy: moves back and forth
    assert win.status_label.text() == "Waiting for the stream"
    win.set_progress(0.07, "Cutting")
    assert (win.progress.minimum(), win.progress.maximum(), win.progress.value()) == (0, 100, 7)
    assert win.status_label.text() == "Cutting  —  7%"


def test_the_job_prefix_only_shows_when_there_are_several_jobs(win):
    win.bridge.job.emit(2, 3)
    win.set_progress(0.1, "Cutting")
    assert win.status_label.text() == "Job 2/3: Cutting  —  10%"
    win.bridge.job.emit(1, 1)
    win.set_progress(0.2, "Cutting")
    assert win.status_label.text() == "Cutting  —  20%"


def test_a_whole_run_updates_rows_progress_and_status(win, qtbot, monkeypatch):
    statuses = []

    def run(job, ctx):
        ctx.stage(0.0, 1.0, f"Part of {job}")
        ctx.report(0.5)
        ctx.log(f"working on {job}")
        return [f"{job}.mp4"]

    fake_jobs(monkeypatch, run)
    tab = win.tab_queue
    a, b = add(tab, 1, job="one")[0], add(tab, 1, label="Other", job="two")[0]
    win.bridge.progress.connect(lambda f, t: statuses.append(win.status_label.text()))
    with qtbot.waitSignal(win.bridge.queue_done, timeout=5000):
        tab.start_queue()
    assert row(tab, a) == ("✓ done (1 files)", "done") and row(tab, b) == ("✓ done (1 files)", "done")
    assert any(s.startswith("Job 2/2: Part of two") for s in statuses)  # the prefix showed while the second one ran
    assert win.status_label.text() == "Queue finished."
    assert win.progress.value() == 0 and win.progress.maximum() == 100
    assert tab.start_btn.isEnabled() and not tab.cancel_btn.isEnabled()
    assert any(line[0].endswith("working on two") for line in log_lines(tab))


def test_the_window_log_goes_to_the_log_view(win):
    win.log("hello")
    assert win.tab_queue.log_view.toPlainText().strip().endswith("hello")


# ------------------------------------------------------------------ closing the window
def test_closing_saves_the_settings_and_removes_the_heartbeat_file(win):
    paths.BEAT_PATH.write_text("beat")
    win.settings["threads"] = 3
    assert win.close()
    import json
    assert json.loads(paths.SETTINGS_PATH.read_text(encoding="utf-8"))["threads"] == 3
    assert not paths.BEAT_PATH.exists()


def test_closing_without_a_heartbeat_file_is_fine(win):
    paths.BEAT_PATH.unlink(missing_ok=True)
    assert not paths.BEAT_PATH.exists()
    assert win.close()


def test_a_window_made_without_settings_never_overwrites_the_saved_file(qtbot, themed):
    paths.SETTINGS_PATH.write_text('{"threads": 5}', encoding="utf-8")
    w = mw.MainWindow()
    qtbot.addWidget(w)
    w.show()
    assert w.close()
    assert paths.SETTINGS_PATH.read_text(encoding="utf-8") == '{"threads": 5}'


def _start_a_job_that_waits(win, monkeypatch):
    started, cancelled = threading.Event(), threading.Event()

    def run(job, ctx):
        started.set()
        if ctx.cancel_event.wait(10):
            cancelled.set()
        ctx.check_cancel()
        return []

    fake_jobs(monkeypatch, run)
    add(win.tab_queue)
    win.tab_queue.start_queue()
    assert started.wait(5)
    return cancelled


def test_closing_while_a_job_runs_asks_first_and_stays_open_on_no(win, boxes, monkeypatch):
    cancelled = _start_a_job_that_waits(win, monkeypatch)
    boxes.answer = False
    paths.BEAT_PATH.write_text("beat")
    assert not win.close()
    assert boxes.log[-1] == ("yesno", "Quit", "A job is running. Cancel it and quit?")
    assert win.isVisible() and paths.BEAT_PATH.exists() and not paths.SETTINGS_PATH.exists()
    assert not cancelled.is_set() and win.tab_queue.runner.is_running()
    boxes.answer = True  # let it finish so the thread ends
    assert win.close()
    assert win.tab_queue.runner.worker.join(5) is None and cancelled.is_set()


def test_closing_while_a_job_runs_cancels_it_saves_and_removes_the_heartbeat_on_yes(win, boxes, monkeypatch):
    cancelled = _start_a_job_that_waits(win, monkeypatch)
    paths.BEAT_PATH.write_text("beat")
    boxes.answer = True
    assert win.close()
    win.tab_queue.runner.worker.join(5)
    assert cancelled.is_set() and not win.tab_queue.runner.is_running()
    assert paths.SETTINGS_PATH.exists() and not paths.BEAT_PATH.exists()


def test_closing_cancels_a_running_tools_setup(win):
    ctx = types.SimpleNamespace(cancelled=False, cancel=lambda: setattr(ctx, "cancelled", True))
    win.tools_ctx = ctx
    assert win.close()
    assert ctx.cancelled


def test_the_stub_handlers_are_still_stubs_and_the_window_still_starts_on_the_right_tab(qtbot, themed):
    no_client = mw.MainWindow(client=None)
    qtbot.addWidget(no_client)
    assert no_client.tabs.currentWidget() is no_client.tab_plan
    assert isinstance(no_client.tab_queue, QueueTab) and no_client.tab_queue.bridge is no_client.bridge


def test_the_tab_order_has_nothing_decorative(tab):
    """tkinter test_tab_order_of_search_queue_and_options_has_nothing_decorative: the scroll area around the tab
    must not take the keyboard (found in Phase 4, when the Search tab was checked the same way)."""
    from PySide6.QtWidgets import QAbstractScrollArea, QLineEdit, QPushButton

    assert tab.scroll.focusPolicy() == Qt.FocusPolicy.NoFocus
    stops, w = [], tab.start_btn
    for _ in range(200):
        stops.append(w)
        w = w.nextInFocusChain()
        if w is tab.start_btn:
            break
    focusable = [x for x in stops if tab.isAncestorOf(x) and x.isVisibleTo(tab) and x.focusPolicy() != Qt.FocusPolicy.NoFocus]
    assert focusable
    for x in focusable:
        assert isinstance(x, (QPushButton, QAbstractScrollArea, QLineEdit)) and x is not tab.scroll, x


# ------------------------------------------------------------------ Phase 9c: Rich rows, header summary, log drawer, reorder & retry
def test_header_counter_tracks_done_running_waiting_and_failed(tab):
    assert tab.counter_label.text() == "0 done · 0 running · 0 waiting · 0 failed"
    a, b, c, d = add(tab, 4)
    assert tab.counter_label.text() == "0 done · 0 running · 4 waiting · 0 failed"

    tab.set_item_status(a, "done (1 file)")
    tab.set_item_status(b, "running…")
    tab.set_item_status(c, "failed")
    assert tab.counter_label.text() == "1 done · 1 running · 1 waiting · 1 failed"
    assert tab.retry_btn.isEnabled()


def test_delegate_paints_rich_row_progress_and_inline_open_button(tab, qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent, QPixmap
    from PySide6.QtWidgets import QStyleOptionViewItem

    thumb = QPixmap(64, 36)
    thumb.fill(QColor(palette.ACCENT))
    it = tab.enqueue(object(), "Streamer · Great Stream", 3, "full VOD + split", thumb=thumb)
    assert it.thumb is not None

    # Running state with progress bar
    tab.set_item_status(it.iid, "running…")
    tab.set_running_progress(0.45, "Downloading part 2/3")
    assert tab.queue_progress.isVisible()
    assert tab.queue_progress.value() == 45
    assert it.progress == pytest.approx(0.45)

    img = tab.table.viewport().grab().toImage()
    assert not img.isNull()

    # Done state exposes inline Open button on column 4
    out_file = tmp_path / "part1.mp4"
    out_file.write_bytes(b"ok")
    it.files = [str(out_file)]
    tab.set_item_status(it.iid, "done (1 file)")
    tab.set_running_progress(0.0, "")
    assert not tab.queue_progress.isVisible()

    idx = tab.model.index(0, 4)
    rect = tab.table.visualRect(idx)
    btn_rect = tab.delegate.open_button_rect(rect)
    opened = []
    monkeypatch.setattr(queue_tab, "open_in_file_manager", lambda p, select=False: opened.append((p, select)))

    ev = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(btn_rect.center()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    opt = QStyleOptionViewItem()
    opt.rect = rect
    assert tab.delegate.editorEvent(ev, tab.model, opt, idx)
    assert opened == [(out_file, True)]


def test_integrated_log_console_and_toolbar(tab):
    assert tab.log_view.isVisible()
    assert tab.log_view.isReadOnly()
    assert "all" in tab.filter_buttons
    assert tab.filter_buttons["warn"].text() == "Warnings"
    assert tab.filter_buttons["err"].text() == "Errors"

    tab.log("Fetching manifest")
    assert "Fetching manifest" in tab.log_view.toPlainText()

    tab.log("Warning: slow segment")
    assert "Warning: slow segment" in tab.log_view.toPlainText()

    tab.log("ERROR: ffmpeg exited with code 1")
    assert "ERROR: ffmpeg exited with code 1" in tab.log_view.toPlainText()
    assert len(tab.log_view.entries) == 3


def test_log_severity_chips_search_autoscroll_and_save_log(tab, monkeypatch, tmp_path):
    tab.log("Normal line one")
    tab.log("Warning: check disk space")
    tab.log("ERROR: download failed")
    assert len(log_lines(tab)) == 3

    tab.set_log_filter("warn")
    lines = [text for text, _, _ in log_lines(tab)]
    assert len(lines) == 1 and "Warning: check disk space" in lines[0]

    tab.set_log_filter("err")
    lines = [text for text, _, _ in log_lines(tab)]
    assert len(lines) == 1 and "ERROR: download failed" in lines[0]

    tab.set_log_filter("all")
    tab.log_search_entry.setText("disk")
    lines = [text for text, _, _ in log_lines(tab)]
    assert len(lines) == 1 and "Warning: check disk space" in lines[0]

    tab.log_search_entry.setText("")
    assert len(log_lines(tab)) == 3

    # Autoscroll toggle
    assert not tab.log_view.pause_autoscroll
    tab.autoscroll_btn.click()
    assert tab.log_view.pause_autoscroll
    tab.autoscroll_btn.click()
    assert not tab.log_view.pause_autoscroll

    # Save log exports the filtered/full text to disk
    dest = tmp_path / "saved_queue.log"
    monkeypatch.setattr(dialogs, "save_file", lambda *a, **kw: str(dest))
    tab.save_log()
    saved = dest.read_text(encoding="utf-8")
    assert "Normal line one" in saved
    assert "Warning: check disk space" in saved
    assert "ERROR: download failed" in saved


def test_retry_and_reorder_waiting_jobs(tab, qtbot, monkeypatch):
    from qt_ui import queue_runner

    a, b, c = add(tab, 3)
    tab.set_item_status(a, "failed")
    tab.set_item_status(b, "cancelled")

    # Retry failed/cancelled resets them to queued
    tab.retry_failed_or_selected()
    assert [it.status for it in tab.items] == ["queued", "queued", "queued"]
    # c was already queued at index 0 after a and b moved to the end
    assert [it.iid for it in tab.items] == [c, a, b]

    # Select 'b' (row 2) and move it up twice to row 0
    tab.table.selectRow(2)
    tab.move_selected(-1)
    assert [it.iid for it in tab.items] == [c, b, a]
    tab.move_selected(-1)
    assert [it.iid for it in tab.items] == [b, c, a]

    # Live reordering while job 1 is running affects which job runs next
    order = []
    first_started = threading.Event()
    allow_finish = threading.Event()

    def fake_run(job, ctx):
        order.append(job)
        if len(order) == 1:
            first_started.set()
            allow_finish.wait(timeout=3.0)
        return ["out.mp4"]

    monkeypatch.setattr(queue_runner, "run_job", fake_run)
    for it in tab.items:
        it.job = f"job-{it.iid}"

    tab.start_queue()
    assert first_started.wait(timeout=2.0)
    # While 'b' is running, swap waiting 'c' and 'a' so 'a' goes before 'c'
    assert tab.model.move_item(a, -1)
    allow_finish.set()
    qtbot.waitUntil(lambda: not tab.runner.is_running(), timeout=3000)
    assert order == [f"job-{b}", f"job-{a}", f"job-{c}"]


def test_queue_model_clear_all(qtbot):
    model = QueueModel()
    model.add(object(), "Video 1", 1, "full video")
    model.add(object(), "Video 2", 1, "full video")
    model.add(object(), "Video 3", 1, "full video")
    assert len(model.items) == 3

    # With keep_running=True when Video 2 is running
    model.items[1].status = "running"
    removed = model.clear_all(keep_running=True)
    assert len(removed) == 2
    assert len(model.items) == 1
    assert model.items[0].label == "Video 2"

    # With keep_running=False
    removed_all = model.clear_all(keep_running=False)
    assert len(removed_all) == 1
    assert len(model.items) == 0


def test_queue_tab_clear_all_button(qtbot, monkeypatch):
    tab = QueueTab()
    qtbot.addWidget(tab)
    tab.enqueue(object(), "Item 1", 1, "full video")
    tab.enqueue(object(), "Item 2", 1, "full video")
    assert len(tab.items) == 2

    # User cancels clear confirmation dialog
    monkeypatch.setattr("qt_ui.dialogs.ask_yes_no", lambda parent, title, msg: False)
    tab.clear_all_jobs()
    assert len(tab.items) == 2

    # User confirms clear confirmation dialog
    monkeypatch.setattr("qt_ui.dialogs.ask_yes_no", lambda parent, title, msg: True)
    tab.clear_all_jobs()
    assert len(tab.items) == 0


def test_queue_tab_multi_selection_and_delete_key(qtbot):
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtGui import QKeyEvent
    tab = QueueTab()
    qtbot.addWidget(tab)
    i1 = tab.enqueue(object(), "Item 1", 1, "full video").iid
    i2 = tab.enqueue(object(), "Item 2", 1, "full video").iid
    i3 = tab.enqueue(object(), "Item 3", 1, "full video").iid
    assert len(tab.items) == 3

    # Multi-select row 0 and row 2 (Item 1 and Item 3)
    sm = tab.table.selectionModel()
    sm.select(tab.model.index(0, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    sm.select(tab.model.index(2, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert set(tab.selected_iids()) == {i1, i3}

    # Simulate pressing Delete key
    press_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    tab.eventFilter(tab.table, press_event)
    assert len(tab.items) == 1
    assert tab.items[0].iid == i2


def test_queue_tab_auto_thumbnail_fetch(qtbot, tmp_path):
    class FakeSource:
        thumbnail = ""

    class FakeJob:
        def __init__(self):
            self.source = FakeSource()

    tab = QueueTab()
    qtbot.addWidget(tab)

    # 1. Local file thumbnail
    test_img = tmp_path / "thumb.png"
    pm = QPixmap(10, 10)
    pm.fill(Qt.GlobalColor.red)
    pm.save(str(test_img))

    job1 = FakeJob()
    job1.source.thumbnail = str(test_img)
    it1 = tab.enqueue(job1, "Local Thumb Job", 1, "full video")
    assert it1.thumb is not None
    assert isinstance(it1.thumb, QPixmap)

    # 2. HTTP URL thumbnail fetched via thumb_ready
    job2 = FakeJob()
    job2.source.thumbnail = "https://example.com/fake.jpg"
    it2 = tab.enqueue(job2, "Remote Thumb Job", 1, "full video")
    assert it2.thumb is None  # Initial state before background fetch arrives

    # When thumb_ready signal fires
    tab._on_thumb_ready(it2.iid, str(test_img))
    assert it2.thumb is not None
    assert isinstance(it2.thumb, QPixmap)


def test_queue_persistence_round_trip_and_running_recovery(tmp_path):
    from core.chapters import ClipFilter
    from core.job import Job, JobOptions
    from core.source_info import GameSegment, SourceInfo, VideoFormat

    state_file = tmp_path / "queue_state.json"
    src1 = SourceInfo(
        url="https://www.twitch.tv/videos/111",
        id="111",
        title="Stream One",
        uploader="alice",
        duration=3600.0,
        date="2026-04-11",
        twitch_vod_id="111",
        segments=[GameSegment(0.0, 1800.0, "Chess")],
        formats=[VideoFormat(format_id="1080p60", height=1080, fps=60.0)],
        site="twitch",
    )
    opts1 = JobOptions(cut_text="0:00:00 - 0:10:00", out_dir=str(tmp_path), clip_filter=ClipFilter(min_views=5))
    job1 = Job(source=src1, opts=opts1, clips=[{"id": "c1", "title": "Nice play"}])

    src2 = SourceInfo(
        url="https://www.twitch.tv/videos/222",
        id="222",
        title="Stream Two",
        uploader="bob",
        duration=1200.0,
        date="2026-04-11",
        twitch_vod_id="222",
        site="twitch",
    )
    job2 = Job(source=src2, opts=JobOptions(cut_text="0:00:00 - end", out_dir=str(tmp_path)))

    model = QueueModel()
    it1 = model.add(job1, "alice · Stream One", 1, "only the parts")
    it2 = model.add(job2, "bob · Stream Two", 1, "full VOD + split")
    # Simulate it1 was running when app closed/crashed
    model.set_status(it1.iid, "running")
    model.save_state(state_file)

    assert state_file.is_file()

    restored_model = QueueModel()
    restored = restored_model.load_state(state_file, only_unfinished=True)
    assert len(restored) == 2
    # Running item is recovered as queued so it can be resumed
    assert restored_model.items[0].status == "queued"
    assert restored_model.items[0].shown_status == "queued"
    assert isinstance(restored_model.items[0].job, Job)
    assert restored_model.items[0].job.source.url == "https://www.twitch.tv/videos/111"
    assert restored_model.items[0].job.opts.clip_filter.min_views == 5
    assert restored_model.items[1].job.source.url == "https://www.twitch.tv/videos/222"


def test_main_window_restores_unfinished_queue_on_startup(qtbot, tmp_path, monkeypatch):
    from core import paths
    from core.job import Job, JobOptions
    from core.source_info import SourceInfo
    from qt_ui.main_window import MainWindow

    state_file = paths.QUEUE_STATE_FILE
    src = SourceInfo(
        url="https://www.twitch.tv/videos/999",
        id="999",
        title="Saved VOD",
        uploader="streamer",
        duration=600.0,
        date="2026-04-11",
        twitch_vod_id="999",
    )
    job = Job(source=src, opts=JobOptions(cut_text="0:00:00 - end", out_dir=str(tmp_path)))

    seed_model = QueueModel()
    it = seed_model.add(job, "streamer · Saved VOD", 1, "full VOD + split")
    seed_model.set_status(it.iid, "running")
    seed_model.save_state(state_file)

    w = MainWindow(settings={"out_dir": str(tmp_path)}, client=None)
    qtbot.addWidget(w)
    assert len(w.tab_queue.items) == 1
    assert w.tab_queue.items[0].label == "streamer · Saved VOD"
    assert w.tab_queue.items[0].status == "queued"
    w.close()
