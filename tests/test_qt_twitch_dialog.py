"""The Qt «Twitch API» dialog (Phase 4): device-code sign-in in a thread, sign out, an own Twitch app, closing.

Port of ``App.ask_credentials``. No network and no browser: ``device_login_start`` / ``device_login_poll`` (or
``requests.post`` under the real ones), ``webbrowser.open`` and ``TwitchClient`` are replaced by fakes, and message
boxes too. The config file is a temporary one (``tests/conftest.py`` points ``core.paths`` at a temp folder).
"""

import json
import threading
import time
import types

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import requests  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton  # noqa: E402

import luckytwitch_engine as engine  # noqa: E402
from core import config, paths  # noqa: E402
from core.settings import DEFAULTS  # noqa: E402
from luckytwitch_engine import Cancelled, EngineError, TwitchClient  # noqa: E402
from qt_ui import dialogs, theme  # noqa: E402
from qt_ui import main_window as mw  # noqa: E402
from qt_ui import twitch_dialog as td  # noqa: E402
from qt_ui.twitch_dialog import TwitchDialog  # noqa: E402

START = {"device_code": "dev123", "user_code": "ABCD-EFGH", "verification_uri": "https://www.twitch.tv/activate",
         "expires_in": 600, "interval": 1, "scopes": ""}


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
    calls = types.SimpleNamespace(log=[])
    for name in ("info", "warning", "error"):
        monkeypatch.setattr(dialogs, name, lambda parent, title, text, _n=name: calls.log.append((_n, title, text)))
    return calls


