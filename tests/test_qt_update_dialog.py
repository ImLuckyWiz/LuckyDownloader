"""Tests for qt_ui.update_dialog: UpdateDialog presentation, notes stripping, and actions."""

from unittest.mock import MagicMock

import pytest

from core import paths, updates
from qt_ui.update_dialog import UpdateDialog, clean_release_notes


def test_clean_release_notes():
    raw = (
        "<h1>Release v2.3.0</h1>\n"
        "<p>Some <b>bold</b> text.</p>\n"
        "![Banner](https://example.com/banner.png)\n"
        "- Stream quality selector\n"
        "- Audio-only extraction\n"
    )
    cleaned = clean_release_notes(raw)
    assert "<h1>" not in cleaned
    assert "<b>" not in cleaned
    assert "![Banner]" not in cleaned
    assert "Stream quality selector" in cleaned
    assert "Audio-only extraction" in cleaned


def test_clean_release_notes_capped():
    long_text = "A" * 3000
    cleaned = clean_release_notes(long_text, max_chars=100)
    assert len(cleaned) < 200
    assert "… (Read the full notes on GitHub)" in cleaned


def test_clean_release_notes_empty():
    assert clean_release_notes("") == "No release notes provided."


def test_update_dialog_init_and_widgets(qtbot, monkeypatch):
    monkeypatch.setattr(paths, "BUNDLED_VERSION", "v2.1.1")
    info = updates.UpdateInfo(
        tag="v2.3.0",
        notes="* Feature 1\n* Feature 2",
        page_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/v2.3.0",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
    )
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)

    assert "v2.3.0" in dlg.windowTitle() or "Update available" in dlg.windowTitle()
    assert dlg.btn_update.text() == "Update now"
    assert dlg.btn_release_page.text() == "Release page"
    assert dlg.btn_later.text() == "Later"
    assert dlg.btn_skip.text() == "Skip v2.3.0"


def test_update_dialog_skip_action(qtbot, tmp_path, monkeypatch):
    state_file = tmp_path / "luckytwitch_update.json"
    monkeypatch.setattr(paths, "UPDATE_STATE_PATH", state_file)
    host = MagicMock()

    info = updates.UpdateInfo(tag="v2.3.0", page_url="http://page")
    dlg = UpdateDialog(info, host=host)
    qtbot.addWidget(dlg)

    dlg.btn_skip.click()
    host.on_update_skipped.assert_called_once_with("v2.3.0")

    state = updates.load_state()
    assert state.get("skipped_tag") == "v2.3.0"


def test_update_dialog_release_page_and_update_now_open_urls(qtbot, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    opened_urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened_urls.append(url.toString()))

    info = updates.UpdateInfo(
        tag="v2.3.0",
        page_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/tag/v2.3.0",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
    )
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)

    dlg.btn_release_page.click()
    assert opened_urls[-1] == info.page_url

    dlg.btn_update.click()
    assert opened_urls[-1] == info.asset_url


def test_update_dialog_installed_setup_busy_blocked(qtbot, monkeypatch):
    monkeypatch.setattr(updates, "is_installed_setup", lambda: True)
    host = MagicMock()
    host.tab_queue.runner.is_running.return_value = True

    from qt_ui import dialogs
    dialog_calls = []
    monkeypatch.setattr(dialogs, "info", lambda parent, title, text: dialog_calls.append((title, text)))

    info = updates.UpdateInfo(
        tag="v2.3.0",
        asset_name="LuckyTwitch-Setup.exe",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
    )
    dlg = UpdateDialog(info, host=host)
    qtbot.addWidget(dlg)

    dlg.on_update_now()
    assert len(dialog_calls) == 1
    assert dialog_calls[0][0] == "Busy"
    assert dlg.progress_container.isHidden()


def test_update_dialog_download_and_install_flow(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "is_installed_setup", lambda: True)
    state_file = tmp_path / "update_state.json"
    monkeypatch.setattr(paths, "UPDATE_STATE_PATH", state_file)

    host = MagicMock()
    host.tab_queue.runner.is_running.return_value = False
    host.tools_busy = False
    host.saved_chat_busy = False

    info = updates.UpdateInfo(
        tag="v2.3.0",
        asset_name="LuckyTwitch-Setup.exe",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
    )
    dlg = UpdateDialog(info, host=host)
    qtbot.addWidget(dlg)

    # Mock runner
    fake_ctx = MagicMock()
    monkeypatch.setattr("qt_ui.background_jobs.UpdateDownloadRunner.start", lambda self, inf, dest: fake_ctx)

    dlg.on_update_now()
    assert not dlg.progress_container.isHidden()
    assert dlg.btn_later.text() == "Cancel"
    assert not dlg.btn_update.isEnabled()

    # Progress update
    dlg._on_download_progress(0.42, "Downloading 42%")
    assert dlg.progress_bar.value() == 42
    assert "42%" in dlg.progress_label.text()

    # Confirm dialog and installer launch
    from qt_ui import dialogs
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda parent, title, text: True)
    launched = []
    monkeypatch.setattr(updates, "launch_installer", lambda path: launched.append(path) or True)

    fake_dest = str(tmp_path / "LuckyTwitch-Setup-v2.3.0.exe")
    dlg._on_download_done(fake_dest, "")

    assert len(launched) == 1
    assert launched[0] == fake_dest
    host.close.assert_called_once()
    saved = updates.load_state()
    assert saved.get("installer_path") == fake_dest


def test_update_dialog_download_error_handling(qtbot, monkeypatch):
    info = updates.UpdateInfo(
        tag="v2.3.0",
        asset_name="LuckyTwitch-Setup.exe",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
    )
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)

    dlg._on_download_done("", "The download did not pass the integrity check.")
    assert "integrity check" in dlg.progress_label.text()
    assert dlg.btn_update.text() == "Open release page"
    assert dlg.btn_later.text() == "Close"


def test_update_dialog_download_cancellation(qtbot, monkeypatch):
    info = updates.UpdateInfo(
        tag="v2.3.0",
        asset_name="LuckyTwitch-Setup.exe",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyTwitch-Setup.exe",
    )
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)

    fake_ctx = MagicMock()
    dlg._download_ctx = fake_ctx

    dlg.on_cancel_or_later()
    fake_ctx.cancel.assert_called_once()
    assert dlg._download_ctx is None
    assert "cancelled" in dlg.progress_label.text().lower()
    assert dlg.btn_later.text() == "Later"


def test_update_dialog_re_verifies_sha256_before_launch(qtbot, monkeypatch, tmp_path):
    import hashlib
    state_file = tmp_path / "update_state.json"
    monkeypatch.setattr(paths, "UPDATE_STATE_PATH", state_file)

    payload = b"valid installer binary"
    expected_hash = hashlib.sha256(payload).hexdigest()
    installer_path = tmp_path / "LuckyDownloader-Setup-v2.3.0.exe"
    installer_path.write_bytes(b"tampered installer binary")

    info = updates.UpdateInfo(
        tag="v2.3.0",
        asset_name="LuckyDownloader-Setup.exe",
        asset_url="https://github.com/ImLuckyWiz/LuckyTwitchDownloader/releases/download/v2.3.0/LuckyDownloader-Setup.exe",
        asset_size=len(payload),
        sha256=expected_hash,
    )
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)

    launched = []
    monkeypatch.setattr(updates, "launch_installer", lambda p: launched.append(p) or True)

    dlg._install_and_restart(str(installer_path))
    assert launched == []
    assert not installer_path.exists()
    assert "verification failed" in dlg.progress_label.text().lower()

