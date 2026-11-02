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