@pytest.fixture()
def browser(monkeypatch):
    opened = []
    monkeypatch.setattr(td.webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    return opened


class Host:
    """What the main window offers the dialog: the client, the status line and the Search tab's refresh."""

    def __init__(self):
        self.client = None
        self.statuses = []
        self.refreshes = 0

    def set_status(self, text):
        self.statuses.append(text)

    def update_search_state(self):
        self.refreshes += 1


@pytest.fixture()
def host():
    return Host()


@pytest.fixture()
def dlg(qtbot, themed, boxes, browser, host):
    d = TwitchDialog(host)
    qtbot.addWidget(d)
    d.open()
    qtbot.waitExposed(d)
    yield d
    d.close()


def config_file() -> dict:
    return json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8")) if paths.CONFIG_PATH.exists() else {}


def fake_api(monkeypatch, start=None, tokens=("ACCESS", "REFRESH"), gate=None):
    """A device-code API that gives ``start``, then (after ``gate`` is set, if there is one) the tokens."""
    log = types.SimpleNamespace(starts=0, polls=[], cancel=None)

    def fake_start(*a, **k):
        log.starts += 1
        return dict(start or START)

    def fake_poll(s, client_id=None, cancel=None):
        log.polls.append(s)
        log.cancel = cancel
        while gate is not None and not gate.is_set():
            if cancel is not None and cancel.is_set():
                raise Cancelled("Sign-in cancelled.")
            time.sleep(0.01)
        return tokens

    monkeypatch.setattr(td, "device_login_start", fake_start)
    monkeypatch.setattr(td, "device_login_poll", fake_poll)
    return log


def signed_in_file(refresh="R", access="A"):
    config.save_login_tokens(access, refresh)


def labels(d):
    return [lbl.text() for lbl in d.findChildren(QLabel)]


# ------------------------------------------------------------------ what it shows
def test_title_texts_and_buttons(dlg):
    assert dlg.windowTitle() == "Twitch API"
    texts = labels(dlg)
    assert ("Optional: only needed to fetch clips (clips → chapters).\n"
            "Sign in with your Twitch account: no developer app needed.") in texts
    assert "Client ID:" in texts and "Client Secret:" in texts
    assert f"Saved in: {paths.CONFIG_PATH}" in texts
    assert [b.text() for b in dlg.findChildren(QPushButton)] == [
        "Sign in with Twitch", "Open page again", "Sign out", "Save own app", "Close"]
    assert dlg.findChildren(type(dlg.findChild(td.QGroupBox)))[0].title() == "Advanced: use your own Twitch app instead"


def test_the_secret_is_masked_and_the_code_is_big_mono_bold_accent(dlg):
    assert dlg.sec_edit.echoMode() == QLineEdit.EchoMode.Password
    assert dlg.id_edit.echoMode() == QLineEdit.EchoMode.Normal
    font = dlg.code_label.font()
    assert font.pointSize() == 18 and font.bold()
    assert dlg.code_label.objectName() == "loginCode" and dlg.code_label.text() == ""
    assert dlg.code_label.height() > 0  # the line is kept while empty, so nothing jumps when the code appears


def test_it_is_modal_and_has_a_fixed_size(dlg):
    assert dlg.isModal()
    assert dlg.minimumSize() == dlg.maximumSize()  # tkinter: not resizable
    assert dlg.width() >= 470  # the status line is 470 wide


def test_status_when_nobody_is_signed_in(dlg):
    assert dlg.status_label.text() == "Not signed in."
    assert dlg.login_btn.text() == "Sign in with Twitch"
    assert not dlg.logout_btn.isEnabled()


def test_status_when_signed_in_with_a_twitch_account(qtbot, themed, boxes, browser, host):
    signed_in_file()
    d = TwitchDialog(host)
    qtbot.addWidget(d)
    assert d.status_label.text() == "✔ Signed in with Twitch. Clips are available."
    assert d.login_btn.text() == "Sign in again" and d.logout_btn.isEnabled()


def test_status_when_using_an_own_app_and_its_fields_are_filled(qtbot, themed, boxes, browser, host):
    config.save_credentials("my-id", "my-secret")
    d = TwitchDialog(host)
    qtbot.addWidget(d)
    assert d.status_label.text() == "Using your own Twitch app (Client ID / Secret below)."
    assert (d.id_edit.text(), d.sec_edit.text()) == ("my-id", "my-secret")
    assert d.login_btn.text() == "Sign in with Twitch" and d.logout_btn.isEnabled()


def test_opening_refreshes_the_search_tab(dlg, host):
    assert host.refreshes >= 1


def test_enter_in_a_field_presses_no_button(qtbot, dlg, monkeypatch):
    fake = fake_api(monkeypatch)
    dlg.id_edit.setFocus()
    qtbot.keyClick(dlg.id_edit, Qt.Key.Key_Return)
    qtbot.keyClick(dlg.sec_edit, Qt.Key.Key_Enter)
    qtbot.wait(100)
    assert fake.starts == 0 and not dlg.state["busy"] and dlg.isVisible()
    assert all(not b.autoDefault() for b in dlg.findChildren(QPushButton))


def test_keyboard_order_follows_the_layout(dlg):
    order = [dlg.login_btn, dlg.page_btn, dlg.logout_btn, dlg.id_edit, dlg.sec_edit, dlg.save_btn, dlg.close_btn]
    stops, w = [], dlg.login_btn
    for _ in range(60):
        stops.append(w)
        w = w.nextInFocusChain()
        if w is dlg.login_btn:
            break
    assert [x for x in stops if x in order] == order


# ------------------------------------------------------------------ signing in
def test_the_sign_in_shows_the_code_opens_the_page_and_saves_the_tokens(qtbot, dlg, host, browser, monkeypatch):
    gate = threading.Event()
    fake = fake_api(monkeypatch, gate=gate)
    config.save_credentials("old-id", "old-secret")  # an own app set up before: the account replaces it
    dlg.refresh_status()
    dlg.login_btn.click()
    assert dlg.status_label.text() in ("Contacting Twitch…", td.WAITING_TEXT)
    assert not dlg.login_btn.isEnabled() and dlg.state["busy"]
    qtbot.waitUntil(lambda: dlg.code_label.text() == "ABCD-EFGH", timeout=3000)
    assert dlg.status_label.text() == ("A browser tab opened. Enter this code on twitch.tv/activate\n"
                                       "and press Authorize. Waiting for you…")
    assert browser == ["https://www.twitch.tv/activate"] and dlg.state["url"] == browser[0]
    assert config_file().get("refresh_token") is None  # nothing is saved until the person approves
    gate.set()
    qtbot.waitUntil(lambda: dlg.login_btn.isEnabled(), timeout=3000)
    assert fake.starts == 1 and fake.polls[0]["device_code"] == "dev123"
    saved = config_file()
    assert (saved["access_token"], saved["refresh_token"]) == ("ACCESS", "REFRESH")
    assert "client_id" not in saved and "client_secret" not in saved  # the own app was replaced
    assert isinstance(host.client, TwitchClient) and host.client.user_refresh == "REFRESH"
    assert dlg.code_label.text() == "" and not dlg.state["busy"]
    assert dlg.status_label.text() == "✔ Signed in with Twitch. Clips are available."
    assert dlg.login_btn.text() == "Sign in again" and dlg.logout_btn.isEnabled()
    assert host.statuses[-1] == "Signed in with Twitch." and host.refreshes >= 2


def test_the_login_runs_off_the_gui_thread_and_the_slots_on_it(qtbot, dlg, monkeypatch):
    threads = {}

    def start(*a, **k):
        threads["start"] = threading.current_thread()
        return dict(START)

    def poll(s, client_id=None, cancel=None):
        threads["poll"] = threading.current_thread()
        return "A", "R"

    monkeypatch.setattr(td, "device_login_start", start)
    monkeypatch.setattr(td, "device_login_poll", poll)
    where = []
    real = TwitchDialog.finish_login
    monkeypatch.setattr(TwitchDialog, "finish_login",
                        lambda self, a, r: where.append(threading.current_thread()) or real(self, a, r))
    dlg2 = TwitchDialog(dlg.host)  # made after the patch, so its signal reaches the spy
    qtbot.addWidget(dlg2)
    dlg2.login_btn.click()
    qtbot.waitUntil(lambda: bool(where), timeout=3000)
    assert threads["start"] is not threading.main_thread() and threads["poll"] is not threading.main_thread()
    assert where == [threading.main_thread()]
    dlg2.close()


def test_pressing_sign_in_twice_starts_one_login(qtbot, dlg, monkeypatch):
    gate = threading.Event()
    fake = fake_api(monkeypatch, gate=gate)
    dlg.start_login()
    dlg.start_login()
    qtbot.waitUntil(lambda: dlg.code_label.text() != "", timeout=3000)
    assert fake.starts == 1
    gate.set()
    qtbot.waitUntil(lambda: dlg.login_btn.isEnabled(), timeout=3000)


def test_open_page_again_needs_a_code_first(qtbot, dlg, browser, monkeypatch):
    dlg.page_btn.click()
    assert browser == []  # nothing to open before the code exists
    gate = threading.Event()
    fake_api(monkeypatch, gate=gate)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: dlg.state["url"] != "", timeout=3000)
    dlg.page_btn.click()
    assert browser == ["https://www.twitch.tv/activate"] * 2  # once by the login, once by the button
    gate.set()
    qtbot.waitUntil(lambda: dlg.login_btn.isEnabled(), timeout=3000)


