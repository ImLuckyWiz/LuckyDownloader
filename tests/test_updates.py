"""Tests for core.updates: version parsing, ordering, asset picking, and update checks."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import paths, updates


# --------------------------------------------------------------------------- parse_version & is_valid
@pytest.mark.parametrize(
    "v_str, expected",
    [
        ("v2.1.1", (2, 1, 1, "")),
        ("v2.2.0", (2, 2, 0, "")),
        ("2.10.0", (2, 10, 0, "")),
        ("v0.8.0-beta.1", (0, 8, 0, "beta.1")),
        ("v2.0.0-alpha", (2, 0, 0, "alpha")),
        ("1.0", None),
        ("", None),
        (None, None),
        ("garbage", None),
        ("v1.2", None),
        ("v1.2.3.4", None),
    ],
)
def test_parse_version(v_str, expected):
    assert updates.parse_version(v_str) == expected


def test_is_valid_app_version():
    assert updates.is_valid_app_version("v2.1.1") is True
    assert updates.is_valid_app_version("v0.8.0-beta") is True
    assert updates.is_valid_app_version("1.0") is False
    assert updates.is_valid_app_version("") is False
    assert updates.is_valid_app_version(None) is False


# --------------------------------------------------------------------------- is_newer
@pytest.mark.parametrize(
    "remote, current, expected",
    [
        ("v2.2.0", "v2.1.1", True),
        ("v2.1.1", "v2.2.0", False),
        ("v2.10.0", "v2.9.0", True),
        ("v2.9.0", "v2.10.0", False),
        ("v2.1.1", "v2.1.1", False),
        # Stable builds ignore pre-releases
        ("v2.2.0-beta.1", "v2.1.1", False),
        ("v2.0.0-alpha", "v2.0.0", False),
        # Pre-release builds notice newer pre-releases or stable
        ("v2.0.0", "v2.0.0-beta.1", True),
        ("v2.0.0-beta.2", "v2.0.0-beta.1", True),
        ("v2.0.0-beta.1", "v2.0.0-beta.2", False),
        # Dev builds / invalid versions never trigger newer
        ("v2.2.0", "1.0", False),
        ("v2.2.0", "", False),
        ("v2.2.0", "dev", False),
        ("garbage", "v2.1.1", False),
        # Without leading 'v'
        ("2.2.0", "v2.1.1", True),
    ],
)
def test_is_newer(remote, current, expected):
    assert updates.is_newer(remote, current) is expected


# --------------------------------------------------------------------------- pick_asset
def test_pick_asset_windows():
    release = {
        "assets": [
            {"name": "LuckyTwitch-macos-arm64.dmg", "browser_download_url": "http://mac-arm"},
            {"name": "LuckyTwitch-Setup.exe", "browser_download_url": "http://win"},
            {"name": "other.zip", "browser_download_url": "http://other"},
        ]
    }
    asset = updates.pick_asset(release, sys_platform="win32", machine="AMD64")
    assert asset is not None
    assert asset["name"] == "LuckyTwitch-Setup.exe"


def test_pick_asset_macos_arm64():
    release = {
        "assets": [
            {"name": "LuckyTwitch-macos-x86_64.dmg", "browser_download_url": "http://x86"},
            {"name": "LuckyTwitch-macos-arm64.dmg", "browser_download_url": "http://arm"},
            {"name": "LuckyTwitch-Setup.exe", "browser_download_url": "http://win"},
        ]
    }
    asset = updates.pick_asset(release, sys_platform="darwin", machine="arm64")
    assert asset is not None
    assert asset["name"] == "LuckyTwitch-macos-arm64.dmg"


def test_pick_asset_macos_intel():
    release = {
        "assets": [
            {"name": "LuckyTwitch-macos-x86_64.dmg", "browser_download_url": "http://x86"},
            {"name": "LuckyTwitch-macos-arm64.dmg", "browser_download_url": "http://arm"},
        ]
    }
    asset = updates.pick_asset(release, sys_platform="darwin", machine="x86_64")
    assert asset is not None
    assert asset["name"] == "LuckyTwitch-macos-x86_64.dmg"


def test_pick_asset_linux():
    release = {
        "assets": [
            {"name": "LuckyTwitch-Setup.exe", "browser_download_url": "http://win"},
            {"name": "LuckyTwitch-macos-arm64.dmg", "browser_download_url": "http://mac"},
            {"name": "LuckyTwitch-x86_64.AppImage", "browser_download_url": "http://appimage"},
            {"name": "LuckyTwitch-linux-x86_64.tar.gz", "browser_download_url": "http://tar"},
        ]
    }
    asset = updates.pick_asset(release, sys_platform="linux", machine="x86_64")
    assert asset is not None
    assert asset["name"] == "LuckyTwitch-x86_64.AppImage"

    release_tar = {
        "assets": [
            {"name": "LuckyTwitch-linux-x86_64.tar.gz", "browser_download_url": "http://tar"},
        ]
    }
    asset_tar = updates.pick_asset(release_tar, sys_platform="linux", machine="x86_64")
    assert asset_tar is not None
    assert asset_tar["name"] == "LuckyTwitch-linux-x86_64.tar.gz"


def test_pick_asset_windows_luckydownloader():
    release = {
        "assets": [
            {"name": "LuckyDownloader-macos-arm64.dmg", "browser_download_url": "http://mac-arm"},
            {"name": "LuckyDownloader-Setup.exe", "browser_download_url": "http://win"},
            {"name": "other.zip", "browser_download_url": "http://other"},
        ]
    }
    asset = updates.pick_asset(release, sys_platform="win32", machine="AMD64")
    assert asset is not None
    assert asset["name"] == "LuckyDownloader-Setup.exe"


def test_pick_asset_macos_luckydownloader():
    release = {
        "assets": [
            {"name": "LuckyDownloader-macos-x86_64.dmg", "browser_download_url": "http://x86"},
            {"name": "LuckyDownloader-macos-arm64.dmg", "browser_download_url": "http://arm"},
        ]
    }
    asset_arm = updates.pick_asset(release, sys_platform="darwin", machine="arm64")
    assert asset_arm is not None
    assert asset_arm["name"] == "LuckyDownloader-macos-arm64.dmg"

    asset_intel = updates.pick_asset(release, sys_platform="darwin", machine="x86_64")
    assert asset_intel is not None
    assert asset_intel["name"] == "LuckyDownloader-macos-x86_64.dmg"


def test_pick_asset_linux_luckydownloader():
    release = {
        "assets": [
            {"name": "LuckyDownloader-Setup.exe", "browser_download_url": "http://win"},
            {"name": "LuckyDownloader-x86_64.AppImage", "browser_download_url": "http://appimage"},
            {"name": "LuckyDownloader-linux-x86_64.tar.gz", "browser_download_url": "http://tar"},
        ]
    }
    asset = updates.pick_asset(release, sys_platform="linux", machine="x86_64")
    assert asset is not None
    assert asset["name"] == "LuckyDownloader-x86_64.AppImage"

    release_tar = {
        "assets": [
            {"name": "LuckyDownloader-linux-x86_64.tar.gz", "browser_download_url": "http://tar"},
        ]
    }
    asset_tar = updates.pick_asset(release_tar, sys_platform="linux", machine="x86_64")
    assert asset_tar is not None
    assert asset_tar["name"] == "LuckyDownloader-linux-x86_64.tar.gz"


def test_pick_asset_none_matching():
    release = {"assets": [{"name": "random.txt"}]}
    assert updates.pick_asset(release, sys_platform="win32") is None


# --------------------------------------------------------------------------- is_safe_asset_url
def test_is_safe_asset_url():
    valid_old = "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.2.0/LuckyTwitch-Setup.exe"
    valid_new = "https://github.com/ImLuckyWiz/LuckyDownloader/releases/download/v2.12.0/LuckyDownloader-Setup.exe"
    assert updates.is_safe_asset_url(valid_old) is True
    assert updates.is_safe_asset_url(valid_new) is True
    assert updates.is_safe_asset_url("http://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.2.0/x.exe") is False
    assert updates.is_safe_asset_url("http://github.com/ImLuckyWiz/LuckyDownloader/releases/download/v2.12.0/x.exe") is False
    assert updates.is_safe_asset_url("https://malicious.com/LuckyTwitch-Setup.exe") is False
    assert updates.is_safe_asset_url("https://malicious.com/LuckyDownloader-Setup.exe") is False
    assert updates.is_safe_asset_url("") is False


# --------------------------------------------------------------------------- verify_download & extract_sha256
def test_verify_download(tmp_path):
    test_file = tmp_path / "installer.exe"
    data = b"LuckyTwitch installer payload binary"
    test_file.write_bytes(data)
    expected_hash = hashlib.sha256(data).hexdigest()

    assert updates.verify_download(test_file, len(data), expected_hash) is True
    assert updates.verify_download(test_file, len(data), expected_hash.upper()) is True
    # Wrong size
    assert updates.verify_download(test_file, len(data) + 1, expected_hash) is False
    # Wrong hash
    assert updates.verify_download(test_file, len(data), "0" * 64) is False
    # Empty hash (must fail per security requirements)
    assert updates.verify_download(test_file, len(data), "") is False
    # Non-existent file
    assert updates.verify_download(tmp_path / "nope.exe", len(data), expected_hash) is False


def test_extract_sha256_from_sums():
    sums_text = (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  LuckyTwitch-Setup.exe\n"
        "ca978112ca1bbdcafac231b39a23dc4da7860819c196611e80e10ab6f442d221 *LuckyTwitch-macos-arm64.dmg\n"
    )
    assert updates.extract_sha256_from_sums(sums_text, "LuckyTwitch-Setup.exe") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert updates.extract_sha256_from_sums(sums_text, "LuckyTwitch-macos-arm64.dmg") == "ca978112ca1bbdcafac231b39a23dc4da7860819c196611e80e10ab6f442d221"
    assert updates.extract_sha256_from_sums(sums_text, "nonexistent.exe") == ""


# --------------------------------------------------------------------------- should_check & throttle
def test_should_check_no_prior_check():
    assert updates.should_check({}) is True
    assert updates.should_check({"last_check": ""}) is True


def test_should_check_throttled_within_24h():
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()
    assert updates.should_check({"last_check": recent}, now=now) is False


def test_should_check_allowed_after_24h():
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    old = (now - timedelta(hours=25)).isoformat()
    assert updates.should_check({"last_check": old}, now=now) is True


def test_should_check_clock_turned_backwards():
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    future = (now + timedelta(days=2)).isoformat()
    assert updates.should_check({"last_check": future}, now=now) is True


# --------------------------------------------------------------------------- state load/save
def test_state_load_and_save(tmp_path, monkeypatch):
    state_file = tmp_path / "luckytwitch_update.json"
    monkeypatch.setattr(paths, "UPDATE_STATE_PATH", state_file)

    initial = updates.load_state()
    assert initial["last_check"] == ""
    assert initial["latest_tag"] == ""

    saved = {
        "last_check": "2026-10-27T12:00:00Z",
        "latest_tag": "v2.3.0",
        "notified_tag": "v2.3.0",
        "skipped_tag": "",
        "cached": {"tag": "v2.3.0"},
        "installer_path": "",
    }
    updates.save_state(saved)
    loaded = updates.load_state()
    assert loaded == saved


# --------------------------------------------------------------------------- fetch_latest
def test_fetch_latest_success_with_api():
    session = MagicMock()
    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json.return_value = {
        "tag_name": "v2.3.0",
        "body": "## What's new\n- Amazing feature",
        "html_url": "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/v2.3.0",
        "assets": [
            {
                "name": "LuckyTwitch-Setup.exe",
                "browser_download_url": "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
                "size": 50000000,
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/SHA256SUMS.txt",
            },
        ],
    }

    sums_resp = MagicMock()
    sums_resp.status_code = 200
    sums_resp.text = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef  LuckyTwitch-Setup.exe\n"

    session.get.side_effect = [api_resp, sums_resp]

    info = updates.fetch_latest(session=session, sys_platform="win32", machine="AMD64")
    assert info is not None
    assert info.tag == "v2.3.0"
    assert info.asset_name == "LuckyTwitch-Setup.exe"
    assert info.asset_size == 50000000
    assert info.sha256 == "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"


def test_fetch_latest_redirect_fallback_on_rate_limit():
    session = MagicMock()
    # API 403 Forbidden
    api_resp = MagicMock()
    api_resp.status_code = 403
    # Web redirect to /tag/v2.3.0
    web_resp = MagicMock()
    web_resp.status_code = 302
    web_resp.headers = {"Location": "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/v2.3.0"}

    session.get.side_effect = [api_resp, web_resp]

    info = updates.fetch_latest(session=session)
    assert info is not None
    assert info.tag == "v2.3.0"
    assert info.page_url == "https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/v2.3.0"
    assert info.asset_name == ""


def test_fetch_latest_failure_silent():
    session = MagicMock()
    session.get.side_effect = Exception("Network offline")
    info = updates.fetch_latest(session=session)
    assert info is None


def test_is_installed_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    fake_exe = tmp_path / "LuckyTwitch.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(updates.sys, "executable", str(fake_exe))

    # Without unins000.exe
    assert not updates.is_installed_setup()

    # With unins000.exe
    unins = tmp_path / "unins000.exe"
    unins.write_text("")
    assert updates.is_installed_setup()

    # Non-win32
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    assert not updates.is_installed_setup()


def test_get_update_temp_dir():
    d = updates.get_update_temp_dir()
    assert d.exists()
    assert d.is_dir()
    assert "LuckyTwitch-update" in str(d)


def test_cleanup_stale_installer(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(updates.paths, "UPDATE_STATE_PATH", state_file)

    update_dir = tmp_path / "LuckyTwitch-update"
    update_dir.mkdir()
    installer_file = update_dir / "LuckyTwitch-Setup-v2.3.0.exe"
    installer_file.write_text("dummy")

    state = {"installer_path": str(installer_file)}
    updates.save_state(state)

    assert installer_file.is_file()
    updates.cleanup_stale_installer()

    assert not installer_file.exists()
    assert not update_dir.exists()
    saved = updates.load_state()
    assert saved.get("installer_path") == ""


def test_launch_installer(monkeypatch):
    calls = []

    def fake_popen(cmd, creationflags=0, close_fds=False):
        calls.append((cmd, creationflags, close_fds))
        return MagicMock()

    monkeypatch.setattr(updates.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updates.sys, "platform", "win32")

    ok = updates.launch_installer("C:\\temp\\LuckyTwitch-Setup.exe")
    assert ok is True
    assert len(calls) == 1
    cmd, flags, _ = calls[0]
    assert cmd[0] == "C:\\temp\\LuckyTwitch-Setup.exe"
    assert "/SILENT" in cmd
    assert "/SUPPRESSMSGBOXES" in cmd
    assert "/NORESTART" in cmd
    assert "/CLOSEAPPLICATIONS" in cmd
    assert "/RELAUNCH=1" in cmd

    # Failure case (e.g. OSError)
    def fail_popen(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(updates.subprocess, "Popen", fail_popen)
    assert updates.launch_installer("bad_path") is False
