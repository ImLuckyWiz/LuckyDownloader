from __future__ import annotations

from pathlib import Path

from core import history
from core.history import HistoryEntry


def test_history_entry_from_dict():
    data = {
        "vod_id": "123456",
        "title": "Epic Stream",
        "streamer": "lucky",
        "date": "2026-10-28",
        "parts": 2,
        "folder": "/downloads/stream",
        "quality": "1080p60",
    }
    e = HistoryEntry.from_dict(data)
    assert e.vod_id == "123456"
    assert e.title == "Epic Stream"
    assert e.streamer == "lucky"
    assert e.parts == 2
    assert e.quality == "1080p60"
    assert e.downloaded_at != ""


def test_load_history_empty_when_missing(tmp_path: Path):
    target = tmp_path / "history.json"
    assert history.load_history(target) == []


def test_load_history_handles_corrupt_json(tmp_path: Path):
    target = tmp_path / "history.json"
    target.write_text("invalid json", encoding="utf-8")
    assert history.load_history(target) == []


def test_record_and_load_history_roundtrip(tmp_path: Path):
    target = tmp_path / "history.json"
    entry1 = {
        "vod_id": "1001",
        "title": "Stream 1",
        "streamer": "alice",
        "date": "2026-10-25",
        "parts": 1,
        "folder": str(tmp_path / "out1"),
        "quality": "Best available",
    }
    history.record_download(entry1, path=target)

    loaded = history.load_history(target)
    assert len(loaded) == 1
    assert loaded[0].vod_id == "1001"
    assert loaded[0].title == "Stream 1"

    # Add second entry
    entry2 = {
        "vod_id": "1002",
        "title": "Stream 2",
        "streamer": "bob",
        "date": "2026-10-26",
        "parts": 2,
        "folder": str(tmp_path / "out2"),
        "quality": "720p60",
    }
    history.record_download(entry2, path=target)

    loaded2 = history.load_history(target)
    assert len(loaded2) == 2
    # newest first
    assert loaded2[0].vod_id == "1002"
    assert loaded2[1].vod_id == "1001"


def test_is_downloaded_check(tmp_path: Path):
    target = tmp_path / "history.json"
    history.record_download({"vod_id": "999", "title": "Winner VOD"}, path=target)

    found = history.is_downloaded("999", path=target)
    assert found is not None
    assert found.title == "Winner VOD"

    assert history.is_downloaded("000", path=target) is None
    assert history.is_downloaded("", path=target) is None
    assert history.is_downloaded(None, path=target) is None


def test_record_download_disabled_flag(tmp_path: Path):
    target = tmp_path / "history.json"
    history.record_download({"vod_id": "888"}, path=target, enabled=False)
    assert not target.exists()
    assert history.load_history(target) == []


def test_clear_history(tmp_path: Path):
    target = tmp_path / "history.json"
    history.record_download({"vod_id": "777"}, path=target)
    assert target.is_file()

    history.clear_history(target)
    assert not target.is_file()
    assert history.load_history(target) == []


def test_deduplication_moves_to_top(tmp_path: Path):
    target = tmp_path / "history.json"
    history.record_download({"vod_id": "1", "folder": "/path1", "title": "Old"}, path=target)
    history.record_download({"vod_id": "2", "folder": "/path2", "title": "Other"}, path=target)
    history.record_download({"vod_id": "1", "folder": "/path1", "title": "New"}, path=target)

    loaded = history.load_history(target)
    assert len(loaded) == 2
    assert loaded[0].vod_id == "1"
    assert loaded[0].title == "New"
    assert loaded[1].vod_id == "2"


def test_history_dialog_populates_rows(qtbot, tmp_path, monkeypatch):
    import core.paths as paths
    from qt_ui import dialogs
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda *a, **k: True)
    target = tmp_path / "luckytwitch_history.json"
    monkeypatch.setattr(paths, "HISTORY_PATH", target)
    history.record_download({"vod_id": "123", "title": "Cool Stream", "streamer": "alice"}, path=target)

    from qt_ui.dialogs import HistoryDialog
    dlg = HistoryDialog()
    qtbot.addWidget(dlg)

    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 0).text() == "Twitch"
    assert dlg.table.item(0, 2).text() == "alice"
    assert dlg.table.item(0, 3).text() == "Cool Stream"
    assert "1 completed" in dlg.count_label.text()

    # Test clear
    dlg.clear_btn.click()
    assert dlg.table.rowCount() == 0
    assert not target.is_file()


def test_vod_strip_shows_downloaded_badge(qtbot, tmp_path, monkeypatch):
    import core.paths as paths
    target = tmp_path / "luckytwitch_history.json"
    monkeypatch.setattr(paths, "HISTORY_PATH", target)
    history.record_download({"vod_id": "999"}, path=target)

    from qt_ui.shell import VodStrip
    strip = VodStrip()
    qtbot.addWidget(strip)

    class FakeSrc:
        vod_id = "999"
        twitch_vod_id = "999"
        title = "Title"
        uploader = "bob"
        upload_date = "2026-10-28"
        duration = 3600
        url = "https://twitch.tv/videos/999"

    strip.set_vod(FakeSrc())
    assert strip.downloaded_badge.isVisible()

    class NotDownloadedSrc:
        vod_id = "111"
        twitch_vod_id = "111"
        title = "Other"
        uploader = "bob"
        upload_date = "2026-10-28"
        duration = 3600
        url = "https://twitch.tv/videos/111"

    strip.set_vod(NotDownloadedSrc())
    assert not strip.downloaded_badge.isVisible()


def test_is_downloaded_by_url(tmp_path: Path):
    target = tmp_path / "history.json"
    history.record_download(
        {
            "site": "youtube",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "streamer": "Rick Astley",
        },
        path=target,
    )

    found = history.is_downloaded(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", path=target)
    assert found is not None
    assert found.title == "Never Gonna Give You Up"
    assert found.site == "youtube"

    assert history.is_downloaded(url="https://www.youtube.com/watch?v=other", path=target) is None


def test_history_dialog_populates_generic_entry(qtbot, tmp_path, monkeypatch):
    import core.paths as paths
    target = tmp_path / "luckytwitch_history.json"
    monkeypatch.setattr(paths, "HISTORY_PATH", target)
    history.record_download(
        {
            "site": "tiktok",
            "url": "https://www.tiktok.com/@user/video/12345",
            "title": "Fun Clip",
            "streamer": "user",
        },
        path=target,
    )

    from qt_ui.dialogs import HistoryDialog
    dlg = HistoryDialog()
    qtbot.addWidget(dlg)

    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 0).text() == "Tiktok"
    assert dlg.table.item(0, 2).text() == "user"
    assert dlg.table.item(0, 3).text() == "Fun Clip"

