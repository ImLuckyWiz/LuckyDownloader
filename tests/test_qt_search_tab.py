"""The Qt Search tab (Phase 4): the sign-in banner, the three lists with their messages, searching, picking a
streamer, the VOD table with its thumbnails, paging, and the generation counter that drops stale answers.
Ports of tests/test_gui_search_tab.py plus the checks the plan asks for.

Nothing touches the network: ``search_channels``, ``fetch_videos`` and ``fetch_thumbnail`` are replaced by fakes, and
message boxes are replaced too (a real one would wait for a click). Runs on Qt's offscreen platform.
"""

import json
import threading
import types

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPoint, Qt, QThread  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QListView, QPushButton, QTableView  # noqa: E402

from core import paths  # noqa: E402
from core import search as core_search  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from qt_ui import dialogs, search_models, theme, thumbs  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui.search_models import THUMB_MARGIN, ThumbCache, VodModel  # noqa: E402
from qt_ui.tabs import search as search_tab  # noqa: E402
from qt_ui.tabs.search import SearchTab  # noqa: E402
from qt_ui.widgets import ComboBox  # noqa: E402

RESULTS = [
    dict(id="1", login="streamer", name="Streamer", live=True),
    dict(id="2", login="other", name="Other One", live=False),
]


def vod(i, **kw):
    return dict(title=f"Stream {i}", date="2026-10-01", duration=3600.0 + i, views=10 * i, thumb="",
                url=f"https://www.twitch.tv/videos/{i}", **kw)


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
    """Every message box the code opens, as (kind, title, text)."""
    calls = types.SimpleNamespace(log=[])
    for name in ("info", "warning", "error"):
        monkeypatch.setattr(dialogs, name, lambda parent, title, text, _n=name: calls.log.append((_n, title, text)))
    return calls


@pytest.fixture()
def session():
    """The Twitch client the tab sees (None = signed out) and how often the tab asked for it to be made again."""
    return types.SimpleNamespace(client=None, reloads=0)


@pytest.fixture()
def tab(qtbot, themed, boxes, session):
    t = SearchTab()
    t.get_client = lambda: session.client

    def reload():
        session.reloads += 1

    t.reload_client = reload
    qtbot.addWidget(t)
    t.resize(1000, 800)
    t.show()
    qtbot.waitExposed(t)
    t.update_search_state()
    yield t
    t.shutdown()


@pytest.fixture()
def win(qtbot, themed, boxes):
    w = mw.MainWindow(settings=dict(DEFAULTS), client=object())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    yield w
    w.tab_search.shutdown()


def sign_in(tab, session):
    session.client = object()  # anything truthy: the tab only asks «is there a session?»
    tab.update_search_state()


def row_texts(view: QListView) -> list[str]:
    m = view.model()
    return [m.index(r, 0).data() for r in range(m.rowCount())]


def png(path, colour="#3366cc", size=(320, 180)):
    img = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    assert img.save(str(path))
    return str(path)


def load_vods(tab, videos, cursor=None, channel=None):
    tab.sv_channel, tab.sv_gen = channel or RESULTS[0], 1
    tab.on_videos_ok(1, videos, cursor)


# ------------------------------------------------------------------ the sign-in banner
def test_without_a_session_the_banner_shows_and_searching_is_off(tab):
    assert tab.signin_bar.isVisibleTo(tab)
    assert not tab.search_btn.isEnabled()
    assert tab.sv_empty.texts()[0] == "Sign in to browse VODs"
    assert "Get info" in tab.sv_empty.texts()[1]  # and says pasting a link still works without signing in


def test_signing_in_hides_the_banner_and_enables_searching(tab, session):
    sign_in(tab, session)
    assert not tab.signin_bar.isVisibleTo(tab)
    assert tab.search_btn.isEnabled()
    assert tab.sv_empty.texts()[0] == "Pick a streamer"


def test_the_banner_text_and_button(tab):
    assert tab.signin_label.text() == "Sign in with Twitch to search streamers and list their VODs."
    buttons = tab.signin_bar.findChildren(QPushButton)
    assert [b.text() for b in buttons] == ["Sign in…"]
    assert buttons[0].property("variant") == "accent"


def test_the_banner_button_asks_for_the_sign_in_dialog(qtbot, tab):
    with qtbot.waitSignal(tab.signin_requested, timeout=1000):
        tab.signin_btn.click()


# ------------------------------------------------------------------ the three lists
def test_the_lists_start_with_a_hint_each(tab):
    assert tab.ch_empty.shown and tab.ch_empty.texts() == ["Search results show up here."]
    assert tab.recent_empty.shown and tab.recent_empty.texts() == ["Streamers you open show up here."]
    assert tab.sv_empty.shown
    assert not tab.clear_recent_btn.isEnabled()  # nothing to clear


def test_a_search_without_results_says_what_was_searched(tab, session):
    sign_in(tab, session)
    tab.on_search_ok("zzzz", [])
    assert tab.ch_empty.shown
    assert tab.ch_empty.texts() == ["No streamers found for «zzzz»", "Check the spelling."]


def test_search_results_replace_the_message_and_a_new_empty_search_brings_it_back(tab, session):
    sign_in(tab, session)
    tab.on_search_ok("stre", RESULTS)
    assert not tab.ch_empty.shown
    assert row_texts(tab.results_view) == ["● Streamer", "Other One"]  # the dot marks who is live
    tab.on_search_ok("nothing", [])
    assert tab.ch_empty.shown and row_texts(tab.results_view) == []


def test_recent_streamers_toggle_their_message_and_the_clear_button(tab):
    tab.add_recent(dict(id="9", login="x", name="Ex"))
    assert not tab.recent_empty.shown
    assert tab.clear_recent_btn.isEnabled()
    assert row_texts(tab.recent_view) == ["Ex"]
    tab.clear_recent()
    assert tab.recent_empty.shown
    assert not tab.clear_recent_btn.isEnabled()


