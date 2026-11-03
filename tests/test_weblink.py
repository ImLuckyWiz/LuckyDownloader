"""Links that open the app (weblink.py): reading them, refusing bad ones, passing one to the window that is
already open, and registering the scheme. No GUI and no network."""

import threading
import time

import pytest

import weblink as wl
from weblink import LinkError, OpenRequest, build_link, parse_link

VOD = "https://www.twitch.tv/videos/123456789"


# --------------------------------------------------------------------------- reading a link
def test_a_simple_link():
    req = parse_link(f"luckydownloader://open?url={VOD}")
    assert req == OpenRequest(url=VOD, cuts="", label="")
    req_legacy = parse_link(f"luckytwitch://open?url={VOD}")
    assert req_legacy == req
    assert req == OpenRequest(url=VOD, cuts="", label="")


def test_url_encoded_values_are_decoded():
    link = "luckytwitch://open?url=https%3A%2F%2Fwww.twitch.tv%2Fvideos%2F1&cuts=0%3A20%3A00%20to%203%3A30%3A00&label=Big%20Stream"
    req = parse_link(link)
    assert req.url == "https://www.twitch.tv/videos/1"
    assert req.cuts == "0:20:00 to 3:30:00"
    assert req.label == "Big Stream"


def test_build_link_and_parse_link_agree():
    cuts = "0:00:00 - 30:00 ; 2:00:00 - end"
    link = build_link(VOD + "?t=1h2m", cuts, "Ünïcode & symbols = ok")
    assert link.startswith("luckydownloader://open?v=1&url=")
    legacy = build_link(VOD + "?t=1h2m", cuts, "Ünïcode & symbols = ok", scheme="luckytwitch")
    assert legacy.startswith("luckytwitch://open?v=1&url=")
    assert parse_link(legacy) == parse_link(link)
    assert " " not in link
    assert parse_link(link) == OpenRequest(url=VOD + "?t=1h2m", cuts=cuts, label="Ünïcode & symbols = ok")


@pytest.mark.parametrize("link", [
    f"luckytwitch://open/?url={VOD}",  # a trailing slash, as Windows sometimes adds
    f"LuckyTwitch://OPEN?url={VOD}",
    f'"luckytwitch://open?url={VOD}"',  # quoted, as it arrives on a command line
    f"luckytwitch:open?url={VOD}",
])
def test_harmless_variations_are_accepted(link):
    assert parse_link(link).url == VOD


def test_cuts_can_have_several_lines():
    link = "luckytwitch://open?url=" + VOD + "&cuts=0%3A00%20-%2030%3A00%0A1%3A00%3A00%20-%20end"
    assert parse_link(link).cuts == "0:00 - 30:00\n1:00:00 - end"


def test_control_characters_are_dropped():
    link = "luckytwitch://open?url=" + VOD + "&label=a%00b%07c&cuts=1%3A00%00"
    req = parse_link(link)
    assert req.label == "abc" and req.cuts == "1:00"


def test_the_first_value_of_a_repeated_parameter_wins_and_unknown_ones_are_ignored():
    req = parse_link(f"luckytwitch://open?url={VOD}&url=https://evil.example/x&future=1")
    assert req.url == VOD


@pytest.mark.parametrize("link, fragment", [
    ("https://www.twitch.tv/videos/1", "not a luckydownloader"),
    ("luckytwitch://open", "which VOD"),
    ("luckytwitch://open?url=", "which VOD"),
    ("luckytwitch://download?url=" + VOD, "does not know"),
    ("luckytwitch://open?v=99&url=" + VOD, "newer version"),
    ("luckytwitch://open?v=x&url=" + VOD, "version"),
    ("luckytwitch://open?url=ftp://example.com/a.mp4", "http"),
    ("luckytwitch://open?url=file:///etc/passwd", "http"),
    ("luckytwitch://open?url=javascript:alert(1)", "http"),
    ("luckytwitch://open?url=https://user:pass@example.com/v", "user name"),
    ("luckytwitch://open?url=https://example.com/a%20b", "spaces"),
])
def test_bad_links_are_refused_with_a_readable_message(link, fragment):
    with pytest.raises(LinkError) as err:
        parse_link(link)
    assert fragment in str(err.value)


