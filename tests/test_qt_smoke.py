"""Smoke tests for Qt application initialization, logging, diagnostics, and AboutDialog."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import zipfile
import pytest

from PySide6.QtWidgets import QApplication

from core import paths
from core.diagnostics import export_diagnostics_zip, redact_settings, setup_file_logging
from qt_ui.dialogs import AboutDialog


@pytest.fixture(autouse=True)
def init_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_setup_file_logging(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    log_file = setup_file_logging()

    assert log_file == tmp_path / "logs" / "luckydownloader.log"
    assert log_file.parent.is_dir()

    logger = logging.getLogger("test_smoke")
    logger.info("Diagnostics smoke test entry")

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "Diagnostics smoke test entry" in content


def test_redact_settings():
    settings = {
        "out_dir": "C:/Downloads",
        "container": "mp4",
        "cookies_from_browser": "chrome",
        "twitch_token": "oauth:secret12345",
        "auth_key": "xyz_secret",
        "nested": {
            "api_key": "nested_secret",
            "normal": 42,
        },
    }
    redacted = redact_settings(settings)
    assert redacted["out_dir"] == "C:/Downloads"
    assert redacted["container"] == "mp4"
    assert redacted["cookies_from_browser"] == "[REDACTED]"
    assert redacted["twitch_token"] == "[REDACTED]"
    assert redacted["auth_key"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["normal"] == 42


def test_export_diagnostics_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "luckydownloader.log"
    log_file.write_text("2026-11-04 12:00:00 [INFO] test log", encoding="utf-8")

    out_zip = tmp_path / "bundle.zip"
    export_diagnostics_zip(out_zip)

    assert out_zip.is_file()
    with zipfile.ZipFile(out_zip, "r") as zf:
        names = zf.namelist()
        assert "system_info.json" in names
        assert "settings_redacted.json" in names
        assert "logs/luckydownloader.log" in names

        sys_info = json.loads(zf.read("system_info.json").decode("utf-8"))
        assert "python_version" in sys_info
        assert "platform" in sys_info
        assert "app_version" in sys_info

        settings = json.loads(zf.read("settings_redacted.json").decode("utf-8"))
        assert isinstance(settings, dict)


def test_about_dialog_ui_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    dlg = AboutDialog(parent=None)

    assert "About LuckyDownloader" in dlg.windowTitle()
    assert hasattr(dlg, "export_btn")
    assert hasattr(dlg, "close_btn")

    # Mock QFileDialog to return a dummy zip path
    dest_zip = tmp_path / "exported.zip"
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(dest_zip), "Zip archives (*.zip)"),
    )
    # Mock info dialog
    info_called = []
    monkeypatch.setattr("qt_ui.dialogs.info", lambda *args, **kwargs: info_called.append(True))

    dlg._on_export_diagnostics()

    assert dest_zip.is_file()
    assert len(info_called) == 1
    dlg.close()