def test_a_missing_verification_page_falls_back_to_the_activate_page(qtbot, dlg, browser, monkeypatch):
    start = dict(START)
    start.pop("verification_uri")
    fake_api(monkeypatch, start=start)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: dlg.login_btn.isEnabled(), timeout=3000)
    assert browser == ["https://www.twitch.tv/activate"]


def test_a_browser_that_will_not_open_does_not_stop_the_login(qtbot, dlg, host, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("no browser")

    monkeypatch.setattr(td.webbrowser, "open", broken)
    fake_api(monkeypatch)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: host.client is not None, timeout=3000)
    assert config_file()["refresh_token"] == "REFRESH"


def test_a_login_error_shows_a_message_and_frees_the_button(qtbot, dlg, boxes, monkeypatch):
    def refused(*a, **k):
        raise EngineError("Could not reach Twitch:\nno network")

    monkeypatch.setattr(td, "device_login_start", refused)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: bool(boxes.log), timeout=3000)
    assert boxes.log == [("error", "Twitch sign-in", "Could not reach Twitch:\nno network")]
    assert dlg.login_btn.isEnabled() and not dlg.state["busy"] and dlg.code_label.text() == ""
    assert dlg.status_label.text() == "Not signed in."
    assert config_file().get("refresh_token") is None


def test_an_expired_code_shows_the_engines_message(qtbot, dlg, boxes, monkeypatch):
    monkeypatch.setattr(td, "device_login_start", lambda *a, **k: dict(START))

    def expired(*a, **k):
        raise EngineError("The sign-in code expired. Start again.")

    monkeypatch.setattr(td, "device_login_poll", expired)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: bool(boxes.log), timeout=3000)
    assert boxes.log == [("error", "Twitch sign-in", "The sign-in code expired. Start again.")]
    assert dlg.code_label.text() == "" and dlg.login_btn.isEnabled()