@pytest.mark.parametrize("host", [
    "localhost", "foo.localhost", "printer.local", "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.9",
    "169.254.169.254", "[::1]", "0.0.0.0", "nas.internal",
])
def test_addresses_on_this_computer_or_network_are_refused(host):
    with pytest.raises(LinkError) as err:
        parse_link(f"luckytwitch://open?url=http://{host}/video")
    assert "private network" in str(err.value)


def test_public_addresses_are_fine():
    assert parse_link("luckytwitch://open?url=https://8.8.8.8/v").url == "https://8.8.8.8/v"
    assert parse_link("luckytwitch://open?url=https://clips.example.com/v").url == "https://clips.example.com/v"


def test_limits():
    with pytest.raises(LinkError):
        parse_link("luckytwitch://open?url=https://example.com/" + "a" * wl.MAX_URL)
    with pytest.raises(LinkError):
        parse_link(f"luckytwitch://open?url={VOD}&cuts=" + "1" * (wl.MAX_CUTS + 1))
    with pytest.raises(LinkError):
        parse_link(f"luckytwitch://open?url={VOD}&label=" + "x" * (wl.MAX_LABEL + 1))
    with pytest.raises(LinkError):
        parse_link("luckytwitch://open?url=" + VOD + "&pad=" + "x" * wl.MAX_LINK)


def test_find_link_in_the_command_line():
    assert wl.find_link([]) is None
    assert wl.find_link(["--debug", "notes.txt"]) is None
    assert wl.find_link(["--x", f"luckytwitch://open?url={VOD}"]) == f"luckytwitch://open?url={VOD}"
    assert wl.find_link([f'"LuckyTwitch://open?url={VOD}"']) == f"LuckyTwitch://open?url={VOD}"


# --------------------------------------------------------------------------- passing it to the open window
def test_no_heartbeat_means_nobody_is_running(tmp_path):
    assert not wl.is_running(tmp_path / "beat")
    assert wl.hand_off("luckytwitch://open?url=x", tmp_path / "inbox", tmp_path / "beat", wait=0.2) is False
    assert not (tmp_path / "inbox").exists() or not list((tmp_path / "inbox").glob("*"))


def test_an_old_heartbeat_does_not_count(tmp_path):
    beat = tmp_path / "beat"
    beat.write_text(str(time.time() - 60))
    assert not wl.is_running(beat)
    wl.beat(beat)
    assert wl.is_running(beat)
    assert not wl.is_running(beat, now=time.time() + 60)


def test_garbage_in_the_heartbeat_file_means_not_running(tmp_path):
    beat = tmp_path / "beat"
    beat.write_text("not a number")
    assert not wl.is_running(beat)


def test_a_link_is_handed_to_the_running_window(tmp_path):
    inbox, beat = tmp_path / "inbox", tmp_path / "beat"
    wl.beat(beat)
    taken: list[str] = []

    def window():  # the running app polls its folder
        for _ in range(50):
            taken.extend(wl.take_links(inbox))
            if taken:
                return
            time.sleep(0.05)

    t = threading.Thread(target=window)
    t.start()
    assert wl.hand_off("luckytwitch://open?url=" + VOD, inbox, beat, wait=3, poll=0.02) is True
    t.join()
    assert taken == ["luckytwitch://open?url=" + VOD]
    assert not list(inbox.glob("*"))


def test_when_the_window_does_not_answer_the_link_is_taken_back(tmp_path):
    inbox, beat = tmp_path / "inbox", tmp_path / "beat"
    wl.beat(beat)  # a heartbeat that is fresh, but nobody reads the folder (a window that just crashed)
    assert wl.hand_off("luckytwitch://open?url=" + VOD, inbox, beat, wait=0.3, poll=0.02) is False
    assert wl.take_links(inbox) == []  # not left behind: it would be opened twice


def test_links_come_out_oldest_first_and_only_once(tmp_path):
    inbox = tmp_path / "inbox"
    for i in range(3):
        wl._drop(inbox, f"luckytwitch://open?url=https://example.com/{i}")
        time.sleep(0.002)
    assert wl.take_links(inbox) == [f"luckytwitch://open?url=https://example.com/{i}" for i in range(3)]
    assert wl.take_links(inbox) == []


