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

    opts_exact = JobOptions(cut_text="0:00:00 - 0:10:00", out_dir=str(tmp_path), strategy="sections", quality="1080p60", exact=True)
    w_exact = compute_job_workdir(src, opts_exact, fmt=fmt)

    assert w1 == w1_retry
    assert w1 != w2
    assert w1 != w_exact
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

    # A live-PID .running workdir is preserved under normal age cleanup (max_age_hours=48.0)
    active_dir = tmp_path / ".luckytwitch_789_active"
    active_dir.mkdir()
    (active_dir / ".running").write_text(str(os.getpid()), encoding="utf-8")
    os.utime(active_dir, (old_mtime, old_mtime))
    assert cleanup_stale_workdirs(tmp_path, max_age_hours=48.0) == 0
    assert active_dir.exists()

    # Cleaning with max_age_hours=0 removes both fresh_dir and .running workdirs (A-01)
    removed_all = cleanup_stale_workdirs(tmp_path, max_age_hours=0.0)
    assert removed_all == 2
    assert not fresh_dir.exists()
    assert not active_dir.exists()
    assert unrelated_dir.exists()


def test_k03_luckydownloader_engine_sys_modules_alias(monkeypatch):
    import sys
    import luckytwitch_engine
    import luckydownloader_engine
    from core.runtime import resolve_dep

    assert sys.modules["luckydownloader_engine"] is sys.modules["luckytwitch_engine"]
    assert luckydownloader_engine is luckytwitch_engine

    sentinel = lambda name: f"patched:{name}"  # noqa: E731
    orig = luckytwitch_engine.find_tool
    monkeypatch.setattr(luckydownloader_engine, "find_tool", sentinel)
    assert resolve_dep("find_tool", orig) is sentinel


def test_b03_source_info_is_age_restricted_single_field():
    from dataclasses import fields

    names = [f.name for f in fields(SourceInfo)]
    assert names.count("is_age_restricted") == 1
    assert names[-1] == "is_age_restricted"
    # Original positional field indices preserved
    src = SourceInfo("https://twitch.tv/videos/1", "1", "Title", "Streamer", 60.0, "2026-11-15", "1")
    assert src.segments == []
    assert src.is_age_restricted is False


def test_detect_hw_encoder_probes_and_caches(monkeypatch, tmp_path):
    import json
    import subprocess
    from core import tools

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    monkeypatch.setattr(tools, "TOOLS_DIR", tools_dir)

    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"bin")
    probe_calls = []

    def fake_run(cmd, **kw):
        enc = cmd[cmd.index("-c:v") + 1]
        probe_calls.append(enc)
        rc = 0 if enc == "h264_qsv" else 1
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    got = tools.detect_hw_encoder(str(fake_ffmpeg))
    assert got == "h264_qsv"
    assert probe_calls == ["h264_nvenc", "h264_qsv"]
    cached = json.loads((tools_dir / "versions.json").read_text(encoding="utf-8"))
    assert cached["hw_encoder"] == "h264_qsv"

    # Second call with same mtime hits cache without spawning subprocess
    probe_calls.clear()
    assert tools.detect_hw_encoder(str(fake_ffmpeg)) == "h264_qsv"
    assert probe_calls == []

    # Updating ffmpeg mtime invalidates cache and re-probes
    new_mtime = fake_ffmpeg.stat().st_mtime + 20.0
    os.utime(fake_ffmpeg, (new_mtime, new_mtime))
    monkeypatch.setattr(tools.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=""))
    assert tools.detect_hw_encoder(str(fake_ffmpeg)) == "libx264"