def test_the_streamer_lists_keep_working_as_before(tab):
    # one column of names and no column heading: the card has the title (a QListView has no header at all)
    assert isinstance(tab.results_view, QListView) and isinstance(tab.recent_view, QListView)
    assert tab.results_view.selectionMode() == tab.recent_view.selectionMode() == QListView.SelectionMode.SingleSelection
    assert isinstance(tab.vod_table, QTableView)
    assert [c[1] for c in search_models.VOD_COLUMNS] == ["", "Title", "Date", "Length", "Views"]
    assert tab.results_view.findChild(QLineEdit) is None


def test_the_card_titles_and_hints(tab):
    from qt_ui.widgets import Card
    cards = {c.title_label.text(): c for c in tab.findChildren(Card)}
    assert set(cards) == {"Results", "Recent streamers"}
    assert cards["Results"].subtitle_label.text() == "● = live now"
    assert cards["Recent streamers"].subtitle_label.text() == "The ones you opened lately"


# ------------------------------------------------------------------ the VOD list
def test_vods_hide_the_message_and_the_header_counts_them(tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1), vod(2)])
    assert not tab.sv_empty.shown
    assert tab.title_label.text() == "Streamer  ·  2 VODs"
    assert tab.vod_model.rowCount() == 2


def test_the_header_says_there_is_more_and_uses_the_singular(tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1)], "next-page")
    assert tab.title_label.text() == "Streamer  ·  1 VOD  ·  more available"
    assert tab.more_btn.isEnabled()


def test_a_streamer_without_vods_gets_an_explanation(tab, session):
    sign_in(tab, session)
    load_vods(tab, [])
    assert tab.sv_empty.shown
    assert tab.sv_empty.texts()[0] == "No past broadcasts found"
    assert "Twitch deletes VODs" in tab.sv_empty.texts()[1]
    assert tab.title_label.text() == "Streamer: no past broadcasts found"


def test_the_message_names_the_kind_of_video(tab, session):
    sign_in(tab, session)
    tab.type_combo.setCurrentText("Highlights")
    load_vods(tab, [])
    assert tab.sv_empty.texts()[0] == "No highlights found"
    assert tab.title_label.text() == "Streamer: no highlights found"


def test_loading_is_announced_and_a_failure_ends_it(qtbot, tab, session, monkeypatch, boxes):
    sign_in(tab, session)
    gate = threading.Event()

    def slow_fetch(client, channel_id, kind, after=None):
        gate.wait(5)
        raise RuntimeError("boom")

    monkeypatch.setattr(search_tab, "fetch_videos", slow_fetch)
    tab.load_channel(RESULTS[0])
    assert tab.sv_loading and tab.sv_empty.texts()[0] == "Loading VODs…"
    assert tab.title_label.text() == "Streamer: loading…"
    assert not tab.more_btn.isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: not tab.sv_loading, timeout=5000)
    assert tab.title_label.text() == "Could not load the VODs."
    assert tab.sv_empty.texts()[0].startswith("No ")  # a streamer is picked, so it explains the empty list
    assert boxes.log == [("error", "Search", "boom")]


def test_an_answer_for_an_older_streamer_changes_nothing(tab, session):
    sign_in(tab, session)
    tab.sv_channel, tab.sv_gen = RESULTS[0], 2
    tab.sv_loading = True
    tab.on_videos_ok(1, [vod(1)], None)  # generation 1 is stale
    assert tab.sv_loading and tab.vod_model.rowCount() == 0


def test_an_error_for_an_older_streamer_changes_nothing(tab, session, boxes):
    sign_in(tab, session)
    tab.sv_channel, tab.sv_gen = RESULTS[0], 2
    tab.sv_loading = True
    tab.set_title("Streamer: loading…")
    tab.on_videos_err(1, "late failure")
    assert tab.sv_loading and tab.title_label.text() == "Streamer: loading…" and boxes.log == []


def test_vod_headings_line_up_with_their_columns(tab):
    model = tab.vod_model
    for col in range(model.columnCount()):
        head = model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole)
        cell = model.index(0, col).data(Qt.ItemDataRole.TextAlignmentRole) if model.rowCount() else head
        assert head == cell
    load_vods(tab, [vod(1)])
    for col in range(model.columnCount()):
        assert model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole) == \
            model.index(0, col).data(Qt.ItemDataRole.TextAlignmentRole)


def test_the_cells_show_title_date_length_and_views(tab):
    load_vods(tab, [vod(3)])
    m = tab.vod_model
    assert [m.index(0, c).data() for c in range(5)] == ["", "Stream 3", "2026-10-01", "1:00:03", "30"]


