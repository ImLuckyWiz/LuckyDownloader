"""Unit tests for core/finalize.py helper functions (disk space checks, naming, etc.)."""

import os
import time
from collections import namedtuple
from pathlib import Path
import pytest

from core.errors import DiskSpaceError, EngineError
from core.finalize import check_disk_space, cleanup_stale_workdirs, compute_job_workdir
from core.job import JobOptions
from core.source_info import SourceInfo, VideoFormat

Usage = namedtuple("Usage", ["total", "used", "free"])


def test_check_disk_space_sufficient(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.disk_usage", lambda path: Usage(total=10**11, used=10**10, free=10**10))
    # 10 GB free > 200 MB required -> does not raise
    check_disk_space(tmp_path, 200 * 1024 * 1024)


def test_check_disk_space_insufficient_raises_disk_space_error(monkeypatch, tmp_path):
    # 50 MB free < 200 MB required
    monkeypatch.setattr("shutil.disk_usage", lambda path: Usage(total=10**11, used=10**11 - 50 * 1024 * 1024, free=50 * 1024 * 1024))
    with pytest.raises(DiskSpaceError) as exc_info:
        check_disk_space(tmp_path, 200 * 1024 * 1024)

    err = exc_info.value
    assert isinstance(err, RuntimeError)
    assert isinstance(err, EngineError)
    assert "50 MB free" in str(err)
    assert "200 MB required" in str(err)


def test_check_disk_space_os_error_ignored(monkeypatch, tmp_path):
    def fake_usage(path):
        raise OSError("Permission denied or drive not ready")

    monkeypatch.setattr("shutil.disk_usage", fake_usage)
    # Should not raise
    check_disk_space(tmp_path, 200 * 1024 * 1024)


def test_check_disk_space_default_threshold(monkeypatch, tmp_path):
    # 150 MB free < default 200 MB
    monkeypatch.setattr("shutil.disk_usage", lambda path: Usage(total=10**11, used=10**11, free=150 * 1024 * 1024))
    with pytest.raises(DiskSpaceError):
        check_disk_space(tmp_path)


def test_compute_job_workdir_is_deterministic_and_unique_per_cuts(tmp_path):
    src = SourceInfo(
        url="https://www.twitch.tv/videos/12345",
        id="12345",
        title="Test",
        uploader="Streamer",
        duration=3600.0,
        date="2026-01-01",
        twitch_vod_id="12345",
    )
    fmt = VideoFormat(format_id="1080p60", height=1080, fps=60)
    opts1 = JobOptions(cut_text="0:00:00 - 0:10:00", out_dir=str(tmp_path), strategy="sections", quality="1080p60")
    opts1_retry = JobOptions(cut_text="0:00:00 - 0:10:00", out_dir=str(tmp_path), strategy="sections", quality="1080p60")
    opts2 = JobOptions(cut_text="0:10:00 - 0:20:00", out_dir=str(tmp_path), strategy="sections", quality="1080p60")

    w1 = compute_job_workdir(src, opts1, fmt=fmt)
    w1_retry = compute_job_workdir(src, opts1_retry, fmt=fmt)
    w2 = compute_job_workdir(src, opts2, fmt=fmt)

    assert w1 == w1_retry
    assert w1 != w2
    assert w1.name.startswith(".luckytwitch_12345_1080p60_")


def test_cleanup_stale_workdirs_removes_old_and_keeps_recent(tmp_path):
    old_dir = tmp_path / ".luckytwitch_123_old"
    old_dir.mkdir()
    (old_dir / "part.mp4.part").write_bytes(b"data")
    old_mtime = time.time() - (72 * 3600)
    os.utime(old_dir, (old_mtime, old_mtime))

    old_work_dir = tmp_path / ".luckydownloader_work_abc"
    old_work_dir.mkdir()
    os.utime(old_work_dir, (old_mtime, old_mtime))

    fresh_dir = tmp_path / ".luckytwitch_456_fresh"
    fresh_dir.mkdir()

    unrelated_dir = tmp_path / "NormalFolder"
    unrelated_dir.mkdir()
    os.utime(unrelated_dir, (old_mtime, old_mtime))

    removed = cleanup_stale_workdirs(tmp_path, max_age_hours=48.0)
    assert removed == 2
    assert not old_dir.exists()
    assert not old_work_dir.exists()
    assert fresh_dir.exists()
    assert unrelated_dir.exists()

    # Cleaning with max_age_hours=0 removes remaining temp workdirs too
    removed_all = cleanup_stale_workdirs(tmp_path, max_age_hours=0.0)
    assert removed_all == 1
    assert not fresh_dir.exists()
    assert unrelated_dir.exists()
