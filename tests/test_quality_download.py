"""Tests for Phase 2: format selection forwarded to yt-dlp, playlist URL, workdir naming, and run_job wiring."""

import json
import subprocess
from pathlib import Path

import pytest

import luckytwitch_engine as eng

FIXTURE_SHORT = Path("tests/fixtures/vod_single_game_short.json")


def load_fixture(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _ctx():
    logs = []
    return eng.Ctx(log=logs.append), logs


class FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.stdout = iter([])
        self.returncode = 0

    def wait(self):
        return 0

    def poll(self):
        return 0


# --- 1. run_ytdlp with and without format_id --- #

def test_run_ytdlp_with_format_id(monkeypatch):
    recorded = []

    monkeypatch.setattr(eng, "find_tool", lambda n: "yt-dlp")
    monkeypatch.setattr(eng.subprocess, "Popen", lambda cmd, **kw: (recorded.append(cmd), FakePopen(cmd))[1])

    ctx, _ = _ctx()
    eng.run_ytdlp(ctx, ["https://twitch.tv/videos/123"], threads=4, format_id="720p60")

    assert len(recorded) == 1
    cmd = recorded[0]
    assert "-f" in cmd
    idx = cmd.index("-f")
    assert cmd[idx + 1] == "720p60"
    assert "-S" not in cmd


def test_run_ytdlp_without_format_id(monkeypatch):
    recorded = []

    monkeypatch.setattr(eng, "find_tool", lambda n: "yt-dlp")
    monkeypatch.setattr(eng.subprocess, "Popen", lambda cmd, **kw: (recorded.append(cmd), FakePopen(cmd))[1])

    ctx, _ = _ctx()
    eng.run_ytdlp(ctx, ["https://twitch.tv/videos/123"], threads=4)

    assert len(recorded) == 1
    cmd = recorded[0]
    assert "-S" in cmd
    assert "-f" not in cmd


# --- 2. get_playlist_url with and without format_id --- #

def test_get_playlist_url_with_format_id(monkeypatch):
    recorded = []

    monkeypatch.setattr(eng, "find_tool", lambda n: "yt-dlp")

    def fake_run(args, **kwargs):
        recorded.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="https://cdn.example.com/stream.m3u8\n", stderr="")

    monkeypatch.setattr(eng.subprocess, "run", fake_run)

    ctx, _ = _ctx()
    url = eng.get_playlist_url(ctx, "https://twitch.tv/videos/123", format_id="720p60")
    assert url == "https://cdn.example.com/stream.m3u8"
    assert len(recorded) == 1
    cmd = recorded[0]
    assert "-f" in cmd
    idx = cmd.index("-f")
    assert cmd[idx + 1] == "720p60"
    assert "-S" not in cmd


def test_get_playlist_url_without_format_id(monkeypatch):
    recorded = []

    monkeypatch.setattr(eng, "find_tool", lambda n: "yt-dlp")

    def fake_run(args, **kwargs):
        recorded.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="https://cdn.example.com/stream.m3u8\n", stderr="")

    monkeypatch.setattr(eng.subprocess, "run", fake_run)

    ctx, _ = _ctx()
    url = eng.get_playlist_url(ctx, "https://twitch.tv/videos/123")
    assert url == "https://cdn.example.com/stream.m3u8"
    assert len(recorded) == 1
    cmd = recorded[0]
    assert "-S" in cmd
    assert "-f" not in cmd


# --- 3. describe_quality pure helper --- #

