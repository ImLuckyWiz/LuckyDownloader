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


def test_a01_running_lock_removed_on_error_and_cleanup_stale(monkeypatch, tmp_path):
    """A-01: .running lock is removed on failure so retry reuses workdir, and stale locks are cleaned."""
    from core.errors import EngineError
    from core.finalize import cleanup_stale_workdirs, compute_job_workdir

    monkeypatch.setattr("core.finalize.check_disk_space", lambda *a, **kw: None)
    seen_workdirs = []

    def failing_dl(ctx, url, workdir, threads, **kw):
        seen_workdirs.append(workdir)
        assert (workdir / ".running").exists()
        raise EngineError("network boom")

    deps = PipelineDeps(
        find_tool=lambda name: "ffmpeg",
        download_full=failing_dl,
        load_chapters=lambda ctx, job: [],
        load_muted=lambda ctx, job: [],
    )
    src = SourceInfo(
        url="https://twitch.tv/videos/777",
        id="777",
        title="Fail VOD",
        date="2026-01-01",
        duration=30.0,
        uploader="Tester",
    )
    job = Job(source=src, opts=JobOptions(cut_text="", out_dir=str(tmp_path), strategy="full"))

    with pytest.raises(EngineError):
        run_job(job, Ctx(log=lambda m: None), deps=deps)

    # Lock must be removed on failure
    assert not (seen_workdirs[0] / ".running").exists()

    # Retry must reuse the same deterministic workdir
    with pytest.raises(EngineError):
        run_job(job, Ctx(log=lambda m: None), deps=deps)
    assert seen_workdirs[0] == seen_workdirs[1]

    # single_clip is included in compute_job_workdir
    w_no_clip = compute_job_workdir(src, job.opts, out_dir=tmp_path, single_clip=False)
    w_clip = compute_job_workdir(src, job.opts, out_dir=tmp_path, single_clip=True)
    assert w_no_clip != w_clip

    # cleanup_stale_workdirs removes dead-PID .running locks and max_age_hours=0
    dead_dir = tmp_path / ".luckytwitch_dead_1234"
    dead_dir.mkdir()
    (dead_dir / ".running").write_text("99999999", encoding="utf-8")
    assert cleanup_stale_workdirs(tmp_path, max_age_hours=0.0) >= 1
    assert not dead_dir.exists()


def test_a02_unknown_duration_defaults_to_sections_and_preserves_end(monkeypatch, tmp_path):
    """A-02: Unknown duration (0.0) chooses sections strategy and preserves part.end in split_copy."""
    from core.finalize import split_copy
    from core.planning import Part, choose_strategy

    strat, _ = choose_strategy([Part(1, 0.0, 60.0)], duration=0.0, mode="auto")
    assert strat == "sections"

    recorded_cmds = []

    def fake_ffmpeg(ctx, args, total=0.0):
        recorded_cmds.append(args)
        seg_dir = tmp_path / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        (seg_dir / "seg_000.mp4").write_bytes(b"a")
        (seg_dir / "list.csv").write_text("seg_000.mp4,0.0,60.0\n", encoding="utf-8")
        return ""

    deps = PipelineDeps(run_ffmpeg=fake_ffmpeg)
    full_file = tmp_path / "full.mp4"
    full_file.write_bytes(b"full")
    res = split_copy(Ctx(log=lambda m: None), full_file, [Part(1, 0.0, 60.0)], 0.0, "mp4", tmp_path, deps=deps)
    assert recorded_cmds, "ffmpeg must be invoked to split at 60.0 even when duration == 0.0"
    assert "-segment_times" in recorded_cmds[0]
    idx = recorded_cmds[0].index("-segment_times")
    assert recorded_cmds[0][idx + 1] == "60.000"
    assert res[1][0].name == "seg_000.mp4"


def test_a03_disk_check_uses_estimate_bytes_when_filesize_zero(monkeypatch, tmp_path):
    """A-03: check_disk_space falls back to estimate_bytes(fmt, dl_seconds) when fmt.filesize == 0."""
    recorded_required = []
    monkeypatch.setattr("core.finalize.check_disk_space", lambda out_dir, req=0: recorded_required.append(req))

    dummy_in = tmp_path / "in.mp4"
    dummy_in.write_bytes(b"0" * 1024)
    dummy_out = tmp_path / "out.mp4"

    deps = PipelineDeps(
        find_tool=lambda name: "ffmpeg",
        download_full=lambda *a, **kw: dummy_in,
        finalize_part=lambda *a, **kw: (dummy_out.write_bytes(b"1"), dummy_out)[1],
        load_chapters=lambda ctx, job: [],
        load_muted=lambda ctx, job: [],
    )
    # 1 hour at 8000 kbps = 3,600,000,000 bytes (~3.6 GB)
    src = SourceInfo(
        url="https://twitch.tv/videos/888",
        id="888",
        title="Big VOD",
        date="2026-01-01",
        duration=3600.0,
        uploader="Tester",
        formats=[VideoFormat(format_id="1080p", tbr=8000.0, filesize=0)],
    )
    job = Job(source=src, opts=JobOptions(cut_text="", out_dir=str(tmp_path), quality="1080p", strategy="full"))
    run_job(job, Ctx(log=lambda m: None), deps=deps)
    assert recorded_required
    assert recorded_required[0] > 3_000_000_000