def test_the_use_hint_sits_next_to_the_button_and_the_header_has_no_instruction(tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    assert "double-click" not in tab.title_label.text().lower()  # it used to run into the drop-down
    assert tab.use_hint.text() == "Double-click a VOD to use it"
    assert tab.use_hint.geometry().right() < tab.use_btn.geometry().left()


def test_the_type_list_is_never_squeezed_by_a_long_title(qtbot, tab):
    tab.window().resize(900, 560)
    tab.set_title("A very long streamer name · 123 VODs · more available, long enough to want a whole line")
    qtbot.wait(50)
    assert tab.type_combo.width() >= tab.type_combo.sizeHint().width()  # the drop-down keeps its full width
    assert tab.title_label.wordWrap()  # the title wraps instead
    assert [tab.type_combo.itemText(i) for i in range(tab.type_combo.count())] == list(core_search.VIDEO_KINDS)


def test_keyboard_order_has_nothing_decorative(qtbot, tab, session):
    sign_in(tab, session)
    tab.show()
    stops, w = [tab.search_edit], tab.search_edit.nextInFocusChain()
    while w is not tab.search_edit and len(stops) < 500:
        stops.append(w)
        w = w.nextInFocusChain()
    inside = [x for x in stops if tab.isAncestorOf(x) and x.isVisibleTo(tab) and x.focusPolicy() != Qt.FocusPolicy.NoFocus]
    wanted = [tab.search_edit, tab.search_btn, tab.results_view, tab.recent_view, tab.clear_recent_btn,
              tab.type_combo, tab.vod_table, tab.more_btn, tab.use_btn]
    order = [x for x in inside if x in wanted]
    assert order == wanted
    for x in inside:  # nothing decorative: only fields, buttons, lists and tables take the keyboard
        assert isinstance(x, (QLineEdit, QPushButton, QListView, QTableView, ComboBox)), x


# ------------------------------------------------------------------ searching
def test_a_search_runs_in_a_worker_and_fills_the_results(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    seen = {}

    def fake_search(client, query):
        seen.update(client=client, query=query, thread=threading.current_thread())
        return RESULTS

    monkeypatch.setattr(search_tab, "search_channels", fake_search)
    statuses = []
    tab.status_message.connect(statuses.append)
    tab.search_edit.setText("  stre  ")
    tab.on_search()
    assert statuses == ["Searching for «stre»…"] and not tab.search_btn.isEnabled()
    qtbot.waitUntil(lambda: tab.sv_results == RESULTS, timeout=3000)
    assert seen["query"] == "stre" and seen["client"] is session.client
    assert seen["thread"] is not threading.main_thread()  # the network call is not on the GUI thread
    assert tab.search_btn.isEnabled()
    assert statuses[-1] in ("2 streamers found. Pick one to see their VODs.", "2 streamer(s) found. Pick one to see their VODs.")
    assert not tab.vod_model.rowCount()  # "stre" is not an exact login: nothing opens by itself


def test_enter_in_the_field_searches(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    queries = []
    monkeypatch.setattr(search_tab, "search_channels", lambda client, q: queries.append(q) or [])
    tab.search_edit.setText("abc")
    qtbot.keyClick(tab.search_edit, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: queries == ["abc"], timeout=3000)


def test_an_empty_query_does_nothing(tab, session, monkeypatch):
    sign_in(tab, session)
    monkeypatch.setattr(search_tab, "search_channels", lambda *a: pytest.fail("must not search"))
    tab.search_edit.setText("   ")
    tab.on_search()
    assert tab.search_btn.isEnabled()


def test_searching_without_a_session_asks_to_sign_in(tab, monkeypatch):
    monkeypatch.setattr(search_tab, "search_channels", lambda *a: pytest.fail("must not search"))
    statuses = []
    tab.status_message.connect(statuses.append)
    tab.search_edit.setText("abc")
    tab.on_search()
    assert statuses == ["Sign in with Twitch to search (use the «Sign in…» button)."]


def test_no_streamers_found_says_so_in_the_status_line(tab, session):
    sign_in(tab, session)
    statuses = []
    tab.status_message.connect(statuses.append)
    tab.on_search_ok("zzzz", [])
    assert statuses == ["No streamers found for «zzzz»."]


def test_an_exact_login_match_opens_the_streamer_at_once(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    calls = []
    monkeypatch.setattr(search_tab, "fetch_videos",
                        lambda client, cid, kind, after=None: calls.append((cid, kind, after)) or ([vod(1)], None))
    tab.on_search_ok("@Streamer", RESULTS)
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 1, timeout=3000)
    assert calls == [("1", "archive", None)]
    assert tab.sv_channel == RESULTS[0]
    assert row_texts(tab.recent_view) == ["Streamer"]  # and it is remembered


def test_a_failed_search_shows_the_message_and_re_enables_the_button(qtbot, tab, session, monkeypatch, boxes):
    sign_in(tab, session)

    def broken(client, query):
        raise RuntimeError("no network")

    monkeypatch.setattr(search_tab, "search_channels", broken)
    statuses = []
    tab.status_message.connect(statuses.append)
    tab.search_edit.setText("abc")
    tab.on_search()
    qtbot.waitUntil(lambda: bool(boxes.log), timeout=3000)
    assert boxes.log == [("error", "Search", "no network")]
    assert statuses[-1] == "Search failed." and tab.search_btn.isEnabled()
    assert session.reloads == 0


def test_an_expired_session_makes_the_client_again(tab, session, boxes):
    sign_in(tab, session)
    tab.on_search_err("Not signed in. Please sign in again.")
    assert session.reloads == 1
    assert boxes.log[-1][:2] == ("error", "Search")


# ------------------------------------------------------------------ picking a streamer
def test_picking_a_result_loads_the_vods_and_remembers_the_streamer(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    calls = []
    monkeypatch.setattr(search_tab, "fetch_videos",
                        lambda client, cid, kind, after=None: calls.append(cid) or ([vod(1), vod(2)], "c1"))
    tab.on_search_ok("stre", RESULTS)
    tab.select_channel(tab.results_view, 1)
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 2, timeout=3000)
    assert calls == ["2"] and tab.sv_channel == RESULTS[1]
    assert tab.title_label.text() == "Other One  ·  2 VODs  ·  more available"
    assert tab.recent == [dict(id="2", login="other", name="Other One")]
    assert tab.more_btn.isEnabled()


def test_picking_from_one_list_clears_the_selection_of_the_other(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    monkeypatch.setattr(search_tab, "fetch_videos", lambda *a, **k: ([], None))
    tab.on_search_ok("stre", RESULTS)
    tab.select_channel(tab.results_view, 0)
    qtbot.waitUntil(lambda: not tab.sv_loading, timeout=3000)
    assert tab.results_view.selectionModel().hasSelection()
    tab.select_channel(tab.recent_view, 0)  # picking from the recent list (the one just opened)
    assert not tab.results_view.selectionModel().hasSelection()
    qtbot.waitUntil(lambda: not tab.sv_loading, timeout=3000)
    assert tab.sv_gen == 3  # two real picks and nothing else: clearing the other list loaded nothing


def test_a_new_streamer_replaces_the_list_and_bumps_the_generation(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    monkeypatch.setattr(search_tab, "fetch_videos", lambda *a, **k: ([vod(1)], None))
    tab.load_channel(RESULTS[0])
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 1, timeout=3000)
    gen = tab.sv_gen
    tab.load_channel(RESULTS[1])
    assert tab.sv_gen == gen + 1
    assert tab.vod_model.rowCount() == 0 and tab.sv_cursor is None  # emptied at once, filled when the answer comes
    assert tab.sv_empty.texts()[0] == "Loading VODs…"


def test_a_slow_answer_for_the_first_streamer_is_dropped(qtbot, tab, session, monkeypatch):
    """Pick A (slow), then B (fast): A's list must never show up, whenever it arrives."""
    sign_in(tab, session)
    gate = threading.Event()

    def fetch(client, cid, kind, after=None):
        if cid == "1":
            gate.wait(5)
            return [vod(1), vod(2), vod(3)], None
        return [vod(9)], None

    monkeypatch.setattr(search_tab, "fetch_videos", fetch)
    tab.load_channel(RESULTS[0])
    tab.load_channel(RESULTS[1])
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 1, timeout=3000)
    gate.set()
    qtbot.wait(300)  # the slow answer has arrived by now
    assert tab.vod_model.rowCount() == 1 and tab.sv_videos[0]["title"] == "Stream 9"
    assert tab.title_label.text() == "Other One  ·  1 VOD"


def test_changing_the_kind_reloads_without_touching_the_recent_list(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    kinds = []
    monkeypatch.setattr(search_tab, "fetch_videos",
                        lambda client, cid, kind, after=None: kinds.append(kind) or ([vod(1)], None))
    tab.load_channel(RESULTS[0])
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 1, timeout=3000)
    before = list(tab.recent)
    tab.type_combo.setCurrentText("Uploads")
    tab._on_kind_chosen(tab.type_combo.currentIndex())  # what the user's choice in the list triggers
    qtbot.waitUntil(lambda: kinds == ["archive", "upload"], timeout=3000)
    assert tab.recent == before


def test_choosing_a_kind_in_the_list_reloads(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    kinds = []
    monkeypatch.setattr(search_tab, "fetch_videos",
                        lambda client, cid, kind, after=None: kinds.append(kind) or ([], None))
    tab.sv_channel = RESULTS[0]
    tab.type_combo.setCurrentIndex(1)
    tab.type_combo.activated.emit(1)  # the signal of a choice made by the person (not by code)
    qtbot.waitUntil(lambda: kinds == ["highlight"], timeout=3000)


def test_choosing_a_kind_with_no_streamer_picked_does_nothing(tab, session, monkeypatch):
    sign_in(tab, session)
    monkeypatch.setattr(search_tab, "fetch_videos", lambda *a, **k: pytest.fail("must not load"))
    tab.type_combo.setCurrentIndex(2)
    tab.type_combo.activated.emit(2)
    assert not tab.sv_loading


def test_loading_a_streamer_without_a_session_asks_to_sign_in(tab, monkeypatch):
    monkeypatch.setattr(search_tab, "fetch_videos", lambda *a, **k: pytest.fail("must not load"))
    statuses = []
    tab.status_message.connect(statuses.append)
    tab.load_channel(RESULTS[0])
    assert statuses == ["Sign in with Twitch to list VODs (use the «Sign in…» button)."]
    assert tab.sv_gen == 0 and tab.sv_channel is None


# ------------------------------------------------------------------ paging
def test_load_more_adds_the_next_page_with_the_cursor(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    pages = {None: ([vod(1), vod(2)], "c1"), "c1": ([vod(3)], None)}
    afters = []

    def fetch(client, cid, kind, after=None):
        afters.append(after)
        return pages[after]

    monkeypatch.setattr(search_tab, "fetch_videos", fetch)
    tab.load_channel(RESULTS[0])
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 2 and tab.more_btn.isEnabled(), timeout=3000)
    gen = tab.sv_gen
    tab.more_btn.click()
    assert not tab.more_btn.isEnabled() and tab.title_label.text() == "Streamer: loading…"
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 3, timeout=3000)
    assert afters == [None, "c1"] and tab.sv_gen == gen  # the same list: the generation does not change
    assert [v["title"] for v in tab.sv_videos] == ["Stream 1", "Stream 2", "Stream 3"]
    assert tab.title_label.text() == "Streamer  ·  3 VODs" and not tab.more_btn.isEnabled()
    assert row_texts_of_recent(tab) == ["Streamer"]  # paging does not add to the recent list again


def row_texts_of_recent(tab):
    return row_texts(tab.recent_view)


def test_load_more_without_a_cursor_does_nothing(tab, session, monkeypatch):
    sign_in(tab, session)
    monkeypatch.setattr(search_tab, "fetch_videos", lambda *a, **k: pytest.fail("must not load"))
    tab.load_more()
    tab.sv_channel = RESULTS[0]
    tab.load_more()
    assert not tab.sv_loading


def test_a_new_page_keeps_the_selection(qtbot, tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1), vod(2)], "c1")
    tab.select_vod(1)
    tab.on_videos_ok(1, [vod(3)], None)
    assert tab.selected_video()["title"] == "Stream 2"


# ------------------------------------------------------------------ recent streamers
def test_the_recent_list_is_newest_first_without_duplicates_and_capped(tab):
    for i in range(15):
        tab.add_recent(dict(id=str(i), login=f"l{i}", name=f"N{i}"))
    assert len(tab.recent) == paths.MAX_RECENT == 12
    assert tab.recent[0]["id"] == "14"
    tab.add_recent(dict(id="10", login="l10", name="N10"))  # opening one again moves it to the top
    assert [c["id"] for c in tab.recent][:3] == ["10", "14", "13"] and len(tab.recent) == 12
    assert row_texts(tab.recent_view)[:2] == ["N10", "N14"]


def test_the_recent_list_is_saved_and_loaded(qtbot, themed, boxes, tab):
    tab.add_recent(dict(id="7", login="seven", name="Seven"))
    saved = json.loads(paths.RECENT_PATH.read_text(encoding="utf-8"))
    assert saved == [dict(id="7", login="seven", name="Seven")]
    again = SearchTab()
    qtbot.addWidget(again)
    assert again.recent == saved and row_texts(again.recent_view) == ["Seven"]
    again.shutdown()
    tab.clear_recent()
    assert json.loads(paths.RECENT_PATH.read_text(encoding="utf-8")) == []


def test_a_name_missing_from_a_streamer_falls_back_to_the_login(tab):
    tab.add_recent(dict(id="5", login="fivelogin"))
    assert tab.recent == [dict(id="5", login="fivelogin", name="fivelogin")]


# ------------------------------------------------------------------ using a VOD
def test_use_this_vod_sends_the_link(qtbot, tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1), vod(2)])
    tab.select_vod(1)
    with qtbot.waitSignal(tab.vod_chosen, timeout=1000) as sig:
        tab.use_btn.click()
    assert sig.args == ["https://www.twitch.tv/videos/2"]