def test_a_cancelled_login_just_frees_the_button(qtbot, dlg, boxes, monkeypatch):
    monkeypatch.setattr(td, "device_login_start", lambda *a, **k: dict(START))

    def cancelled(*a, **k):
        raise Cancelled("Sign-in cancelled.")

    monkeypatch.setattr(td, "device_login_poll", cancelled)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: dlg.login_btn.isEnabled(), timeout=3000)
    assert boxes.log == [] and dlg.code_label.text() == ""  # no message for a cancel
    assert dlg.status_label.text() == "Not signed in."


# ------------------------------------------------------------------ the real engine functions, fake HTTP
class Reply:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}
        self.ok = status < 400
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


@pytest.fixture()
def fake_http(monkeypatch):
    """``requests.post`` as the engine sees it: a device code, «pending» a few times, then the tokens."""
    real_sleep = time.sleep
    import core.twitch_api as twitch_api
    monkeypatch.setattr(twitch_api, "time", types.SimpleNamespace(sleep=lambda s: real_sleep(0.005), monotonic=time.monotonic))
    monkeypatch.setattr(engine, "time", types.SimpleNamespace(sleep=lambda s: real_sleep(0.005), monotonic=time.monotonic))
    log = types.SimpleNamespace(calls=[], pending=2, approve=True)

    def post(url, data=None, timeout=None, **kw):
        log.calls.append((url, dict(data or {})))
        if url == engine.DEVICE_URL:
            return Reply(200, {k: v for k, v in START.items() if k != "scopes"})
        if log.pending > 0 or not log.approve:
            log.pending -= 1
            return Reply(400, {"message": "authorization_pending"})
        return Reply(200, {"access_token": "AT", "refresh_token": "RT"})

    monkeypatch.setattr(engine.requests, "post", post)
    return log


def test_the_whole_flow_through_the_real_engine_functions(qtbot, dlg, host, fake_http):
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: host.client is not None, timeout=5000)
    urls = [u for u, _ in fake_http.calls]
    assert urls[0] == engine.DEVICE_URL and urls[1:] == [engine.TOKEN_URL] * 3  # pending, pending, approved
    first = fake_http.calls[0][1]
    assert first["client_id"] == engine.TWITCH_CLIENT_ID
    poll = fake_http.calls[1][1]
    assert poll["device_code"] == "dev123" and poll["grant_type"] == engine.DEVICE_GRANT
    assert config_file()["refresh_token"] == "RT" and config_file()["access_token"] == "AT"


def test_closing_while_waiting_cancels_the_thread_and_saves_nothing(qtbot, dlg, host, fake_http):
    fake_http.approve = False  # the person never approves
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: dlg.code_label.text() == "ABCD-EFGH", timeout=3000)
    thread = next(t for t in threading.enumerate() if t.daemon and t.is_alive() and t.name.startswith("Thread-")
                  and t is not threading.main_thread() and getattr(t, "_target", None) is not None
                  and getattr(t._target, "__qualname__", "").endswith("start_login.<locals>.work"))
    dlg.close()
    assert dlg.cancel_ev.is_set() and dlg.closed
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=3000)  # the poll noticed within a quarter of a second
    qtbot.wait(100)
    assert config_file().get("refresh_token") is None and host.client is None


def test_an_answer_after_the_dialog_was_closed_is_dropped(qtbot, dlg, host):
    dlg.close()
    dlg.signals.ok.emit("A", "R")
    dlg.signals.error.emit("late error")
    dlg.signals.code.emit("XXXX", "https://x")
    dlg.signals.cancelled.emit()
    qtbot.wait(50)
    assert config_file().get("refresh_token") is None and host.client is None
    assert dlg.code_label.text() == ""


@pytest.mark.parametrize("how", ["button", "escape", "window"])
def test_every_way_of_closing_cancels_the_login(qtbot, dlg, monkeypatch, how):
    fake_api(monkeypatch, gate=threading.Event())
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: dlg.code_label.text() != "", timeout=3000)
    if how == "button":
        dlg.close_btn.click()
    elif how == "escape":
        qtbot.keyClick(dlg, Qt.Key.Key_Escape)  # (a Qt habit tkinter's dialog did not have: MIGRATION_LOG.md)
    else:
        dlg.close()
    assert dlg.cancel_ev.is_set() and not dlg.isVisible()