def test_a05_sections_multipart_omits_download_archive(monkeypatch, tmp_path):
    """A-05: Multi-part sections download does not pass download_archive per part."""
    monkeypatch.setattr("core.finalize.check_disk_space", lambda *a, **kw: None)
    seen_archives = []

    def fake_dl_sec(ctx, url, part, workdir, threads, exact, **kw):
        seen_archives.append(kw.get("download_archive"))
        f = workdir / f"p{part.index}.mp4"
        f.write_bytes(b"x")
        return f

    def fake_fin(ctx, src_file, dest_stem, container, chs, tags, total, copy=False):
        out = tmp_path / f"{dest_stem.name}.{container}"
        out.write_bytes(b"y")
        return out

    deps = PipelineDeps(
        find_tool=lambda name: "ffmpeg",
        download_section=fake_dl_sec,
        finalize_part=fake_fin,
        load_chapters=lambda ctx, job: [],
        load_muted=lambda ctx, job: [],
    )
    src = SourceInfo(
        url="https://twitch.tv/videos/555",
        id="555",
        title="Multi-part",
        date="2026-01-01",
        duration=3600.0,
        uploader="Tester",
    )
    job = Job(
        source=src,
        opts=JobOptions(
            cut_text="0:00 - 0:10, 10:00 - 10:10",
            out_dir=str(tmp_path),
            strategy="sections",
            download_archive=str(tmp_path / "archive.txt"),
        ),
    )
    res = run_job(job, Ctx(log=lambda m: None), deps=deps)
    assert len(res) == 3
    assert seen_archives == [None, None, None]


def test_c01_run_job_enforces_cookies_scope(monkeypatch, tmp_path):
    """C-01: run_job() applies resolve_cookies_for_request() so Twitch VODs drop cookies under known_only."""
    monkeypatch.setattr("core.finalize.check_disk_space", lambda *a, **kw: None)
    seen_cookies = []

    def fake_dl_full(ctx, url, workdir, threads, **kw):
        seen_cookies.append(kw.get("cookies_browser"))
        f = workdir / "full.mp4"
        f.write_bytes(b"x")
        return f

    def fake_fin(ctx, src_file, dest_stem, container, chs, tags, total, copy=False):
        out = tmp_path / f"{dest_stem.name}.{container}"
        out.write_bytes(b"y")
        return out

    deps = PipelineDeps(
        find_tool=lambda name: "ffmpeg",
        download_full=fake_dl_full,
        finalize_part=fake_fin,
        load_chapters=lambda ctx, job: [],
        load_muted=lambda ctx, job: [],
    )
    twitch_src = SourceInfo(
        url="https://www.twitch.tv/videos/123456",
        id="123456",
        title="Twitch VOD",
        date="2026-01-01",
        duration=30.0,
        uploader="Tester",
    )
    job_known_only = Job(
        source=twitch_src,
        opts=JobOptions(
            cut_text="",
            out_dir=str(tmp_path),
            strategy="full",
            cookies_browser="firefox",
            cookies_scope="known_only",
        ),
    )
    run_job(job_known_only, Ctx(log=lambda m: None), deps=deps)
    assert seen_cookies[-1] is None

    # Explicit per-job override or scope="all" allows cookies
    job_explicit = Job(
        source=twitch_src,
        opts=JobOptions(
            cut_text="",
            out_dir=str(tmp_path),
            strategy="full",
            cookies_browser="firefox",
            cookies_scope="known_only",
            cookies_explicit=True,
        ),
    )
    run_job(job_explicit, Ctx(log=lambda m: None), deps=deps)
    assert seen_cookies[-1] == "firefox"


def test_c05_export_diagnostics_zip_scrubs_home_and_query_params(monkeypatch, tmp_path):
    """C-05: export_diagnostics_zip() scrubs Path.home() and signed URL query params."""
    import zipfile
    import core.paths as paths
    from core.diagnostics import export_diagnostics_zip

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    home_str = str(Path.home())
    (log_dir / "luckydownloader.log").write_text(
        f"Saving to {home_str}\\Videos\nGET https://cdn.example.com/v.m3u8?token=secret123&sig=abc&X-Amz-Signature=xyz&ok=1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.settings.load_settings",
        lambda: {"out_dir": f"{home_str}\\Downloads", "twitch_token": "tok"},
    )

    dest = tmp_path / "diag.zip"
    export_diagnostics_zip(dest)

    with zipfile.ZipFile(dest, "r") as zf:
        settings_txt = zf.read("settings_redacted.json").decode("utf-8")
        log_txt = zf.read("logs/luckydownloader.log").decode("utf-8")

    assert home_str not in settings_txt
    assert home_str not in log_txt
    assert "secret123" not in log_txt
    assert "abc" not in log_txt
    assert "xyz" not in log_txt
    assert "token=[REDACTED]" in log_txt
    assert "sig=[REDACTED]" in log_txt
    assert "X-Amz-Signature=[REDACTED]" in log_txt
    assert "ok=1" in log_txt