def test_cut_exact_uses_hw_encoder_and_falls_back_to_libx264(tmp_path):
    from core.finalize import PipelineDeps, cut_exact
    from core.planning import Part
    from core.runtime import Ctx

    src = tmp_path / "full.mp4"
    src.write_bytes(b"video")
    calls = []
    logs = []

    def fake_ffmpeg(ctx, args, total=None):
        calls.append(args)
        if "h264_nvenc" in args:
            raise EngineError("nvenc device not found")
        Path(args[-1]).write_bytes(b"encoded")
        return ""

    deps = PipelineDeps(
        find_tool=lambda n: "fake_ffmpeg" if n == "ffmpeg" else None,
        detect_hw_encoder=lambda p: "h264_nvenc",
        run_ffmpeg=fake_ffmpeg,
    )
    ctx = Ctx(log=logs.append)
    out = cut_exact(ctx, src, Part(1, 5.0, 15.0), "mp4", tmp_path, video_encoder="auto", smart=False, deps=deps)
    assert out.is_file()
    assert len(calls) == 2
    assert "h264_nvenc" in calls[0]
    assert "-cq" in calls[0] and "20" in calls[0]
    assert "libx264" in calls[1]
    assert "-crf" in calls[1] and "18" in calls[1]
    assert any("h264_nvenc" in m for m in logs)
    assert any("libx264" in m for m in logs)


def test_probe_keyframes_parses_ffprobe_output(monkeypatch, tmp_path):
    import subprocess
    from core import premiere_export

    video = tmp_path / "vod.mp4"
    video.write_bytes(b"v")
    seen_cmds = []

    def fake_run(cmd, **kw):
        seen_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="100.000000\nN/A\n12.500000,\n12.500000\n", stderr="")

    monkeypatch.setattr(premiere_export, "find_tool", lambda n: "fake_ffprobe" if n == "ffprobe" else None)
    monkeypatch.setattr(premiere_export.subprocess, "run", fake_run)

    pts = premiere_export.probe_keyframes(video, [10.0, 100.0])
    assert pts == [12.5, 100.0]
    assert "-skip_frame" in seen_cmds[0] and "nokey" in seen_cmds[0]
    assert "-read_intervals" in seen_cmds[0]
    ri = seen_cmds[0][seen_cmds[0].index("-read_intervals") + 1]
    assert "0.000%+30,85.000%+30" == ri


def test_smart_cut_splices_gop_boundaries_and_falls_back(monkeypatch, tmp_path):
    from core import finalize
    from core.finalize import PipelineDeps, cut_exact
    from core.planning import Part
    from core.runtime import Ctx

    src = tmp_path / "vod.mp4"
    src.write_bytes(b"vod")
    monkeypatch.setattr(
        finalize,
        "probe_stream_signature",
        lambda p: {"codec_name": "h264", "profile": "High", "pix_fmt": "yuv420p", "time_base": "1/90000"},
    )

    # 1. 1-hour part (3600s > 20s): re-encodes only boundary stubs, stream-copies interior, concats with timescale=1000
    calls = []

    def fake_ffmpeg(ctx, args, total=None):
        calls.append(args)
        Path(args[-1]).write_bytes(b"ok")
        return ""

    deps = PipelineDeps(
        find_tool=lambda n: "fake_ffmpeg" if n == "ffmpeg" else None,
        detect_hw_encoder=lambda p: "libx264",
        probe_keyframes=lambda p, times: [8.0, 12.0, 3606.0, 3608.0, 3614.0],
        run_ffmpeg=fake_ffmpeg,
    )
    out = cut_exact(Ctx(log=lambda m: None), src, Part(1, 10.5, 3610.5), "mp4", tmp_path, deps=deps)
    assert out.is_file()
    assert len(calls) == 4
    # head: [10.5, 12.0] (1.5s)
    assert calls[0][calls[0].index("-ss") + 1] == "10.500"
    assert calls[0][calls[0].index("-t") + 1] == "1.500"
    assert "libx264" in calls[0]
    assert "-video_track_timescale" in calls[0] and "90000" in calls[0]
    # mid: stream copy [12.0, 3608.0] (3596.0s)
    assert calls[1][calls[1].index("-ss") + 1] == "12.000"
    assert calls[1][calls[1].index("-t") + 1] == "3596.000"
    assert "-c" in calls[1] and "copy" in calls[1]
    # tail: [3608.0, 3610.5] (2.5s)
    assert calls[2][calls[2].index("-ss") + 1] == "3608.000"
    assert calls[2][calls[2].index("-t") + 1] == "2.500"
    assert "libx264" in calls[2]
    # concat: -f concat -safe 0 -c copy -movie_timescale 1000
    assert "-f" in calls[3] and "concat" in calls[3]
    assert "-safe" in calls[3] and "0" in calls[3]
    assert "-movie_timescale" in calls[3] and "1000" in calls[3]

    # 2. Short part (<= 20s) skips Smart Cut and does a single full re-encode
    calls.clear()
    out_short = cut_exact(Ctx(log=lambda m: None), src, Part(2, 10.0, 25.0), "mp4", tmp_path, deps=deps)
    assert out_short.is_file()
    assert len(calls) == 1
    assert "libx264" in calls[0]

    # 3. Mismatched stream codec (e.g. vp9) falls back to full cut_exact
    calls.clear()
    monkeypatch.setattr(
        finalize,
        "probe_stream_signature",
        lambda p: {"codec_name": "vp9", "profile": "", "pix_fmt": "yuv420p", "time_base": "1/1000"},
    )
    out_vp9 = cut_exact(Ctx(log=lambda m: None), src, Part(3, 10.5, 3610.5), "mp4", tmp_path, deps=deps)
    assert out_vp9.is_file()
    assert len(calls) == 1
    assert "libx264" in calls[0]


