from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget

from core.options import JobOptions
from core.providers import Capability, GenericProvider
from core.source_info import SourceInfo, VideoFormat
from qt_ui.tabs.plan import PlanTab


def _make_sample_source(site: str = "youtube", duration: float = 300.0) -> SourceInfo:
    prov = GenericProvider(site)
    formats = [
        VideoFormat(format_id="1080p", height=1080, fps=60, container="mp4"),
        VideoFormat(format_id="720p", height=720, fps=30, container="mp4"),
        VideoFormat(format_id="audio", height=0, fps=0, container="m4a", audio_only=True),
    ]
    return SourceInfo(
        url="https://www.youtube.com/watch?v=sample123",
        id="sample_vid_123",
        title="Sample Video Title",
        uploader="Content Creator",
        duration=duration,
        date="2026-11-02",
        site=site,
        provider=prov,
        formats=formats,
    )


def test_plan_tab_mode_switching(qtbot):
    tab = PlanTab()
    qtbot.addWidget(tab)
    tab.show()

    # Initial state is Timeline mode (Twitch)
    assert tab.mode_timeline is True
    assert tab.timeline_card.isVisible()
    assert tab.cuts_card.isVisible()
    assert tab.clips_card.isVisible()
    assert not tab.generic_card.isVisible()

    # Switch to Generic / Card mode
    tab.set_mode(False)
    assert tab.mode_timeline is False
    assert not tab.timeline_card.isVisible()
    assert not tab.cuts_card.isVisible()
    assert not tab.clips_card.isVisible()
    assert tab.generic_card.isVisible()
    assert not tab.onboarding_card.isVisible()

    # Switch back to Timeline mode
    tab.set_mode(True)
    assert tab.mode_timeline is True
    assert tab.timeline_card.isVisible()
    assert tab.cuts_card.isVisible()
    assert tab.clips_card.isVisible()
    assert not tab.generic_card.isVisible()


def test_generic_card_controls_and_options(qtbot, tmp_path):
    tab = PlanTab()
    qtbot.addWidget(tab)
    src = _make_sample_source("youtube", 185.0)
    tab.source = src

    tab.set_mode(False)
    tab.set_formats(src.formats, "best")
    tab.set_title(src.title)
    tab.update_generic_card(src)

    # Title & Reset
    assert tab.card_title() == "Sample Video Title"
    assert tab.generic_title_entry.text() == "Sample Video Title"
    tab.generic_title_entry.setText("Edited Title")
    assert tab.card_title() == "Edited Title"
    assert src.title == "Edited Title"

    tab.generic_reset_title_btn.click()
    assert tab.card_title() == "Sample Video Title"

    # Metadata labels
    assert "Content Creator" in tab.generic_uploader_lbl.text()
    assert "3:05" in tab.generic_duration_lbl.text()
    assert "2026-11-02" in tab.generic_date_lbl.text()

    # Formats & Quality
    assert tab.generic_quality_combo.count() == 4  # Best available + 3 formats
    assert tab.current_quality() == "best"

    # Select specific quality in generic combo
    tab.generic_quality_combo.setCurrentIndex(1)
    tab._on_generic_quality_activated(1)
    assert tab.current_quality() == "1080p"

    # Container & Audio toggle
    assert tab.current_container() == "mp4"
    assert not tab.is_audio_only()

    # Toggle audio on -> switches to mp3
    tab.generic_audio_toggle.setChecked(True)
    tab.generic_audio_toggle.clicked.emit()
    assert tab.is_audio_only()
    assert tab.current_container() == "mp3"

    # Toggle audio off -> switches to mp4
    tab.generic_audio_toggle.setChecked(False)
    tab.generic_audio_toggle.clicked.emit()
    assert not tab.is_audio_only()
    assert tab.current_container() == "mp4"

    # Folder entry
    tab.generic_folder_entry.setText(str(tmp_path))
    assert tab.current_output_dir() == str(tmp_path)

    # Preview update in Card Mode
    tab.update_preview()
    assert "Full video download" in tab.preview_text()
    assert "3:05" in tab.preview_text()
    assert "1 video" in tab.plan_summary_lbl.text()