def test_double_click_and_enter_use_the_vod(qtbot, tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1), vod(2)])
    tab.select_vod(0)
    index = tab.vod_model.index(0, 1)
    pos = tab.vod_table.visualRect(index).center()
    qtbot.mouseClick(tab.vod_table.viewport(), Qt.MouseButton.LeftButton, pos=pos)  # the first click of a double-click
    with qtbot.waitSignal(tab.vod_chosen, timeout=1000):
        qtbot.mouseDClick(tab.vod_table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    tab.vod_table.setFocus()
    with qtbot.waitSignal(tab.vod_chosen, timeout=1000):
        qtbot.keyClick(tab.vod_table, Qt.Key.Key_Return)
    with qtbot.waitSignal(tab.vod_chosen, timeout=1000):
        qtbot.keyClick(tab.vod_table, Qt.Key.Key_Enter)


def test_double_click_on_empty_space_uses_nothing(qtbot, tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    seen = []
    tab.vod_chosen.connect(seen.append)
    qtbot.mouseDClick(tab.vod_table.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(50, tab.vod_table.viewport().height() - 5))
    assert seen == []


def test_using_a_vod_with_nothing_selected_explains(tab, session, boxes):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    seen = []
    tab.vod_chosen.connect(seen.append)
    tab.use_btn.click()
    assert boxes.log == [("info", "Select a VOD", "Select a VOD in the list first.")] and seen == []


def test_the_window_puts_the_link_in_the_entry_and_runs_get_info(win, monkeypatch):
    calls = []
    monkeypatch.setattr(mw.MainWindow, "on_get_info", lambda self: calls.append(self.vod_entry.text()))
    win.tabs.setCurrentWidget(win.tab_search)
    load_vods(win.tab_search, [vod(4)])
    win.tab_search.select_vod(0)
    win.tab_search.use_btn.click()
    assert win.vod_entry.text() == "https://www.twitch.tv/videos/4"
    assert win.tabs.currentWidget() is win.tab_plan
    assert calls == ["https://www.twitch.tv/videos/4"]


# ------------------------------------------------------------------ thumbnails
@pytest.fixture()
def fake_fetch(monkeypatch, tmp_path):
    """``fetch_thumbnail`` that writes a picture per URL and records which thread asked."""
    log = types.SimpleNamespace(urls=[], threads=set(), colours={}, fail=set(), delay=None)

    def fetch(url):
        log.urls.append(url)
        log.threads.add(threading.current_thread())
        if log.delay:
            log.delay.wait(5)
        if url in log.fail:
            return None
        return __import__("pathlib").Path(png(tmp_path / f"{abs(hash(url))}.png", log.colours.get(url, "#3366cc")))

    monkeypatch.setattr(thumbs, "fetch_thumbnail", fetch)
    return log


def with_thumbs(n, **kw):
    return [dict(vod(i), thumb=f"https://img/{i}.jpg", **kw) for i in range(1, n + 1)]


def test_thumbnails_are_fetched_by_workers_and_built_on_the_gui_thread(qtbot, tab, session, fake_fetch, monkeypatch):
    sign_in(tab, session)
    gui = QThread.currentThread()
    where = []
    real = VodModel.set_thumb

    def spy(self, iid, path):
        where.append(QThread.currentThread())
        return real(self, iid, path)

    monkeypatch.setattr(VodModel, "set_thumb", spy)
    fake_fetch.colours["https://img/1.jpg"] = "#ff0000"
    load_vods(tab, with_thumbs(3))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 3, timeout=5000)
    assert all(t is not threading.main_thread() for t in fake_fetch.threads)  # fetched off the GUI thread
    assert where and all(t is gui for t in where)  # ... the pixmaps are made on it
    pix = tab.vod_model.index(0, 0).data(search_models.THUMB_ROLE)
    assert (pix.width(), pix.height()) == core_search.THUMB_SIZE
    assert pix.toImage().pixelColor(10, 10) == QColor("#ff0000")


def test_the_delegate_paints_the_picture_inside_the_row(qtbot, tab, session, fake_fetch):
    sign_in(tab, session)
    fake_fetch.colours["https://img/1.jpg"] = "#00ff00"
    load_vods(tab, with_thumbs(2))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 2, timeout=5000)
    tab.vod_table.viewport().repaint()
    img = tab.vod_table.viewport().grab().toImage()
    rect = tab.vod_table.visualRect(tab.vod_model.index(0, 0))
    centre = img.pixelColor(rect.left() + THUMB_MARGIN + core_search.THUMB_SIZE[0] // 2, rect.center().y())
    assert centre == QColor("#00ff00")
    gap = img.pixelColor(rect.left() + THUMB_MARGIN + core_search.THUMB_SIZE[0] + 6, rect.center().y())
    assert gap != QColor("#00ff00")  # the gap between the picture and the title stays empty


def test_a_row_without_a_thumbnail_paints_none(tab, session):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    assert tab.vod_model.index(0, 0).data(search_models.THUMB_ROLE) is None


def test_workers_start_with_the_first_thumbnail_and_there_are_four(qtbot, tab, session, fake_fetch):
    sign_in(tab, session)
    assert tab.thumbs.threads == []  # nothing runs for a tab that has no thumbnails yet
    load_vods(tab, with_thumbs(1))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 1, timeout=5000)
    assert len(tab.thumbs.threads) == thumbs.WORKERS == 4
    assert all(t.daemon for t in tab.thumbs.threads)