# ------------------------------------------------------------------ signing out
def test_sign_out_removes_the_account_and_the_own_app(qtbot, themed, boxes, browser, host):
    signed_in_file()
    config.save_credentials("cid", "sec")
    host.client = object()
    d = TwitchDialog(host)
    qtbot.addWidget(d)
    d.logout_btn.click()
    assert config_file() == {}
    assert host.client is None and host.statuses == ["Twitch account removed."]
    assert (d.id_edit.text(), d.sec_edit.text()) == ("", "")
    assert d.status_label.text() == "Not signed in." and not d.logout_btn.isEnabled()
    assert d.login_btn.text() == "Sign in with Twitch"


def test_sign_out_keeps_other_settings_of_the_config_file(qtbot, themed, boxes, browser, host):
    config.write_config({"something_else": 1, "refresh_token": "R", "access_token": "A"})
    d = TwitchDialog(host)
    qtbot.addWidget(d)
    d.logout_btn.click()
    assert config_file() == {"something_else": 1}


# ------------------------------------------------------------------ an own Twitch app
class FakeClient:
    behaviour = None  # None = works, or an exception to raise
    made = []

    def __init__(self, client_id, client_secret=None, **kw):
        self.client_id, self.client_secret = client_id, client_secret
        FakeClient.made.append(self)

    def refresh_token(self):
        if FakeClient.behaviour is not None:
            raise FakeClient.behaviour


@pytest.fixture()
def own_app(monkeypatch):
    FakeClient.behaviour, FakeClient.made = None, []
    monkeypatch.setattr(td, "TwitchClient", FakeClient)
    return FakeClient


def test_both_fields_are_needed(dlg, boxes, own_app):
    dlg.id_edit.setText("only-id")
    dlg.save_btn.click()
    dlg.id_edit.setText("   ")
    dlg.sec_edit.setText("only-secret")
    dlg.save_btn.click()
    assert boxes.log == [("warning", "Missing data", "Fill in both fields.")] * 2
    assert own_app.made == [] and config_file() == {}


def test_a_good_own_app_is_checked_and_saved(dlg, host, own_app):
    signed_in_file()  # the own app replaces a signed-in account
    dlg.id_edit.setText("  my-id ")
    dlg.sec_edit.setText("my-secret  ")
    dlg.save_btn.click()
    assert [(c.client_id, c.client_secret) for c in own_app.made] == [("my-id", "my-secret")]  # trimmed, checked
    assert config_file() == {"client_id": "my-id", "client_secret": "my-secret"}
    assert host.client is own_app.made[0]
    assert host.statuses[-1] == "Twitch API credentials saved."
    assert dlg.status_label.text() == "Using your own Twitch app (Client ID / Secret below)."
    assert dlg.logout_btn.isEnabled() and dlg.login_btn.text() == "Sign in with Twitch"


def test_wrong_credentials_show_the_error_and_save_nothing(dlg, host, boxes, own_app):
    own_app.behaviour = ValueError("Invalid Client ID or Client Secret.")
    dlg.id_edit.setText("a")
    dlg.sec_edit.setText("b")
    dlg.save_btn.click()
    assert boxes.log == [("error", "Error", "Invalid Client ID or Client Secret.")]
    assert config_file() == {} and host.client is None


def test_a_network_failure_is_reported_as_one(dlg, host, boxes, own_app):
    own_app.behaviour = requests.ConnectionError("offline")
    dlg.id_edit.setText("a")
    dlg.sec_edit.setText("b")
    dlg.save_btn.click()
    assert boxes.log == [("error", "Network error", "offline")]
    assert config_file() == {} and host.client is None


def test_the_real_client_rejects_bad_credentials_without_a_network(dlg, host, boxes, monkeypatch):
    """Without the fake: the real ``TwitchClient.refresh_token`` against a fake HTTP answer of 401."""
    monkeypatch.setattr(engine.requests, "post", lambda *a, **k: Reply(401, {"message": "invalid client"}))
    dlg.id_edit.setText("bad")
    dlg.sec_edit.setText("bad")
    dlg.save_btn.click()
    assert boxes.log == [("error", "Error", "Invalid Client ID or Client Secret.")]
    assert config_file() == {}


