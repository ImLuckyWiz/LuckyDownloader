"""Tests for core download pipeline pre-flight validations and execution flow."""

from collections import namedtuple
from pathlib import Path
import pytest

from core.errors import DiskSpaceError
from core.finalize import PipelineDeps, run_job
from core.job import Job, JobOptions
from core.planning import Plan, Part
from core.runtime import Ctx
from core.source_info import SourceInfo, VideoFormat

Usage = namedtuple("Usage", ["total", "used", "free"])


def test_run_job_preflight_disk_check_aborts_early(monkeypatch, tmp_path):
    # Only 50 MB free space
    monkeypatch.setattr("shutil.disk_usage", lambda path: Usage(total=10**11, used=10**11 - 50 * 1024 * 1024, free=50 * 1024 * 1024))
    monkeypatch.setattr("core.finalize.find_tool", lambda name: "ffmpeg")
    import sys
    if "luckytwitch_engine" in sys.modules:
        monkeypatch.setattr("luckytwitch_engine.find_tool", lambda name: "ffmpeg")

    src = SourceInfo(
        url="https://twitch.tv/videos/12345",
        id="12345",
        title="Test VOD",
        date="2026-01-01",
        duration=60.0,
        uploader="Lucky",
        formats=[VideoFormat(format_id="1080p", filesize=100 * 1024 * 1024)],
    )
    job = Job(source=src, opts=JobOptions(cut_text="", out_dir=str(tmp_path), quality="1080p"))
    ctx = Ctx(log=lambda m: None)

    with pytest.raises(DiskSpaceError) as exc_info:
        run_job(job, ctx)

    assert "Insufficient disk space" in str(exc_info.value)


def test_run_job_preflight_disk_check_multiplier(monkeypatch, tmp_path):
    recorded_required = []

    def fake_check(out_dir, required_bytes=200 * 1024 * 1024):
        recorded_required.append(required_bytes)

    monkeypatch.setattr("core.finalize.check_disk_space", fake_check)
    monkeypatch.setattr("core.finalize.find_tool", lambda name: "ffmpeg")
    monkeypatch.setattr("core.finalize._load_chapters", lambda ctx, job: [])
    monkeypatch.setattr("core.finalize._load_muted", lambda ctx, job: [])
    # Also patch luckytwitch_engine if loaded
    import sys
    if "luckytwitch_engine" in sys.modules:
        monkeypatch.setattr("luckytwitch_engine.find_tool", lambda name: "ffmpeg")
        monkeypatch.setattr("luckytwitch_engine._load_chapters", lambda ctx, job: [])
        monkeypatch.setattr("luckytwitch_engine._load_muted", lambda ctx, job: [])

    # Single part: multiplier 1.1x filesize
    src_single = SourceInfo(
        url="https://twitch.tv/videos/12345",
        id="12345",
        title="Test VOD",
        date="2026-01-01",
        duration=60.0,
        uploader="Lucky",
        formats=[VideoFormat(format_id="1080p", filesize=100 * 1024 * 1024)],
    )
    job_single = Job(source=src_single, opts=JobOptions(cut_text="", out_dir=str(tmp_path), quality="1080p"))

    monkeypatch.setattr("core.finalize.download_full", lambda *args, **kwargs: tmp_path / "dummy.mp4")
    monkeypatch.setattr("core.finalize.finalize_part", lambda *args, **kwargs: tmp_path / "dummy_out.mp4")
    if "luckytwitch_engine" in sys.modules:
        monkeypatch.setattr("luckytwitch_engine.download_full", lambda *args, **kwargs: tmp_path / "dummy.mp4")
        monkeypatch.setattr("luckytwitch_engine.finalize_part", lambda *args, **kwargs: tmp_path / "dummy_out.mp4")

    (tmp_path / "dummy.mp4").write_text("test")

    ctx = Ctx(log=lambda m: None)
    run_job(job_single, ctx)

    assert len(recorded_required) == 1
    # 100 MB * 1.1 = 110 MB
    assert recorded_required[0] == int(100 * 1024 * 1024 * 1.1)


def test_pipeline_deps_injection_without_luckytwitch_engine(monkeypatch, tmp_path):
    monkeypatch.setattr("core.finalize.check_disk_space", lambda *a, **kw: None)
    dummy_in = tmp_path / "in.mp4"
    dummy_in.write_bytes(b"0" * 8192)
    dummy_out = tmp_path / "out.mp4"

    called = {"dl": 0, "fin": 0}

    def fake_dl(ctx, url, workdir, threads, **kw):
        called["dl"] += 1
        return dummy_in

    def fake_fin(ctx, src_file, dest_stem, container, chs, tags, total, copy=False):
        called["fin"] += 1
        dummy_out.write_bytes(b"1" * 8192)
        return dummy_out

    deps = PipelineDeps(
        find_tool=lambda name: "ffmpeg",
        download_full=fake_dl,
        finalize_part=fake_fin,
        load_chapters=lambda ctx, job: [],
        load_muted=lambda ctx, job: [],
    )

    src = SourceInfo(
        url="https://twitch.tv/videos/99999",
        id="99999",
        title="Injected VOD",
        date="2026-01-01",
        duration=30.0,
        uploader="Tester",
    )
    job = Job(source=src, opts=JobOptions(cut_text="", out_dir=str(tmp_path), strategy="full"))
    res = run_job(job, Ctx(log=lambda m: None), deps=deps)
    assert res == [dummy_out]
    assert called == {"dl": 1, "fin": 1}


def test_core_modules_do_not_inspect_luckytwitch_engine_in_sys_modules():
    root = Path(__file__).resolve().parent.parent / "core"
    offenders = []
    for py_file in sorted(root.rglob("*.py")):
        for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "luckytwitch_engine" in stripped:
                offenders.append(f"{py_file.relative_to(root.parent)}:{lineno}: {stripped}")
    assert offenders == []