def test_a_vod_without_a_thumbnail_url_is_not_queued(tab, session, fake_fetch):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])  # thumb is ""
    assert tab.thumbs.threads == [] and fake_fetch.urls == []


def test_a_stale_thumbnail_job_is_skipped_without_fetching(qtbot, tab, session, fake_fetch):
    sign_in(tab, session)
    tab.sv_gen = 5
    tab.thumbs.submit(4, "0", "https://img/old.jpg")  # a job of an older list
    tab.thumbs.submit(5, "0", "https://img/new.jpg")
    qtbot.waitUntil(lambda: "https://img/new.jpg" in fake_fetch.urls, timeout=3000)
    qtbot.wait(100)
    assert fake_fetch.urls == ["https://img/new.jpg"]


def test_a_thumbnail_arriving_after_the_list_was_replaced_is_dropped(qtbot, tab, session, fake_fetch, tmp_path):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    path = png(tmp_path / "late.png")
    tab.sv_gen = 2  # another streamer was picked meanwhile
    tab.on_thumb(1, "0", path)
    assert len(tab.vod_model.cache) == 0 and tab.vod_model.paths == {}


def test_a_thumbnail_for_a_row_that_is_gone_is_dropped(tab, session, tmp_path):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    tab.on_thumb(1, "7", png(tmp_path / "x.png"))
    tab.on_thumb(1, "zero", png(tmp_path / "y.png"))
    assert len(tab.vod_model.cache) == 0