def test_stale_and_oversized_floods_are_ignored(tmp_path):
    inbox = tmp_path / "inbox"
    path = wl._drop(inbox, "luckytwitch://open?url=" + VOD)
    assert wl.take_links(inbox, now=path.stat().st_mtime + wl.MAX_AGE + 5) == []  # too old, and removed
    assert not list(inbox.glob("*.link"))
    for i in range(wl.MAX_WAITING):
        assert wl._drop(inbox, f"l{i}") is not None
        time.sleep(0.001)
    assert wl._drop(inbox, "one more") is None  # the folder is full


def test_unfinished_files_are_never_read(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "123.tmp").write_text("luckytwitch://open?url=" + VOD)
    assert wl.take_links(inbox) == []


# --------------------------------------------------------------------------- registering the scheme (Windows)
class FakeWinreg:
    """Just enough of winreg, keeping the keys in a dict."""
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.data: dict[tuple[str, str], str] = {}

    class _Key:
        def __init__(self, owner, path):
            self.owner, self.path = owner, path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def CreateKeyEx(self, root, path, reserved, access):
        return self._Key(self, path)

    def OpenKey(self, root, path):
        if not any(p == path for p, _ in self.data):
            raise FileNotFoundError(path)
        return self._Key(self, path)

    def SetValueEx(self, key, name, reserved, kind, value):
        self.data[(key.path, name)] = value

    def QueryValueEx(self, key, name):
        return self.data[(key.path, name)], self.REG_SZ


COMMAND = '"C:\\Users\\me\\AppData\\Local\\Programs\\LuckyTwitch\\LuckyTwitch.exe" "%1"'


def test_registration_roundtrip():
    reg = FakeWinreg()
    assert wl.registration(COMMAND, reg=reg) == wl.Registration(True, "missing")
    wl.register(COMMAND, reg=reg)
    assert wl.registration(COMMAND, reg=reg).state == "ok"
    assert reg.data[(r"Software\Classes\luckydownloader", "URL Protocol")] == ""
    assert reg.data[(r"Software\Classes\luckydownloader\shell\open\command", "")] == COMMAND
    assert reg.data[(r"Software\Classes\luckytwitch", "URL Protocol")] == ""
    assert reg.data[(r"Software\Classes\luckytwitch\shell\open\command", "")] == COMMAND


def test_registration_notices_another_copy_of_the_app():
    reg = FakeWinreg()
    wl.register('"D:\\old\\LuckyTwitch.exe" "%1"', reg=reg)
    status = wl.registration(COMMAND, reg=reg)
    assert status.state == "other" and "old" in status.command
    wl.register(COMMAND, reg=reg)  # registering again takes it over
    assert wl.registration(COMMAND, reg=reg).state == "ok"


def test_registration_ignores_case_in_paths():
    reg = FakeWinreg()
    wl.register(COMMAND, reg=reg)
    assert wl.registration(COMMAND, reg=reg).state == "ok"


def test_not_supported_outside_windows(monkeypatch):
    monkeypatch.setattr(wl.sys, "platform", "darwin")
    assert wl.registration().state == "unsupported"
    assert wl.registration().supported is False
    with pytest.raises(OSError):
        wl.register()


def test_blocked_host_encodings():
    assert wl._blocked_host("2130706433")
    assert wl._blocked_host("0x7f000001")
    assert wl._blocked_host("0177.0.0.1")
    assert wl._blocked_host("127.0.0.1")
    assert wl._blocked_host("localhost")
    assert not wl._blocked_host("example.com")
    assert not wl._blocked_host("twitch.tv")
    assert not wl._blocked_host("youtube.com")


def test_launch_command_for_the_packaged_app_and_for_source(monkeypatch):
    assert wl.launch_command(exe="C:\\App\\LuckyTwitch.exe") == '"C:\\App\\LuckyTwitch.exe" "%1"'
    monkeypatch.delattr(wl.sys, "frozen", raising=False)
    cmd = wl.launch_command(script="/x/luckytwitch_downloader.py")
    assert cmd.endswith('"/x/luckytwitch_downloader.py" "%1"') and cmd.startswith('"')