def test_describe_quality_cases():
    f_1080 = eng.VideoFormat("1080p60", height=1080, fps=60, tbr=6000, source=True)
    f_720 = eng.VideoFormat("720p60", height=720, fps=60, tbr=3000)
    f_480 = eng.VideoFormat("480p30", height=480, fps=30, tbr=1500)
    f_audio = eng.VideoFormat("Audio_Only", height=0, fps=0, tbr=160, audio_only=True)

    # 1. asked "best" or empty -> nothing appended
    assert eng.describe_quality(f_1080, eng.QUALITY_BEST) == f"Quality: {f_1080.label}"
    assert eng.describe_quality(f_1080, "") == f"Quality: {f_1080.label}"
    assert eng.describe_quality(f_1080, None) == f"Quality: {f_1080.label}"

    # 2. asked equal to format_id -> nothing appended
    assert eng.describe_quality(f_720, "720p60") == f"Quality: {f_720.label}"
    assert eng.describe_quality(f_720, "720P60") == f"Quality: {f_720.label}"

    # 3. asked "audio" and result is audio-only -> nothing appended
    assert eng.describe_quality(f_audio, "audio") == f"Quality: {f_audio.label}"

    # 4. asked "480p" and got "480p30" -> appended
    assert eng.describe_quality(f_480, "480p") == f"Quality: {f_480.label} (asked for 480p)"

    # 5. asked "audio" and got video fallback -> appended
    assert eng.describe_quality(f_1080, "audio") == f"Quality: {f_1080.label} (asked for audio)"


# --- 4. run_job wiring with formats --- #

def _patch_run_job_wiring(monkeypatch, tmp_path, aligned_fake, download_fake=None):
    monkeypatch.setattr(eng, "find_tool", lambda n: "/bin/true")
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)

    monkeypatch.setattr(eng, "download_section_aligned", aligned_fake)
    if download_fake:
        monkeypatch.setattr(eng, "download_full", download_fake)
        monkeypatch.setattr(eng, "download_section", download_fake)
    else:
        monkeypatch.setattr(eng, "download_section", lambda *a, **k: raw)

    monkeypatch.setattr(eng, "cut_exact", lambda ctx, f, part, container, workdir, offset=None: raw)
    monkeypatch.setattr(eng, "finalize_part", lambda ctx, f, stem, container, chapters, tags, total, copy=False: stem.with_suffix(".mp4"))
    return raw


def test_run_job_forwards_format_id(monkeypatch, tmp_path):
    formats = eng.parse_formats(load_fixture(FIXTURE_SHORT).get("formats"))
    src = eng.SourceInfo(
        url="https://www.twitch.tv/videos/1",
        id="1",
        title="Test Stream",
        uploader="Streamer",
        duration=3600.0,
        date="2026-01-01",
        twitch_vod_id="1",
        formats=formats,
    )
    opts = eng.JobOptions(
        cut_text="0:20:00 - 0:21:00",
        out_dir=str(tmp_path / "out"),
        strategy="sections",
        quality="720p",
    )
    job = eng.Job(source=src, opts=opts)

    calls = {}
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)

    def fake_aligned(ctx, url, part, workdir, **kw):
        calls.update(kw)
        return raw, 1200.0, 1260.0

    _patch_run_job_wiring(monkeypatch, tmp_path, fake_aligned)
    ctx, logs = _ctx()

    eng.run_job(job, ctx)

    assert calls.get("format_id") == "720p60"
    assert any("Quality: 720p60" in line for line in logs)


def test_run_job_no_formats_receives_no_format_id(monkeypatch, tmp_path):
    src = eng.SourceInfo(
        url="https://www.twitch.tv/videos/1",
        id="1",
        title="Test Stream",
        uploader="Streamer",
        duration=3600.0,
        date="2026-01-01",
        twitch_vod_id="1",
        formats=[],
    )
    opts = eng.JobOptions(
        cut_text="0:20:00 - 0:21:00",
        out_dir=str(tmp_path / "out"),
        strategy="sections",
        quality=eng.QUALITY_BEST,
    )
    job = eng.Job(source=src, opts=opts)

    calls = {}
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)

    def fake_aligned(ctx, url, part, workdir, **kw):
        calls.update(kw)
        return raw, 1200.0, 1260.0

    _patch_run_job_wiring(monkeypatch, tmp_path, fake_aligned)
    ctx, logs = _ctx()

    eng.run_job(job, ctx)

    assert "format_id" not in calls
    assert not any("Quality:" in line for line in logs)


