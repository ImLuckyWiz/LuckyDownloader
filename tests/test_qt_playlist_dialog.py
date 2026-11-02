from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from core.playlist import expand_playlist_jobs
from core.source_info import PlaylistInfo, PlaylistItem, parse_playlist_info
from qt_ui.playlist_dialog import CONFIRM_THRESHOLD, PlaylistPickerDialog

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_playlist():
    fixture_path = FIXTURES_DIR / "playlist_sample.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return parse_playlist_info(data, "https://www.youtube.com/playlist?list=PLBCF2DAC6FFB574DE")


def test_dialog_init_and_table_population(qtbot, sample_playlist):
    dlg = PlaylistPickerDialog(sample_playlist)
    qtbot.addWidget(dlg)
    dlg.show()

    assert dlg.table.rowCount() == 5
    assert len(dlg._checkboxes) == 5
    assert all(cb.isChecked() for cb in dlg._checkboxes)
    assert "5 of 5" in dlg.sel_count_lbl.text()
    assert dlg.btn_queue.isEnabled()


def test_dialog_select_all_none(qtbot, sample_playlist):
    dlg = PlaylistPickerDialog(sample_playlist)
    qtbot.addWidget(dlg)
    dlg.show()

    # None
    dlg.select_none()
    assert not any(cb.isChecked() for cb in dlg._checkboxes)
    assert len(dlg.selected_items()) == 0
    assert not dlg.btn_queue.isEnabled()
    assert "0 of 5" in dlg.sel_count_lbl.text()

    # All
    dlg.select_all()
    assert all(cb.isChecked() for cb in dlg._checkboxes)
    assert len(dlg.selected_items()) == 5
    assert dlg.btn_queue.isEnabled()
    assert "5 of 5" in dlg.sel_count_lbl.text()


def test_dialog_apply_range(qtbot, sample_playlist):
    dlg = PlaylistPickerDialog(sample_playlist)
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.range_entry.setText("1-2, 4")
    dlg.apply_range()

    selected = dlg.selected_items()
    assert len(selected) == 3
    assert [item.index for item in selected] == [1, 2, 4]
    assert "3 of 5" in dlg.sel_count_lbl.text()


def test_dialog_options_and_build_jobs(qtbot, sample_playlist, tmp_path):
    out_dir = str(tmp_path / "custom_downloads")
    dlg = PlaylistPickerDialog(sample_playlist, settings={"out_dir": out_dir})
    qtbot.addWidget(dlg)
    dlg.show()

    # Select only items 1 and 3
    dlg.range_entry.setText("1, 3")
    dlg.apply_range()

    # Adjust options
    dlg.container_combo.setCurrentText("mkv")
    idx_720 = dlg.quality_combo.findData("720p")
    if idx_720 >= 0:
        dlg.quality_combo.setCurrentIndex(idx_720)
    dlg.folder_entry.setText(out_dir)
    dlg.skip_existing_check.setChecked(True)

    jobs = dlg.build_jobs()
    assert len(jobs) == 2
    assert jobs[0].source.id == "GvgqDSnpRQM"
    assert jobs[0].opts.container == "mkv"
    assert jobs[0].opts.quality == "720p"
    assert jobs[0].opts.out_dir == out_dir
    assert jobs[0].opts.download_archive != ""


def test_dialog_audio_only_toggle(qtbot, sample_playlist):
    dlg = PlaylistPickerDialog(sample_playlist)
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.container_combo.setCurrentText("mp4")
    dlg.audio_toggle.setChecked(True)
    dlg._on_audio_toggled()

    assert dlg.current_quality() == "audio"
    assert dlg.current_container() == "mp3"


def test_dialog_large_playlist_confirm(qtbot, monkeypatch):
    # Create playlist with 60 dummy items
    items = [
        PlaylistItem(id=f"id_{i}", title=f"Title {i}", url=f"https://yt.com/{i}", index=i)
        for i in range(1, 61)
    ]
    pl = PlaylistInfo(id="PL_big", title="Big Playlist", url="https://yt.com/pl", entries=items)

    dlg = PlaylistPickerDialog(pl)
    qtbot.addWidget(dlg)
    dlg.show()

    # When user cancels confirmation dialog
    monkeypatch.setattr("qt_ui.dialogs.ask_yes_no", lambda parent, title, msg: False)
    dlg._on_accept()
    assert dlg.result() == 0  # Not accepted

    # When user accepts confirmation dialog
    monkeypatch.setattr("qt_ui.dialogs.ask_yes_no", lambda parent, title, msg: True)
    dlg._on_accept()
    assert dlg.result() == 1  # Accepted


