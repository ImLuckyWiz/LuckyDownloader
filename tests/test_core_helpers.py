"""The UI-free helpers in core/ (settings, recent, config, status, log, paths): no Tk, no Qt, no display.

Paths are redirected to a temp folder by monkeypatching the attributes of ``core.paths`` (the other core
modules read them when they are called), so nothing here touches the real settings or the Twitch login.
"""

import json
import re
from pathlib import Path

import pytest

from core import config, paths, recent, resources, settings, status

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "settings_written_by_tk.json"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(paths, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(paths, "SETTINGS_PATH", tmp_path / "luckytwitch_settings.json")
    monkeypatch.setattr(paths, "RECENT_PATH", tmp_path / "luckytwitch_recent.json")
    monkeypatch.setattr(paths, "LINKS_DIR", tmp_path / "links")
    monkeypatch.setattr(paths, "BEAT_PATH", tmp_path / "running.beat")
    return tmp_path


# ------------------------------------------------------------------ paths
def test_paths_use_the_same_file_names_as_the_tkinter_app():
    assert paths.CONFIG_PATH.name == "config.json"
    assert paths.SETTINGS_PATH.name == "luckytwitch_settings.json"
    assert paths.RECENT_PATH.name == "luckytwitch_recent.json"
    assert paths.LINKS_DIR.name == "links" and paths.BEAT_PATH.name == "running.beat"
    assert paths.MAX_RECENT == 12
    for p in (paths.CONFIG_PATH, paths.SETTINGS_PATH, paths.RECENT_PATH, paths.LINKS_DIR, paths.BEAT_PATH):
        assert p.parent == paths.DATA_DIR


def test_ensure_data_dir_creates_the_folder_and_never_raises(tmp_path, monkeypatch):
    target = tmp_path / "a" / "b"
    monkeypatch.setattr(paths, "DATA_DIR", target)
    paths.ensure_data_dir()
    assert target.is_dir()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(paths, "DATA_DIR", blocker / "sub")  # cannot be created: must stay silent
    paths.ensure_data_dir()


def test_resource_path_points_into_the_project():
    assert resources.resource_path("assets", "icon.png").is_file()


# ------------------------------------------------------------------ settings
def test_defaults_are_the_42_documented_keys_with_the_documented_types():
    d = settings.DEFAULTS
    assert len(d) == 50
    assert sum(isinstance(v, bool) for v in d.values()) == 18
    assert sum(isinstance(v, str) for v in d.values()) == 31
    assert sum(isinstance(v, dict) for v in d.values()) == 1
    expected_bools = {
        "exact", "keep_full", "chapters", "sidecar", "premiere_xml",
        "premiere_plugin", "game_markers", "muted_markers", "chat",
        "chat_embed", "chat_render", "chat_render_smooth", "subfolders", "auto_update", "clean_title",
        "check_app_updates", "provider_subfolders", "save_history",
    }
    assert {k for k, v in d.items() if isinstance(v, bool)} == expected_bools
    for k, v in d.items():
        if k in expected_bools:
            assert isinstance(v, bool), f"{k} should be bool"
        elif isinstance(v, dict):
            assert isinstance(v, dict), f"{k} should be dict"
        else:
            assert isinstance(v, str), f"{k} should be str" 


def test_load_settings_without_a_file_gives_the_defaults(data_dir):
    assert settings.load_settings() == settings.DEFAULTS


def test_load_settings_with_a_broken_file_gives_the_defaults(data_dir):
    paths.SETTINGS_PATH.write_text("{not json", encoding="utf-8")
    assert settings.load_settings() == settings.DEFAULTS


def test_load_settings_overlays_known_keys_and_drops_unknown_ones(data_dir):
    paths.SETTINGS_PATH.write_text(json.dumps({"threads": "2", "exact": True, "old_key": 1}), encoding="utf-8")
    got = settings.load_settings()
    assert got["threads"] == "2" and got["exact"] is True
    assert "old_key" not in got
    assert {k: v for k, v in got.items() if k not in ("threads", "exact")} == \
        {k: v for k, v in settings.DEFAULTS.items() if k not in ("threads", "exact")}


def test_settings_file_written_by_the_tkinter_app_loads_with_every_value(data_dir):
    """tests/fixtures/settings_written_by_tk.json was written by the real tkinter App (v1.16.0) with a value that
    differs from the default in every one of the 38 keys (default_quality and audio_format were added by hand)."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(raw).issubset(set(settings.DEFAULTS))
    assert all(raw[k] != settings.DEFAULTS[k] for k in raw)
    paths.SETTINGS_PATH.write_bytes(FIXTURE.read_bytes())
    loaded = settings.load_settings()
    for k in raw:
        assert loaded[k] == raw[k]
    assert loaded["clean_title"] is True
    assert loaded["default_quality"] == "720p"
    assert loaded["audio_format"] == "mp3 · converted"
    assert loaded["gap_title"] == "Charla ñandú"  # non-ASCII survives the JSON escapes


def test_a_settings_file_with_windows_line_endings_loads_too(data_dir):
    crlf = FIXTURE.read_bytes().replace(b"\n", b"\r\n")  # the tkinter app writes CRLF on Windows
    paths.SETTINGS_PATH.write_bytes(crlf)
    loaded = settings.load_settings()
    for k, v in json.loads(FIXTURE.read_text(encoding="utf-8")).items():
        assert loaded[k] == v
    assert loaded["clean_title"] is True


def test_settings_round_trip_keeps_every_key_and_type(data_dir):
    paths.SETTINGS_PATH.write_bytes(FIXTURE.read_bytes())
    loaded = settings.load_settings()
    settings.save_settings(loaded)
    again = settings.load_settings()
    assert again == loaded
    assert {k: type(v) for k, v in again.items()} == {k: type(v) for k, v in settings.DEFAULTS.items()}
    # the file is what json.dumps(indent=2) gives, like the tkinter app writes it
    assert paths.SETTINGS_PATH.read_text(encoding="utf-8") == json.dumps(loaded, indent=2)


def test_save_settings_ignores_a_folder_that_cannot_be_written(data_dir, monkeypatch):
    monkeypatch.setattr(paths, "SETTINGS_PATH", data_dir / "missing" / "s.json")
    settings.save_settings({"threads": "2"})  # must not raise


# ------------------------------------------------------------------ recent
def test_recent_round_trip_and_cleanup(data_dir):
    assert recent.load_recent() == []
    items = [{"id": "1", "login": "a", "name": "A"}, {"id": "2", "login": "b", "name": "B"}]
    recent.save_recent(items)
    assert recent.load_recent() == items
    paths.RECENT_PATH.write_text(json.dumps([
        {"id": 7, "login": "x"}, {"login": "no id"}, "junk", {"id": "9", "login": None, "name": None},
    ]), encoding="utf-8")
    assert recent.load_recent() == [{"id": "7", "login": "x", "name": "x"}, {"id": "9", "login": "", "name": ""}]


def test_recent_is_capped_and_survives_bad_files(data_dir, monkeypatch):
    paths.RECENT_PATH.write_text(json.dumps([{"id": str(i), "login": f"l{i}"} for i in range(30)]), encoding="utf-8")
    assert len(recent.load_recent()) == paths.MAX_RECENT
    paths.RECENT_PATH.write_text("{}", encoding="utf-8")
    assert recent.load_recent() == []
    paths.RECENT_PATH.write_text("nope", encoding="utf-8")
    assert recent.load_recent() == []
    monkeypatch.setattr(paths, "RECENT_PATH", data_dir / "missing" / "r.json")
    recent.save_recent([{"id": "1"}])  # must not raise


# ------------------------------------------------------------------ config and credentials
def test_credentials_and_tokens_round_trip(data_dir):
    assert config.read_config() == {} and config.load_credentials() is None and config.make_client() is None
    config.save_credentials("cid", "sec")
    assert config.load_credentials()["client_id"] == "cid"
    config.save_login_tokens("acc", "ref")
    assert config.read_config()["refresh_token"] == "ref"
    config.clear_credentials()
    assert config.load_credentials() is None and config.read_config()["access_token"] == "acc"
    config.save_login_tokens(None, None)
    assert config.read_config() == {}


def test_make_client_prefers_the_own_app_then_the_signed_in_user(data_dir):
    config.save_login_tokens("acc", "ref")
    c = config.make_client()
    assert c is not None and c.user_refresh == "ref" and c.token == "acc" and c.uses_login
    config.save_credentials("cid", "sec")
    c2 = config.make_client()
    assert c2.client_id == "cid" and c2.client_secret == "sec" and not c2.uses_login


def test_a_config_file_that_is_not_an_object_is_ignored(data_dir):
    paths.CONFIG_PATH.write_text("[1, 2]", encoding="utf-8")
    assert config.read_config() == {}


# ------------------------------------------------------------------ status and log helpers
@pytest.mark.parametrize("text, word, label", [
    ("queued", "queued", "○ queued"), ("running…", "running", "▶ running…"),
    ("done (3 files)", "done", "✓ done (3 files)"), ("failed", "failed", "✕ failed"),
    ("cancelled", "cancelled", "■ cancelled"), ("", "", ""), ("weird thing", "weird", "weird thing"),
])
def test_status_word_and_label(text, word, label):
    assert status.status_word(text) == word
    assert status.status_label(text) == label


@pytest.mark.parametrize("msg, kind", [
    ("ERROR: boom", "err"), ("Warning: x", "warn"), ("Could not read", "warn"), ("Cancelled.", "warn"),
    ("Server busy, retrying", "warn"), ("part 2 failed", "warn"), ("2 skipped", "warn"), ("ffmpeg not found", "warn"),
    ("✔ saved", "ok"), ("yt-dlp is up to date.", "ok"), ("ffmpeg installed.", "ok"),
    ("Queued: video 1", "muted"), ("just some text", "plain"), ("   ERROR with indent", "err"),
])
def test_log_kind(msg, kind):
    assert status.log_kind(msg) == kind


def test_queue_summary():
    assert status.queue_summary([]) == ""
    assert status.queue_summary(["running…", "queued", "queued", "done (2 files)", "failed", "cancelled"]) == \
        "1 running  ·  2 queued  ·  1 done  ·  1 failed  ·  1 cancelled"
    assert status.FINISHED == ("done", "failed", "cancelled")
    assert set(status.STATUS_COLOURS) == set(status.STATUS_ICONS)


# ------------------------------------------------------------------ legacy migration
def test_resolve_legacy_data_dir():
    assert paths.resolve_legacy_data_dir(frozen=False) is None
    stable = paths.resolve_legacy_data_dir(frozen=True, version="1.0")
    assert stable is not None
    assert stable.name == "LuckyTwitch"
    beta = paths.resolve_legacy_data_dir(frozen=True, version="v0.8.0-beta.1")
    assert beta is not None
    assert beta.name == "LuckyTwitch-beta"


def test_migrate_from_legacy_copies_files_without_deleting_or_overwriting(tmp_path):
    src = tmp_path / "legacy_twitch"
    dest = tmp_path / "new_downloader"
    src.mkdir()
    (src / "config.json").write_text('{"token": "xyz"}', encoding="utf-8")
    (src / "luckytwitch_settings.json").write_text('{"quality": "best"}', encoding="utf-8")
    (src / "luckytwitch_history.json").write_text('["vid1"]', encoding="utf-8")
    src_tools = src / "tools"
    src_tools.mkdir()
    (src_tools / "yt-dlp.exe").write_text("dummy-binary", encoding="utf-8")

    dest.mkdir()
    (dest / "config.json").write_text('{"token": "existing"}', encoding="utf-8")

    copied = paths.migrate_from_legacy(src=src, dest=dest)

    assert "config.json" not in copied
    assert "luckytwitch_settings.json" in copied
    assert "luckytwitch_history.json" in copied
    assert "tools/yt-dlp.exe" in copied

    assert (dest / "config.json").read_text(encoding="utf-8") == '{"token": "existing"}'
    assert (dest / "luckytwitch_settings.json").read_text(encoding="utf-8") == '{"quality": "best"}'
    assert (dest / "tools" / "yt-dlp.exe").read_text(encoding="utf-8") == "dummy-binary"

    assert (src / "config.json").is_file()
    assert (src / "luckytwitch_settings.json").is_file()
    assert (src_tools / "yt-dlp.exe").is_file()

    # Second migration does nothing because files already exist
    assert paths.migrate_from_legacy(src=src, dest=dest) == []
    # If src does not exist or equals dest, returns []
    assert paths.migrate_from_legacy(src=tmp_path / "nonexistent", dest=dest) == []
    assert paths.migrate_from_legacy(src=dest, dest=dest) == []
    assert paths.migrate_from_legacy(src=None, dest=dest) == []


def test_extract_uninstaller_exe(tmp_path):
    dummy_exe = tmp_path / "unins000.exe"
    dummy_exe.write_text("bin", encoding="utf-8")

    assert paths._extract_uninstaller_exe("") is None
    assert paths._extract_uninstaller_exe(f'"{dummy_exe}"') == dummy_exe
    assert paths._extract_uninstaller_exe(f'"{dummy_exe}" /SILENT') == dummy_exe
    assert paths._extract_uninstaller_exe(f"{dummy_exe} /SILENT") == dummy_exe
    assert paths._extract_uninstaller_exe(str(tmp_path / "nonexistent.exe")) is None


def test_find_legacy_uninstaller_guard_and_detection(tmp_path, monkeypatch):
    mock_local = tmp_path / "localappdata"
    twitch_dir = mock_local / "Programs" / "LuckyTwitch"
    twitch_dir.mkdir(parents=True)
    uninst = twitch_dir / "unins000.exe"
    uninst.write_text("bin", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(mock_local))
    monkeypatch.setattr(paths.sys, "platform", "win32")

    # If current_exe_dir is the same directory as uninstaller, must ignore it (self-protection)
    assert paths.find_legacy_uninstaller(current_exe_dir=twitch_dir) is None

    # If current_exe_dir is LuckyDownloader, it finds LuckyTwitch uninstaller
    downloader_dir = mock_local / "Programs" / "LuckyDownloader"
    found = paths.find_legacy_uninstaller(current_exe_dir=downloader_dir)
    assert found == uninst


def test_cleanup_legacy_shortcuts(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shortcut1 = desktop / "LuckyTwitch.lnk"
    shortcut1.write_text("dummy", encoding="utf-8")

    appdata = tmp_path / "AppData" / "Roaming"
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True)
    shortcut2 = programs / "LuckyTwitch.lnk"
    shortcut2.write_text("dummy", encoding="utf-8")

    twitch_folder = programs / "LuckyTwitch"
    twitch_folder.mkdir()
    shortcut3 = twitch_folder / "LuckyTwitch.lnk"
    shortcut3.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths.sys, "platform", "win32")

    assert shortcut1.is_file()
    assert shortcut2.is_file()
    assert shortcut3.is_file()

    removed = paths.cleanup_legacy_shortcuts()

    assert not shortcut1.exists()
    assert not shortcut2.exists()
    assert not shortcut3.exists()
    assert not twitch_folder.exists()
    assert len(removed) >= 3


def test_uninstall_legacy_app_launches_subprocess(tmp_path, monkeypatch):
    dummy_uninst = tmp_path / "unins000.exe"
    dummy_uninst.write_text("bin", encoding="utf-8")

    launched_cmds = []

    class DummyProc:
        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        launched_cmds.append(cmd)
        return DummyProc()

    monkeypatch.setattr(paths.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(paths, "cleanup_legacy_shortcuts", lambda: [])

    # Without uninstaller
    assert paths.uninstall_legacy_app(uninst_path=None) is False
    assert len(launched_cmds) == 0

    # With uninstaller
    ok = paths.uninstall_legacy_app(uninst_path=dummy_uninst, wait=True)
    assert ok is True
    assert len(launched_cmds) == 1
    assert launched_cmds[0] == [str(dummy_uninst), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"]


def test_ensure_data_dir_runs_uninstaller_when_frozen(tmp_path, monkeypatch):
    uninstalled = []
    migrated = []
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(paths, "migrate_from_legacy", lambda: migrated.append(True) or [])
    monkeypatch.setattr(paths, "uninstall_legacy_app", lambda: uninstalled.append(True) or True)

    paths.ensure_data_dir()
    assert len(migrated) == 1
    assert len(uninstalled) == 1


def test_settings_corrupt_file_backup(tmp_path, monkeypatch):
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr(paths, "SETTINGS_PATH", test_file)
    test_file.write_text("NOT VALID JSON {{{", encoding="utf-8")
    loaded = settings.load_settings()
    assert loaded["container"] == settings.DEFAULTS["container"]
    assert list(tmp_path.glob("settings.json.corrupt*"))

def test_corrupt_files_backed_up_across_all_storage(tmp_path, monkeypatch):
    import core.history as history
    import core.watchlist as watchlist
    import core.ui_state as ui_state
    import core.config as config
    import core.tools as tools

    # History
    hist_file = tmp_path / "hist.json"
    hist_file.write_text("CORRUPT JSON", encoding="utf-8")
    assert history.load_history(hist_file) == []
    assert list(tmp_path.glob("hist.json.corrupt*"))

    # Watchlist
    watch_file = tmp_path / "watch.json"
    watch_file.write_text("CORRUPT JSON", encoding="utf-8")
    assert watchlist.load_watchlist(watch_file) == []
    assert list(tmp_path.glob("watch.json.corrupt*"))

    # UI state
    ui_file = tmp_path / "ui.json"
    ui_file.write_text("CORRUPT JSON", encoding="utf-8")
    assert ui_state.load_ui_state(ui_file) == ui_state.UIState()
    assert list(tmp_path.glob("ui.json.corrupt*"))

    # Config
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("CORRUPT JSON", encoding="utf-8")
    monkeypatch.setattr(paths, "CONFIG_PATH", cfg_file)
    assert config.read_config() == {}
    assert list(tmp_path.glob("config.json.corrupt*"))

    # Tools versions.json
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    ver_file = tools_dir / "versions.json"
    ver_file.write_text("CORRUPT JSON", encoding="utf-8")
    monkeypatch.setattr(tools, "TOOLS_DIR", tools_dir)
    assert tools._read_versions() == {}
    assert list(tools_dir.glob("versions.json.corrupt*"))



def test_settings_list_json_backup(tmp_path, monkeypatch):
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr(paths, "SETTINGS_PATH", test_file)
    test_file.write_text("[]", encoding="utf-8")
    loaded = settings.load_settings()
    assert loaded["container"] == settings.DEFAULTS["container"]
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_migration_sentinel_prevents_re_migration(tmp_path):
    src = tmp_path / "legacy"
    src.mkdir()
    (src / "config.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "dest"
    
    res1 = paths.migrate_from_legacy(src, dest)
    assert "config.json" in res1
    assert (dest / ".migrated_from_luckytwitch").exists()
    
    (dest / "config.json").unlink()
    
    res2 = paths.migrate_from_legacy(src, dest)
    assert res2 == []
    assert not (dest / "config.json").exists()


def test_mac_ffmpeg_sources_have_pinned_sha256_and_verify(tmp_path, monkeypatch):
    import hashlib
    import zipfile
    from core import tools
    from core.errors import EngineError
    from core.runtime import Ctx

    for arch in ("arm64", "x86_64"):
        monkeypatch.setattr(tools.platform, "machine", lambda a=arch: a)
        for tool in ("ffmpeg", "ffprobe"):
            sources = tools._mac_ffmpeg_sources(tool)
            assert len(sources) == 3
            for _label, url in sources:
                digest = tools._MAC_FFMPEG_SHA256.get(url, "")
                assert len(digest) == 64

    monkeypatch.setattr(tools, "TOOLS_DIR", tmp_path)

    # Create valid zip archives for ffmpeg and ffprobe
    zips = {}
    for tool in ("ffmpeg", "ffprobe"):
        zp = tmp_path / f"src_{tool}.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr(tool, f"fake-{tool}-binary")
        zips[tool] = zp

    # 1. Mismatched SHA-256 must fail and not extract binaries
    monkeypatch.setattr(
        tools,
        "_download_with_retry",
        lambda ctx, url, dest, attempts=3: dest.write_bytes(zips["ffmpeg"].read_bytes()),
    )
    with pytest.raises(EngineError):
        tools._install_ffmpeg_macos(Ctx())
    assert not (tmp_path / "ffmpeg").exists()

    # 2. Matching SHA-256 extracts both binaries
    def fake_dl_matching(ctx, url, dest, attempts=3):
        tool = "ffprobe" if "ffprobe" in url else "ffmpeg"
        data = zips[tool].read_bytes()
        dest.write_bytes(data)
        monkeypatch.setitem(tools._MAC_FFMPEG_SHA256, url, hashlib.sha256(data).hexdigest())

    monkeypatch.setattr(tools, "_download_with_retry", fake_dl_matching)
    tools._install_ffmpeg_macos(Ctx())
    assert (tmp_path / "ffmpeg").read_text(encoding="utf-8") == "fake-ffmpeg-binary"
    assert (tmp_path / "ffprobe").read_text(encoding="utf-8") == "fake-ffprobe-binary"


# ------------------------------------------------------------------ U-DATA-01 & U-DATA-02
def test_dpapi_secrets_and_legacy_migration(data_dir, monkeypatch):
    import base64
    import sys

    if sys.platform != "win32":
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setattr(
            config,
            "_dpapi_encrypt",
            lambda s: config.DPAPI_PREFIX + base64.b64encode(s.encode("utf-8")).decode("ascii"),
        )
        monkeypatch.setattr(
            config,
            "_dpapi_decrypt",
            lambda t: base64.b64decode(t[len(config.DPAPI_PREFIX):]).decode("utf-8"),
        )

    config.save_credentials("cid-123", "my-client-secret")
    config.save_login_tokens("acc-tok", "ref-tok", user_login="lucky")

    raw_text = paths.CONFIG_PATH.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    assert raw["client_id"] == "cid-123"
    assert raw["user_login"] == "lucky"
    for key, plain in (("client_secret", "my-client-secret"), ("access_token", "acc-tok"), ("refresh_token", "ref-tok")):
        assert raw[key].startswith(config.DPAPI_PREFIX)
        assert plain not in raw_text

    loaded = config.load_config()
    assert loaded == {
        "client_id": "cid-123",
        "user_login": "lucky",
        "client_secret": "my-client-secret",
        "access_token": "acc-tok",
        "refresh_token": "ref-tok",
    }

    # Legacy plaintext config.json migrates transparently on first load_config()
    legacy_payload = {
        "client_id": "legacy-cid",
        "user_login": "legacy_user",
        "access_token": "legacy-acc",
        "refresh_token": "legacy-ref",
        "client_secret": "legacy-sec",
    }
    paths.CONFIG_PATH.write_text(json.dumps(legacy_payload), encoding="utf-8")

    migrated = config.load_config()
    assert migrated == legacy_payload

    migrated_raw_text = paths.CONFIG_PATH.read_text(encoding="utf-8")
    migrated_raw = json.loads(migrated_raw_text)
    assert migrated_raw["client_id"] == "legacy-cid"
    assert migrated_raw["user_login"] == "legacy_user"
    for key, plain in (("access_token", "legacy-acc"), ("refresh_token", "legacy-ref"), ("client_secret", "legacy-sec")):
        assert migrated_raw[key].startswith(config.DPAPI_PREFIX)
        assert plain not in migrated_raw_text

    assert config.load_config() == legacy_payload


def test_keyring_storage_migration_and_headless_fallback(data_dir, monkeypatch):
    import os
    import sys
    from core import files

    monkeypatch.setattr(config.sys, "platform", "linux")

    class FakeKeyring:
        def __init__(self):
            self.store: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, key: str):
            return self.store.get((service, key))

        def set_password(self, service: str, key: str, val: str):
            self.store[(service, key)] = val

        def delete_password(self, service: str, key: str):
            self.store.pop((service, key), None)

    kr = FakeKeyring()
    monkeypatch.setattr(config, "keyring", kr)

    config.save_credentials("cid-kr", "sec-kr")
    config.save_login_tokens("acc-kr", "ref-kr", user_login="lucky_kr")

    assert kr.store == {
        (config.KEYRING_SERVICE, "client_secret"): "sec-kr",
        (config.KEYRING_SERVICE, "access_token"): "acc-kr",
        (config.KEYRING_SERVICE, "refresh_token"): "ref-kr",
    }
    raw_disk = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw_disk == {"client_id": "cid-kr", "user_login": "lucky_kr", "_keyring": True}
    assert config.load_config() == {
        "client_id": "cid-kr",
        "user_login": "lucky_kr",
        "client_secret": "sec-kr",
        "access_token": "acc-kr",
        "refresh_token": "ref-kr",
    }

    # Legacy plaintext migration into keyring on first load_config()
    kr.store.clear()
    legacy = {
        "client_id": "leg-cid",
        "user_login": "leg-user",
        "access_token": "leg-acc",
        "refresh_token": "leg-ref",
        "client_secret": "leg-sec",
    }
    paths.CONFIG_PATH.write_text(json.dumps(legacy), encoding="utf-8")
    assert config.load_config() == legacy
    assert kr.store == {
        (config.KEYRING_SERVICE, "access_token"): "leg-acc",
        (config.KEYRING_SERVICE, "refresh_token"): "leg-ref",
        (config.KEYRING_SERVICE, "client_secret"): "leg-sec",
    }
    migrated_disk = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
    assert migrated_disk == {"client_id": "leg-cid", "user_login": "leg-user", "_keyring": True}

    # Headless fallback to 0o600 JSON when keyring errors out
    class BrokenKeyring:
        def get_password(self, service: str, key: str):
            raise RuntimeError("No keyring backend available")

        def set_password(self, service: str, key: str, val: str):
            raise RuntimeError("No keyring backend available")

        def delete_password(self, service: str, key: str):
            raise RuntimeError("No keyring backend available")

    chmod_calls = []
    orig_atomic = files.atomic_write_json

    def spy_atomic(path, data, **kwargs):
        chmod_calls.append(kwargs.get("chmod_mode"))
        return orig_atomic(path, data, **kwargs)

    monkeypatch.setattr(config, "keyring", BrokenKeyring())
    monkeypatch.setattr(files, "atomic_write_json", spy_atomic)

    config.write_config({"client_id": "hl-cid", "client_secret": "hl-sec", "access_token": "hl-acc", "refresh_token": "hl-ref"})
    assert 0o600 in chmod_calls
    fallback_disk = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
    assert fallback_disk == {"client_id": "hl-cid", "client_secret": "hl-sec", "access_token": "hl-acc", "refresh_token": "hl-ref"}
    assert config.load_config() == fallback_disk
    if os.name == "posix":
        assert (paths.CONFIG_PATH.stat().st_mode & 0o777) == 0o600


def test_backup_corrupt_json_rotation_keeps_3_newest(tmp_path):
    import os
    from core.files import backup_corrupt_json

    target = tmp_path / "sample.json"
    created: list[Path] = []
    base_ts = 1_700_000_000.0
    for idx in range(5):
        target.write_text(f"bad-{idx}", encoding="utf-8")
        bak = backup_corrupt_json(target, max_backups=3)
        assert bak is not None
        assert re.match(r"^sample\.json\.corrupt\.\d{8}-\d{6}(?:_\d+)?$", bak.name)
        mtime = base_ts + idx * 10.0
        os.utime(bak, (mtime, mtime))
        created.append(bak)

    # Trigger one more rotation after setting distinct mtimes so newest-3 pruning is deterministic
    target.write_text("bad-5", encoding="utf-8")
    newest = backup_corrupt_json(target, max_backups=3)
    assert newest is not None
    os.utime(newest, (base_ts + 50.0, base_ts + 50.0))

    remaining = sorted(tmp_path.glob("sample.json.corrupt*"), key=lambda p: p.stat().st_mtime)
    assert len(remaining) == 3
    assert [p.read_text(encoding="utf-8") for p in remaining] == ["bad-3", "bad-4", "bad-5"]


def test_concurrent_4_thread_history_record_download_preserves_all_entries(tmp_path):
    import threading
    from core import history

    target = tmp_path / "luckytwitch_history.json"
    barrier = threading.Barrier(4, timeout=5.0)
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            barrier.wait()
            for j in range(10):
                history.record_download(
                    {
                        "vod_id": f"vod-{tid}-{j}",
                        "title": f"Stream {tid}-{j}",
                        "folder": str(tmp_path / f"f-{tid}"),
                    },
                    path=target,
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10.0)

    assert not errors
    entries = history.load_history(path=target)
    assert len(entries) == 40
    assert {e.vod_id for e in entries} == {f"vod-{t}-{j}" for t in range(4) for j in range(10)}


def test_json_store_schema_migrations_and_update(tmp_path):
    from core.files import JsonStore

    # 1. Bare list -> version 2 dict migration
    list_file = tmp_path / "list_migrated.json"
    list_file.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    list_store: JsonStore[dict] = JsonStore(
        list_file,
        lambda: {"items": [], "step": 0},
        expected_type=dict,
        schema_version=2,
        migrations={
            0: lambda items: {"items": list(items), "step": 1},
            1: lambda d: {**d, "step": 2},
        },
    )
    loaded = list_store.load()
    assert loaded == {"items": ["a", "b"], "step": 2}
    disk = json.loads(list_file.read_text(encoding="utf-8"))
    assert disk == {"schema_version": 2, "items": ["a", "b"], "step": 2}

    # 2. Unversioned dict -> version 2 migration + atomic update(fn)
    dict_file = tmp_path / "dict_migrated.json"
    dict_file.write_text(json.dumps({"count": 5}), encoding="utf-8")
    dict_store: JsonStore[dict] = JsonStore(
        dict_file,
        lambda: {"count": 0, "migrated": True},
        expected_type=dict,
        schema_version=2,
        migrations={1: lambda d: {"count": d["count"] * 10, "migrated": True}},
    )
    assert dict_store.load() == {"count": 50, "migrated": True}
    updated = dict_store.update(lambda d: {**d, "count": d["count"] + 7})
    assert updated == {"count": 57, "migrated": True}
    assert json.loads(dict_file.read_text(encoding="utf-8")) == {"schema_version": 2, "count": 57, "migrated": True}

    # 3. Versioned v1 envelope -> v2 migration
    v1_file = tmp_path / "v1_env.json"
    v1_file.write_text(json.dumps({"schema_version": 1, "count": 3}), encoding="utf-8")
    assert dict_store.load(path=v1_file) == {"count": 30, "migrated": True}
    assert json.loads(v1_file.read_text(encoding="utf-8"))["schema_version"] == 2

    # 4. TwitchClient repr hides secrets
    from core.twitch_api import TwitchClient
    client = TwitchClient("pub_cid", "top_secret", access_token="acc_secret", refresh_token="ref_secret")
    rep = repr(client)
    assert "pub_cid" in rep
    assert "top_secret" not in rep
    assert "acc_secret" not in rep
    assert "ref_secret" not in rep