def test_an_unreadable_picture_leaves_the_row_without_one(tab, session, tmp_path):
    sign_in(tab, session)
    load_vods(tab, [vod(1)])
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"this is not an image")
    tab.on_thumb(1, "0", str(bad))
    assert tab.vod_model.index(0, 0).data(search_models.THUMB_ROLE) is None
    tab.on_thumb(1, "0", str(tmp_path / "missing.jpg"))
    assert len(tab.vod_model.cache) == 0


def test_a_failed_download_leaves_the_row_without_one(qtbot, tab, session, fake_fetch):
    sign_in(tab, session)
    fake_fetch.fail.add("https://img/1.jpg")
    load_vods(tab, with_thumbs(2))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 1, timeout=5000)
    qtbot.wait(100)
    assert tab.vod_model.index(0, 0).data(search_models.THUMB_ROLE) is None
    assert tab.vod_model.index(1, 0).data(search_models.THUMB_ROLE) is not None


def test_a_new_streamer_clears_the_pictures(qtbot, tab, session, fake_fetch, monkeypatch):
    sign_in(tab, session)
    load_vods(tab, with_thumbs(2))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 2, timeout=5000)
    monkeypatch.setattr(search_tab, "fetch_videos", lambda *a, **k: ([], None))
    tab.load_channel(RESULTS[1])
    assert len(tab.vod_model.cache) == 0 and tab.vod_model.paths == {}


def test_the_cache_is_capped_and_a_dropped_picture_comes_back_from_its_file(tmp_path):
    cache = ThumbCache(limit=2)
    model = VodModel(cache)
    model.append([vod(1), vod(2), vod(3)])
    for i in range(3):
        assert model.set_thumb(str(i), png(tmp_path / f"{i}.png", ["#ff0000", "#00ff00", "#0000ff"][i]))
    assert len(cache) == 2 and "0" not in cache  # the least recently used went first
    pix = model.index(0, 0).data(search_models.THUMB_ROLE)  # row 0 is made again from its file
    assert pix is not None and pix.toImage().pixelColor(5, 5) == QColor("#ff0000")
    assert len(cache) == 2 and "0" in cache


def test_stopping_the_tab_ends_the_workers(qtbot, tab, session, fake_fetch):
    sign_in(tab, session)
    load_vods(tab, with_thumbs(1))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 1, timeout=5000)
    threads = list(tab.thumbs.threads)
    tab.shutdown()
    qtbot.waitUntil(lambda: not any(t.is_alive() for t in threads), timeout=3000)
    tab.thumbs.submit(1, "0", "https://img/late.jpg")  # after stopping nothing starts again
    assert tab.thumbs.threads == threads


# ------------------------------------------------------------------ the models and the threads
def test_the_models_are_updated_on_the_gui_thread(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    gui = QThread.currentThread()
    where = []
    real = VodModel.append

    def spy(self, videos):
        where.append(QThread.currentThread())
        return real(self, videos)

    monkeypatch.setattr(VodModel, "append", spy)
    fetched = []
    monkeypatch.setattr(search_tab, "fetch_videos",
                        lambda *a, **k: fetched.append(threading.current_thread()) or ([vod(1)], None))
    tab.load_channel(RESULTS[0])
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 1, timeout=3000)
    assert where == [gui] and fetched[0] is not threading.main_thread()


def test_the_channel_model_marks_live_streamers_only_in_the_results(tab):
    tab.results_model.set_channels(RESULTS)
    tab.recent_model.set_channels(RESULTS)
    assert row_texts(tab.results_view) == ["● Streamer", "Other One"]
    assert row_texts(tab.recent_view) == ["Streamer", "Other One"]
    assert tab.results_model.index(0, 0).data(search_models.CHANNEL_ROLE) == RESULTS[0]


def test_the_constants_are_the_ones_of_the_tkinter_app():
    assert core_search.THUMB_SIZE == (128, 72) and core_search.THUMB_GAP == 14
    assert core_search.VIDEO_KINDS == {"Past broadcasts": "archive", "Highlights": "highlight", "Uploads": "upload"}
    assert paths.MAX_RECENT == 12


# ------------------------------------------------------------------ the combo box
def test_the_combo_box_is_read_only_and_draws_its_arrow(qtbot, tab):
    combo = tab.type_combo
    assert isinstance(combo, ComboBox) and not combo.isEditable()
    assert combo.currentText() == "Past broadcasts"
    img = combo.grab().toImage()
    x, y = combo.width() - 12, combo.height() // 2
    inner = {img.pixelColor(x + dx, y + dy).name() for dx in range(-3, 4) for dy in range(-2, 3)}
    assert len(inner) > 1  # the arrow is not the same colour as the field around it