def test_signing_in_with_an_account_replaces_an_own_app_in_the_dialog(qtbot, dlg, host, monkeypatch):
    config.save_credentials("cid", "sec")
    dlg.refresh_status()
    assert dlg.status_label.text().startswith("Using your own")
    fake_api(monkeypatch)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: dlg.status_label.text().startswith("✔"), timeout=3000)
    assert load_creds_none()


def load_creds_none():
    return config.load_credentials() is None


# ------------------------------------------------------------------ in the main window
@pytest.fixture()
def win(qtbot, themed, boxes, browser):
    w = mw.MainWindow(settings=dict(DEFAULTS))  # nobody signed in
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    yield w
    if w._login_dialog is not None:
        w._login_dialog.close()
    w.tab_search.shutdown()


def test_the_twitch_api_button_and_the_banner_open_the_dialog(qtbot, win):
    win.api_btn.click()
    first = win._login_dialog
    assert isinstance(first, TwitchDialog) and first.isVisible() and first.parent() is win
    first.close()
    win.tab_search.signin_btn.click()
    assert win._login_dialog is not first and win._login_dialog.isVisible()


def test_opening_it_again_closes_the_old_one(qtbot, win, monkeypatch):
    fake_api(monkeypatch, gate=threading.Event())
    win.ask_credentials()
    old = win._login_dialog
    old.login_btn.click()
    qtbot.waitUntil(lambda: old.code_label.text() != "", timeout=3000)
    win.ask_credentials()
    assert old.cancel_ev.is_set() and win._login_dialog is not old


def test_signing_in_from_the_dialog_turns_the_search_tab_on(qtbot, win, monkeypatch):
    tab = win.tab_search
    assert tab.signin_bar.isVisibleTo(tab) and not tab.search_btn.isEnabled()
    fake_api(monkeypatch)
    win.ask_credentials()
    win._login_dialog.login_btn.click()
    qtbot.waitUntil(lambda: win.client is not None, timeout=3000)
    assert isinstance(win.client, TwitchClient)
    assert not tab.signin_bar.isVisibleTo(tab) and tab.search_btn.isEnabled()
    assert win.status_label.text() == "Signed in with Twitch."


def test_signing_out_turns_it_off_again(qtbot, win):
    signed_in_file()
    win.client = config.make_client()
    assert win.tab_search.search_btn.isEnabled()
    win.ask_credentials()
    win._login_dialog.logout_btn.click()
    assert win.client is None and not win.tab_search.search_btn.isEnabled()
    assert win.tab_search.signin_bar.isVisibleTo(win.tab_search)
    assert win.status_label.text() == "Twitch account removed."


def test_closing_the_window_closes_the_dialog_and_cancels_the_login(qtbot, win, monkeypatch):
    fake_api(monkeypatch, gate=threading.Event())
    win.ask_credentials()
    dialog = win._login_dialog
    dialog.login_btn.click()
    qtbot.waitUntil(lambda: dialog.code_label.text() != "", timeout=3000)
    win.close()
    assert dialog.cancel_ev.is_set() and dialog.closed



def test_copy_code_button_copies_device_code_to_clipboard(qtbot, dlg):
    assert not dlg.copy_code_btn.isVisible()
    dlg.on_code("WXYZ-1234", "https://www.twitch.tv/activate")
    assert not dlg.copy_code_btn.isHidden()
    dlg.copy_code_btn.click()
    assert QApplication.clipboard().text() == "WXYZ-1234"
    assert dlg.copy_code_btn.text() == "Copied!"


def test_save_own_app_runs_refresh_token_off_gui_thread(qtbot, dlg, host, monkeypatch):
    gate = threading.Event()
    refresh_threads = []

    class SlowClient:
        def __init__(self, client_id, client_secret=None, **kw):
            self.client_id = client_id
            self.client_secret = client_secret

        def refresh_token(self):
            refresh_threads.append(threading.current_thread())
            gate.wait(timeout=3.0)

    monkeypatch.setattr(td, "TwitchClient", SlowClient)
    dlg.id_edit.setText("cid-async")
    dlg.sec_edit.setText("sec-async")
    dlg.save_btn.click()

    assert not dlg.save_btn.isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: dlg.save_btn.isEnabled(), timeout=3000)
    assert len(refresh_threads) == 1
    assert refresh_threads[0] is not threading.main_thread()
    assert config_file() == {"client_id": "cid-async", "client_secret": "sec-async"}