def test_main_window_playlist_enqueue_flow(qtbot, monkeypatch, tmp_path, sample_playlist):
    import core.paths as paths
    monkeypatch.setattr(paths, "HISTORY_PATH", tmp_path / "history.json")

    from qt_ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()

    # Mock dialog execution to automatically accept and return 2 jobs
    def fake_handle(pl):
        jobs = expand_playlist_jobs(pl, pl.entries[:2], win.build_options())
        for job in jobs:
            label = f"{job.source.uploader or job.source.site} · {job.source.title}"[:70]
            win.tab_queue.enqueue(job, label, 1, "full video")
        win._sync_queue_badge()

    monkeypatch.setattr(win, "_handle_playlist_loaded", fake_handle)

    # When info arrives with PlaylistInfo
    win.on_info_ok(sample_playlist, clips=[], loaded=False, warn="")

    assert len(win.tab_queue.items) == 2
    assert win.tab_queue.items[0].job.source.id == sample_playlist.entries[0].id
    assert win.tab_queue.items[1].job.source.id == sample_playlist.entries[1].id


def test_info_runner_handles_playlist(qtbot, monkeypatch, sample_playlist):
    from qt_ui.background_jobs import InfoRunner
    from qt_ui.bridge import Bridge
    bridge = Bridge()
    runner = InfoRunner(bridge)

    monkeypatch.setattr("qt_ui.background_jobs.get_source_info", lambda url: sample_playlist)
    from core import source_info
    monkeypatch.setattr(source_info, "get_source_info", lambda url: sample_playlist)

    received_info = []
    received_error = []
    bridge.info_ok.connect(lambda info, clips, loaded, warn: received_info.append(info))
    bridge.error.connect(lambda err: received_error.append(err))

    runner.start("https://www.youtube.com/playlist?list=PLBCF2DAC6FFB574DE", client=MagicMock())
    qtbot.waitUntil(lambda: len(received_info) > 0 or len(received_error) > 0, timeout=3000)

    assert len(received_error) == 0
    assert len(received_info) == 1
    assert received_info[0].id == sample_playlist.id


def test_dialog_thumbnail_column_and_loader(qtbot, sample_playlist, tmp_path):
    from PySide6.QtGui import QPixmap
    dlg = PlaylistPickerDialog(sample_playlist)
    qtbot.addWidget(dlg)
    dlg.show()

    assert dlg.table.columnCount() == 6
    assert 0 in dlg._thumb_labels

    # Create dummy image and trigger thumb loaded
    test_img = tmp_path / "thumb_test.png"
    pm = QPixmap(10, 10)
    pm.fill(Qt.GlobalColor.blue)
    pm.save(str(test_img))

    dlg._on_thumb_loaded(0, str(test_img))
    lbl = dlg._thumb_labels[0]
    assert lbl.pixmap() is not None
    assert not lbl.pixmap().isNull()


def test_dialog_cookies_toggle(qtbot, sample_playlist):
    # Case 1: no browser configured
    dlg_none = PlaylistPickerDialog(sample_playlist, settings={"cookies_from_browser": "None"})
    qtbot.addWidget(dlg_none)
    assert dlg_none.is_cookies_enabled() is False
    assert dlg_none.cookies_check.isHidden()

    # Case 2: firefox configured with YouTube URL -> enabled by default
    sample_playlist.url = "https://www.youtube.com/playlist?list=PL123"
    dlg_yt = PlaylistPickerDialog(sample_playlist, settings={"cookies_from_browser": "firefox"})
    qtbot.addWidget(dlg_yt)
    assert not dlg_yt.cookies_check.isHidden()
    assert dlg_yt.is_cookies_enabled() is True
    jobs = dlg_yt.build_jobs()
    assert jobs[0].opts.cookies_browser == "firefox"

    # User manually unchecks the cookies checkbox
    dlg_yt.cookies_check.setChecked(False)
    assert dlg_yt.is_cookies_enabled() is False
    jobs_unchecked = dlg_yt.build_jobs()
    assert jobs_unchecked[0].opts.cookies_browser == ""

    # Case 3: firefox configured with external / untrusted URL -> unchecked by default
    sample_playlist.url = "https://www.pornhub.com/playlist/123"
    dlg_ph = PlaylistPickerDialog(sample_playlist, settings={"cookies_from_browser": "firefox"})
    qtbot.addWidget(dlg_ph)
    assert not dlg_ph.cookies_check.isHidden()
    assert dlg_ph.is_cookies_enabled() is False
    jobs_ph = dlg_ph.build_jobs()
    assert jobs_ph[0].opts.cookies_browser == ""