def test_video_encoder_option_wiring(tmp_path):
    from core.job import Job, deserialize_job, serialize_job
    from core.options import build_options
    from core.settings import DEFAULTS

    assert DEFAULTS["video_encoder"] == "auto"
    opts = build_options({**DEFAULTS, "video_encoder": "nvenc"})
    assert opts.video_encoder == "nvenc"

    src = SourceInfo("https://twitch.tv/videos/1", "1", "V", "S", 100.0, "2026-11-15", "1")
    job = Job(source=src, opts=opts)
    restored = deserialize_job(serialize_job(job))
    assert restored.opts.video_encoder == "nvenc"

    # Legacy queue_state without video_encoder defaults safely to "auto"
    raw = serialize_job(job)
    raw["opts"].pop("video_encoder", None)
    assert deserialize_job(raw).opts.video_encoder == "auto"


def test_run_job_forwards_video_encoder_and_aligned_cookies(monkeypatch, tmp_path):
    from core.finalize import PipelineDeps, run_job
    from core.job import Job
    from core.runtime import Ctx

    monkeypatch.setattr("core.finalize.check_disk_space", lambda *a, **kw: None)
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)
    seen = {}

    def fake_aligned(ctx, url, part, workdir, format_id=None, audio_only=False, *, cookies_browser=None):
        seen["cookies_browser"] = cookies_browser
        return raw, 0.0, 40.0

    def fake_cut(ctx, f, part, container, workdir, offset=None, *, video_encoder="auto", deps=None):
        seen["video_encoder"] = video_encoder
        return raw

    deps = PipelineDeps(
        find_tool=lambda n: "ffmpeg",
        download_section_aligned=fake_aligned,
        cut_exact=fake_cut,
        finalize_part=lambda ctx, f, stem, container, chs, tags, total, copy=False: stem.with_suffix(".mp4"),
        load_chapters=lambda ctx, job: [],
        load_muted=lambda ctx, job: [],
    )
    src = SourceInfo(
        url="https://www.twitch.tv/videos/42",
        id="42",
        title="Aligned",
        uploader="Streamer",
        duration=3600.0,
        date="2026-11-15",
        twitch_vod_id="42",
    )
    opts = JobOptions(
        cut_text="0:00:05 - 0:00:35",
        out_dir=str(tmp_path / "out"),
        strategy="sections",
        exact=True,
        video_encoder="qsv",
        cookies_browser="chrome",
        cookies_scope="all",
    )
    run_job(Job(source=src, opts=opts), Ctx(log=lambda m: None), deps=deps)
    assert seen["cookies_browser"] == "chrome"
    assert seen["video_encoder"] == "qsv"