# ------------------------------------------------------------------ in the main window
def test_the_window_gives_the_tab_its_client(win):
    tab = win.tab_search
    assert tab.client is win.client and not tab.signin_bar.isVisibleTo(tab)
    win.client = None  # signing out
    assert tab.signin_bar.isVisibleTo(tab) and not tab.search_btn.isEnabled()
    win.client = object()
    assert not tab.signin_bar.isVisibleTo(tab) and tab.search_btn.isEnabled()


def test_a_window_without_a_session_starts_on_the_plan_tab_with_the_banner(qtbot, themed):
    w = mw.MainWindow(settings=dict(DEFAULTS))
    qtbot.addWidget(w)
    w.show()
    assert w.tabs.currentWidget() is w.tab_plan
    assert w.tab_search.signin_bar.isVisibleTo(w.tab_search) and not w.tab_search.search_btn.isEnabled()
    w.tab_search.shutdown()


def test_the_tab_reaches_the_status_line_and_the_dialog_through_the_window(qtbot, win, monkeypatch):
    opened = []
    monkeypatch.setattr(mw.MainWindow, "ask_credentials", lambda self: opened.append(1))
    win.client = None
    win.tab_search.signin_requested.emit()
    assert opened == [1]
    win.tab_search.status_message.emit("hello from the search tab")
    assert win.status_label.text() == "hello from the search tab"


def test_closing_the_window_stops_the_thumbnail_workers(qtbot, win, fake_fetch):
    tab = win.tab_search
    tab.sv_channel, tab.sv_gen = RESULTS[0], 1
    tab.on_videos_ok(1, with_thumbs(1), None)
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 1, timeout=5000)
    threads = list(tab.thumbs.threads)
    win.close()
    qtbot.waitUntil(lambda: not any(t.is_alive() for t in threads), timeout=3000)



# ------------------------------------------------------------------ Phase 9g: ChannelDelegate, Grid/List mode, filter, infinite scroll
def test_channel_delegate_renders_avatar_initials_and_live_badge(qtbot, tab, session):
    sign_in(tab, session)
    tab.on_search_ok("stre", RESULTS)
    assert search_models.channel_avatar_colour("Streamer") == search_models.channel_avatar_colour("  streamer ")
    tab.results_view.viewport().repaint()
    img = tab.results_view.viewport().grab().toImage()
    rect = tab.results_view.visualRect(tab.results_model.index(0, 0))
    # Red LIVE badge (#eb0400) painted near the right end of row 0
    badge_colors = {img.pixelColor(x, int(rect.center().y())).name() for x in range(int(rect.right() - 40), int(rect.right() - 8))}
    assert "#eb0400" in badge_colors