def test_run_job_no_formats_with_explicit_quality_logs_notice(monkeypatch, tmp_path):
    src = eng.SourceInfo(
        url="https://www.twitch.tv/videos/1",
        id="1",
        title="Test Stream",
        uploader="Streamer",
        duration=3600.0,
        date="2026-01-01",
        twitch_vod_id="1",
        formats=[],
    )
    opts = eng.JobOptions(
        cut_text="0:20:00 - 0:21:00",
        out_dir=str(tmp_path / "out"),
        strategy="sections",
        quality="720p",
    )
    job = eng.Job(source=src, opts=opts)

    calls = {}
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)

    def fake_aligned(ctx, url, part, workdir, **kw):
        calls.update(kw)
        return raw, 1200.0, 1260.0

    _patch_run_job_wiring(monkeypatch, tmp_path, fake_aligned)
    ctx, logs = _ctx()

    eng.run_job(job, ctx)

    assert "format_id" not in calls
    assert any("Quality: this video offers no choice, using the best one." in line for line in logs)


# --- 5. workdir naming by quality --- #

def test_run_job_workdir_naming_by_quality(monkeypatch, tmp_path):
    formats = eng.parse_formats(load_fixture(FIXTURE_SHORT).get("formats"))
    workdirs = []
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)

    def fake_full(ctx, url, workdir, threads, **kw):
        workdirs.append(workdir.name)
        return raw

    _patch_run_job_wiring(monkeypatch, tmp_path, lambda *a, **k: None, download_fake=fake_full)
    monkeypatch.setattr(eng, "split_copy", lambda ctx, full, parts, duration, container, workdir: {1: (raw, 0, 100)})

    def run_with(quality, fmts):
        src = eng.SourceInfo(
            url="https://www.twitch.tv/videos/1",
            id="1",
            title="T",
            uploader="Streamer",
            duration=3600.0,
            date="2026-01-01",
            twitch_vod_id="1",
            formats=fmts,
        )
        opts = eng.JobOptions(
            cut_text="0:00:00 - 0:01:00",
            out_dir=str(tmp_path / "out"),
            strategy="full",
            quality=quality,
        )
        ctx, _ = _ctx()
        eng.run_job(eng.Job(source=src, opts=opts), ctx)

    run_with("720p", formats)
    run_with("480p", formats)
    run_with("best", [])

    assert len(workdirs) == 3
    assert workdirs[0] == ".luckytwitch_1_720p60"
    assert workdirs[1] == ".luckytwitch_1_480p"
    assert workdirs[2] == ".luckytwitch_1"


def test_run_job_generic_source_cuts(monkeypatch, tmp_path):
    from core.providers import GenericProvider
    prov = GenericProvider("youtube")
    src = eng.SourceInfo(
        url="https://www.youtube.com/watch?v=generic123",
        id="generic123",
        title="Generic Video",
        uploader="YouTuber",
        duration=600.0,
        date="2026-01-01",
        twitch_vod_id=None,
        formats=[],
        site="youtube",
        provider=prov,
    )
    opts = eng.JobOptions(
        cut_text="0:00:10 - 0:00:30 ; 0:01:00 - 0:02:00",
        out_dir=str(tmp_path / "out"),
        strategy="sections",
        quality="best",
        cookies_browser="firefox",
    )
    job = eng.Job(source=src, opts=opts)

    sec_calls = []
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)

    def fake_sec(ctx, url, part, workdir, threads, exact, **kw):
        sec_calls.append((part.start, part.end, kw))
        return raw

    _patch_run_job_wiring(monkeypatch, tmp_path, lambda *a, **k: None)
    monkeypatch.setattr(eng, "download_section", fake_sec)

    ctx, logs = _ctx()
    results = eng.run_job(job, ctx)

    assert len(results) == 2
    assert len(sec_calls) == 2
    assert sec_calls[0][0] == 10.0 and sec_calls[0][1] == 30.0
    assert sec_calls[1][0] == 60.0 and sec_calls[1][1] == 120.0
    assert sec_calls[0][2].get("cookies_browser") == "firefox"