def test_main_window_generic_flow(qtbot, monkeypatch, tmp_path):
    import core.paths as paths
    monkeypatch.setattr(paths, "HISTORY_PATH", tmp_path / "history.json")

    from qt_ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()

    src = _make_sample_source("tiktok", 45.0)

    # Simulate info arrival
    win.on_info_ok(src, clips=[], loaded=False, warn="")

    assert win.tab_plan.mode_timeline is False
    assert win.tab_plan.generic_card.isVisible()
    assert not win.tab_plan.timeline_card.isVisible()
    assert win.vod_strip.isVisible()
    assert "TIKT" in win.vod_strip.thumb_label.text() or win.vod_strip.thumb_label.pixmap() is not None

    # Enqueue generic job
    win.tab_plan.generic_folder_entry.setText(str(tmp_path / "downloads"))
    win.tab_plan.generic_container_combo.setCurrentText("mkv")
    win.tab_plan.generic_quality_combo.setCurrentIndex(1)
    win.tab_plan._on_generic_quality_activated(1)

    win.add_to_queue(start=False)

    assert len(win.tab_queue.items) == 1
    item = win.tab_queue.items[0]
    assert item.parts == 1
    assert item.strategy == "full video"
    assert item.job.opts.container == "mkv"
    assert item.job.opts.quality == "1080p"
    assert item.job.opts.strategy == "full"
    assert item.job.source.site == "tiktok"

    # Clear VOD restores Timeline mode
    win.clear_vod()
    assert win.source is None
    assert win.tab_plan.mode_timeline is True
    assert not win.vod_strip.isVisible()


def test_main_window_topbar_input_routing(qtbot, monkeypatch):
    from qt_ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()

    # 1. Twitch streamer name -> routes to Search tab
    win.vod_entry.setText("shroud")
    win.on_get_info()
    assert win.tabs.currentWidget() == win.tab_search
    assert win.tab_search.search_edit.text() == "shroud"

    # 2. Invalid input -> shows warning, does not run info_runner
    runner_mock = MagicMock()
    monkeypatch.setattr(win.info_runner, "start", runner_mock)

    warn_mock = MagicMock()
    from qt_ui import dialogs
    monkeypatch.setattr(dialogs, "warning", warn_mock)

    win.vod_entry.setText("not-a-valid-url-or-id")
    win.on_get_info()
    assert warn_mock.called
    assert not runner_mock.called

    # 3. Valid generic URL -> starts info_runner
    warn_mock.reset_mock()
    win.vod_entry.setText("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    win.on_get_info()
    assert runner_mock.called
    assert runner_mock.call_args[0][0] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extractor_error_prompts_update_and_retries(qtbot, monkeypatch):
    from qt_ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()

    update_called = []
    monkeypatch.setattr(win, "update_tools_now", lambda: update_called.append(True))

    from qt_ui import dialogs
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda parent, title, text: True)

    win.vod_entry.setText("https://www.youtube.com/watch?v=changed123")
    err_msg = "Extractor error: the video site layout may have changed. Try updating yt-dlp in Options > Tools."
    win.on_info_error(err_msg)

    assert update_called == [True]
    assert win._pending_retry_url == "https://www.youtube.com/watch?v=changed123"

    runner_mock = MagicMock()
    monkeypatch.setattr(win.info_runner, "start", runner_mock)

    win.on_tools_done("")
    assert win._pending_retry_url is None
    assert runner_mock.called


def test_generic_thumbnail_async_load(qtbot, monkeypatch, tmp_path):
    from PySide6.QtGui import QImage
    img = QImage(32, 32, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.blue)
    sample_img_path = tmp_path / 'sample_thumb.jpg'
    img.save(str(sample_img_path))

    import luckytwitch_engine
    monkeypatch.setattr(luckytwitch_engine, 'fetch_thumbnail', lambda url: sample_img_path)

    from qt_ui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()

    src = _make_sample_source('youtube', 120.0)
    src.thumbnail = 'https://example.com/thumb.jpg'

    win.on_info_ok(src, clips=[], loaded=False, warn='')

    qtbot.waitUntil(lambda: win.vod_strip.thumb_label.pixmap() is not None and not win.vod_strip.thumb_label.pixmap().isNull(), timeout=3000)
    qtbot.waitUntil(lambda: win.tab_plan.generic_thumb_label.pixmap() is not None and not win.tab_plan.generic_thumb_label.pixmap().isNull(), timeout=3000)

    assert win.vod_strip.thumb_label.text() == ''
    assert win.tab_plan.generic_thumb_label.text() == ''
