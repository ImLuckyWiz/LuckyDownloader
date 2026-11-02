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
    assert len(d) == 44
    assert sum(isinstance(v, bool) for v in d.values()) == 16
    assert sum(isinstance(v, str) for v in d.values()) == 28
    expected_bools = {
        "exact", "keep_full", "chapters", "sidecar", "premiere_xml",
        "premiere_plugin", "game_markers", "muted_markers", "chat",
        "chat_embed", "chat_render", "chat_render_smooth", "subfolders", "auto_update", "clean_title",
        "check_app_updates",
    }
    assert {k for k, v in d.items() if isinstance(v, bool)} == expected_bools
    for k, v in d.items():
        if k in expected_bools:
            assert isinstance(v, bool), f"{k} should be bool"
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