def test_list_and_grid_view_switcher_shares_selection_and_paints_cards(qtbot, tab, session, fake_fetch):
    sign_in(tab, session)
    fake_fetch.colours["https://img/1.jpg"] = "#00cc66"
    load_vods(tab, with_thumbs(2))
    qtbot.waitUntil(lambda: len(tab.vod_model.cache) == 2, timeout=5000)

    assert tab.view_mode == "list"
    assert tab.vod_stack.currentWidget() is tab.vod_table
    tab.select_vod(1)
    assert tab.selected_video()["title"] == "Stream 2"

    # Switch to grid view
    tab.grid_mode_btn.click()
    assert tab.view_mode == "grid"
    assert tab.vod_stack.currentWidget() is tab.vod_grid
    assert tab.selected_video()["title"] == "Stream 2"

    # Paint grid cards and double-click card 0
    tab.vod_grid.viewport().repaint()
    img = tab.vod_grid.viewport().grab().toImage()
    assert not img.isNull()
    idx0 = tab.vod_model.index(0, 0)
    pos = tab.vod_grid.visualRect(idx0).center()
    qtbot.mouseClick(tab.vod_grid.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    with qtbot.waitSignal(tab.vod_chosen, timeout=1000) as sig:
        qtbot.mouseDClick(tab.vod_grid.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert sig.args == ["https://www.twitch.tv/videos/1"]

    # Switch back to list view
    tab.list_mode_btn.click()
    assert tab.view_mode == "list"
    assert tab.vod_stack.currentWidget() is tab.vod_table


def test_vod_filter_bar_hides_non_matching_rows_in_table_and_grid(tab, session):
    sign_in(tab, session)
    load_vods(tab, [
        {**vod(1), "title": "Elden Ring Boss Rush", "date": "2026-10-01"},
        {**vod(2), "title": "Just Chatting Chill", "date": "2026-10-02"},
        {**vod(3), "title": "Elden Ring Finale", "date": "2026-10-03"},
    ])
    assert tab.visible_vod_rows() == [0, 1, 2]
    tab.vod_filter_edit.setText("elden")
    assert tab.visible_vod_rows() == [0, 2]
    assert tab.vod_table.isRowHidden(1) and tab.vod_grid.isRowHidden(1)
    tab.vod_filter_edit.clear()
    assert tab.visible_vod_rows() == [0, 1, 2]


def test_infinite_scroll_loads_next_page_at_bottom(qtbot, tab, session, monkeypatch):
    sign_in(tab, session)
    pages = {None: ([vod(i) for i in range(1, 15)], "cur2"), "cur2": ([vod(15)], None)}
    monkeypatch.setattr(search_tab, "fetch_videos", lambda client, cid, kind, after=None: pages[after])
    tab.load_channel(RESULTS[0])
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 14 and tab.sv_cursor == "cur2", timeout=3000)
    bar = tab.vod_table.verticalScrollBar()
    if bar.maximum() > 0:
        bar.setValue(bar.maximum())
    else:
        tab._on_vod_scroll(bar.maximum())
    qtbot.waitUntil(lambda: tab.vod_model.rowCount() == 15, timeout=3000)



def test_channel_model_renders_real_avatar_pixmap_when_set(qtbot, tab, tmp_path):
    tab.results_model.set_channels([dict(id="123", login="vexoria", name="Vexoria")])
    avatar_file = png(tmp_path / "vex.png", colour="#9933cc", size=(64, 64))
    pix = search_models.load_thumb(avatar_file)
    assert pix is not None
    tab.results_model.set_avatar("123", pix)
    assert not tab.results_model.index(0, 0).data(search_models.AVATAR_ROLE).isNull()
    tab.results_view.viewport().repaint()
    img = tab.results_view.viewport().grab().toImage()
    rect = tab.results_view.visualRect(tab.results_model.index(0, 0))
    # Probe inside circular avatar area
    assert img.pixelColor(rect.left() + 20, rect.center().y()) == QColor("#9933cc")

def test_spawn_avatar_fetch_downloads_profile_pictures_for_all_channels(qtbot, tab, session, tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.calls = []
        def get(self, endpoint, params):
            self.calls.append((endpoint, params))
            if endpoint == "users":
                return {
                    "data": [
                        {"id": "10", "profile_image_url": "https://img.test/10.png"},
                        {"id": "20", "profile_image_url": "https://img.test/20.png"},
                    ]
                }
            return {}

    client = FakeClient()
    session.client = client
    tab.update_search_state()

    p10 = png(tmp_path / "10.png", colour="#ff0000", size=(48, 48))
    p20 = png(tmp_path / "20.png", colour="#00ff00", size=(48, 48))
    thumbs_map = {"https://img.test/10.png": p10, "https://img.test/20.png": p20}
    monkeypatch.setattr(search_tab, "fetch_thumbnail", lambda url: thumbs_map.get(url))

    tab.results_model.set_channels([
        dict(id="10", login="ch10", name="Channel 10"),
        dict(id="20", login="ch20", name="Channel 20"),
    ])

    tab._spawn_avatar_fetch(tab.results_model.channels, for_results=True)

    # Even if sv_gen changes (e.g. user selected a channel), avatars should still populate
    tab.sv_gen += 1

    qtbot.waitUntil(lambda: tab.results_model.has_avatar("10") and tab.results_model.has_avatar("20"), timeout=3000)
    assert not tab.results_model.index(0, 0).data(search_models.AVATAR_ROLE).isNull()
    assert not tab.results_model.index(1, 0).data(search_models.AVATAR_ROLE).isNull()
    assert ("users", {"id": ["10", "20"]}) in client.calls



# ------------------------------------------------------------------ Phase 7: Browse Tab & Provider Selector
def test_provider_selector_lists_only_browsable_providers(tab):
    assert tab.provider_combo.isVisible()
    items = [tab.provider_combo.itemData(i) for i in range(tab.provider_combo.count())]
    assert "twitch" in items
    assert "youtube" in items
    assert "generic" not in items
    assert tab.provider_combo.currentData() == "twitch"


def test_provider_selector_hidden_when_only_one_provider_can_browse(monkeypatch):
    from core import providers
    from core.providers.twitch import TwitchProvider
    monkeypatch.setattr(providers, "ALL_PROVIDERS", [TwitchProvider()])
    single_tab = SearchTab()
    try:
        assert not single_tab.provider_combo.isVisible()
        assert not single_tab.provider_label.isVisible()
    finally:
        single_tab.shutdown()


def test_switching_to_youtube_provider_adapts_ui(tab):
    tab.set_provider("youtube")
    assert tab.current_provider_name() == "youtube"
    assert tab.streamer_label.text() == "Search:"
    assert "Search videos" in tab.search_edit.placeholderText()
    assert not tab.type_combo.isVisible()
    assert not tab.results_card.isVisible()
    assert not tab.signin_bar.isVisible()
    assert tab.search_btn.isEnabled()
    assert tab.use_btn.text() == "Use this video"
    assert tab.recent_card.title_label.text() == "Recent searches"


def test_youtube_search_flow_and_use_video(qtbot, tab, monkeypatch):
    from core.providers import YOUTUBE_PROVIDER
    fake_results = [
        {
            "id": "yt1",
            "title": "Python Tutorial 101",
            "date": "2026-05-01",
            "duration": 600.0,
            "views": 50000,
            "thumb": "",
            "url": "https://www.youtube.com/watch?v=yt1",
            "uploader": "LuckyDev",
        }
    ]
    monkeypatch.setattr(YOUTUBE_PROVIDER, "search_videos", lambda query, limit=20: fake_results)
    tab.set_provider("youtube")
    tab.search_edit.setText("python tutorial")
    tab.on_search()

    qtbot.waitUntil(lambda: len(tab.sv_videos) == 1, timeout=3000)
    assert tab.sv_videos[0]["title"] == "Python Tutorial 101"
    assert "Python Tutorial 101" in tab.vod_model.index(0, 1).data()

    # Selecting and using video emits vod_chosen
    tab.select_vod(0)
    with qtbot.waitSignal(tab.vod_chosen, timeout=1000) as sig:
        tab.use_btn.click()
    assert sig.args == ["https://www.youtube.com/watch?v=yt1"]


def test_youtube_recent_searches_and_clear(qtbot, tab, monkeypatch, tmp_path):
    from core.providers import YOUTUBE_PROVIDER
    from core import paths
    monkeypatch.setattr(paths, "RECENT_SEARCHES_PATH", tmp_path / "recent_searches.json")
    monkeypatch.setattr(YOUTUBE_PROVIDER, "search_videos", lambda query, limit=20: [])

    tab.set_provider("youtube")
    tab.search_edit.setText("astronomy")
    tab.on_search()
    qtbot.waitUntil(lambda: not tab.sv_loading, timeout=3000)

    assert any(c["name"] == "astronomy" for c in tab.recent_yt)
    assert tab.recent_model.rowCount() >= 1

    tab.clear_recent()
    assert tab.recent_yt == []
    assert tab.recent_model.rowCount() == 0


def test_switching_back_to_twitch_restores_state(tab):
    tab.set_provider("youtube")
    assert not tab.type_combo.isVisible()

    tab.set_provider("twitch")
    assert tab.current_provider_name() == "twitch"
    assert tab.streamer_label.text() == "Streamer:"
    assert tab.type_combo.isVisible()
    assert tab.results_card.isVisible()
    assert tab.use_btn.text() == "Use this VOD"
