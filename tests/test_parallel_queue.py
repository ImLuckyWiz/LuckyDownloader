"""Tests for Phase F3: parallel queue jobs and bandwidth limits."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import luckytwitch_engine as eng
from core.download import download_full, download_section, run_ytdlp
from core.job import Job, JobOptions
from core.source_info import SourceInfo
from qt_ui.bridge import Bridge
from qt_ui.queue_model import QueueModel
from qt_ui.queue_runner import QueueRunner


def test_job_options_rate_limit_default():
    opts = JobOptions(cut_text="0-10", out_dir="out")
    assert opts.rate_limit == ""


def test_run_ytdlp_forwards_rate_limit(monkeypatch):
    recorded = []
    monkeypatch.setattr(eng, "find_tool", lambda n: "yt-dlp")

    class FakeProc:
        def __init__(self, cmd, **kw):
            self.cmd = cmd
            self.stdout = iter([])
            self.returncode = 0
        def wait(self):
            return 0
        def poll(self):
            return 0

    monkeypatch.setattr(eng.subprocess, "Popen", lambda cmd, **kw: (recorded.append(cmd), FakeProc(cmd))[1])
    ctx = eng.Ctx()
    run_ytdlp(ctx, ["https://twitch.tv/videos/123"], threads=4, rate_limit="5M")

    assert len(recorded) == 1
    cmd = recorded[0]
    assert "--limit-rate" in cmd
    idx = cmd.index("--limit-rate")
    assert cmd[idx + 1] == "5M"


def test_download_full_forwards_rate_limit(monkeypatch, tmp_path: Path):
    recorded_kw = {}

    def fake_ytdlp(ctx, args, threads, **kw):
        recorded_kw.update(kw)
        out_f = tmp_path / "full.mp4"
        out_f.write_bytes(b"x" * 1024)

    monkeypatch.setattr(eng, "run_ytdlp", fake_ytdlp)
    ctx = eng.Ctx()
    download_full(ctx, "https://twitch.tv/videos/123", tmp_path, threads=4, rate_limit="2M")
    assert recorded_kw.get("rate_limit") == "2M"


def test_download_section_forwards_rate_limit(monkeypatch, tmp_path: Path):
    recorded_kw = {}

    def fake_ytdlp(ctx, args, threads, **kw):
        recorded_kw.update(kw)
        part_dir = tmp_path / "part1"
        part_dir.mkdir(parents=True, exist_ok=True)
        out_f = part_dir / "part.mp4"
        out_f.write_bytes(b"x" * 5000)

    monkeypatch.setattr(eng, "run_ytdlp", fake_ytdlp)
    ctx = eng.Ctx()
    part = eng.Part(index=1, start=10.0, end=20.0)
    download_section(ctx, "https://twitch.tv/videos/123", part, tmp_path, threads=4, exact=False, rate_limit="10M")
    assert recorded_kw.get("rate_limit") == "10M"


def test_queue_runner_parallel_execution(qtbot):
    bridge = Bridge()
    runner = QueueRunner(bridge, max_concurrent=2)
    model = QueueModel()
    bridge.item.connect(model.set_status)

    concurrent_count = [0]
    max_concurrent_seen = [0]
    done_jobs = []
    lock = threading.Lock()

    def fake_run(job, ctx):
        with lock:
            concurrent_count[0] += 1
            if concurrent_count[0] > max_concurrent_seen[0]:
                max_concurrent_seen[0] = concurrent_count[0]
        time.sleep(0.04)
        with lock:
            concurrent_count[0] -= 1
            done_jobs.append(job)
        return [Path("file.mp4")]

    import qt_ui.queue_runner as qr_mod
    orig_run = qr_mod.run_job
    qr_mod.run_job = fake_run
    try:
        model.add("j1", "Job 1", 1, "auto")
        model.add("j2", "Job 2", 1, "auto")
        model.add("j3", "Job 3", 1, "auto")

        with qtbot.waitSignal(bridge.queue_done, timeout=5000):
            runner.start(model.items, model=model, max_concurrent=2)

        assert len(done_jobs) == 3
        assert max_concurrent_seen[0] >= 2
    finally:
        qr_mod.run_job = orig_run


def test_queue_runner_cancel_single_job(qtbot):
    bridge = Bridge()
    runner = QueueRunner(bridge, max_concurrent=2)
    model = QueueModel()
    bridge.item.connect(model.set_status)

    started_events = {1: threading.Event(), 2: threading.Event()}
    finish_events = {1: threading.Event(), 2: threading.Event()}
    results = {}

    def fake_run(job_id, ctx):
        started_events[job_id].set()
        while not finish_events[job_id].is_set():
            if ctx.cancelled:
                results[job_id] = "cancelled"
                raise eng.Cancelled()
            time.sleep(0.01)
        results[job_id] = "done"
        return [Path("ok.mp4")]

    import qt_ui.queue_runner as qr_mod
    orig_run = qr_mod.run_job
    qr_mod.run_job = fake_run

    try:
        it1 = model.add(1, "Job 1", 1, "auto")
        it2 = model.add(2, "Job 2", 1, "auto")

        runner.start(model.items, model=model, max_concurrent=2)
        assert started_events[1].wait(3.0)
        assert started_events[2].wait(3.0)

        # Allow worker thread a brief tick to store ctx in runner.active_contexts
        qtbot.waitUntil(lambda: it1.iid in runner.active_contexts, timeout=2000)

        # Cancel ONLY job 1
        assert runner.cancel(it1.iid)

        # Let job 2 complete normally
        finish_events[2].set()

        qtbot.waitUntil(lambda: results.get(1) == "cancelled" and results.get(2) == "done", timeout=5000)
        runner.worker.join(5.0)
    finally:
        qr_mod.run_job = orig_run


def test_download_full_forwards_cookies_browser(monkeypatch, tmp_path: Path):
    import luckytwitch_engine as eng
    from core.download import download_full
    recorded_kw = {}

    def fake_ytdlp(ctx, args, threads, **kw):
        recorded_kw.update(kw)
        out_f = tmp_path / "full.mp4"
        out_f.write_bytes(b"x" * 1024)

    monkeypatch.setattr(eng, "run_ytdlp", fake_ytdlp)
    ctx = eng.Ctx()
    download_full(ctx, "https://youtube.com/watch?v=123", tmp_path, threads=4, cookies_browser="firefox")
    assert recorded_kw.get("cookies_browser") == "firefox"


def test_run_ytdlp_appends_cookies_flag(monkeypatch, tmp_path: Path):
    from core.download import run_ytdlp
    from core.runtime import Ctx
    captured_cmd = []

    class FakeProc:
        returncode = 0
        stdout = []
        def wait(self): pass

    def fake_popen(cmd, *args, **kwargs):
        captured_cmd.extend(cmd)
        return FakeProc()

    monkeypatch.setattr("core.download.find_tool", lambda name: "fake_ytdlp")
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    ctx = Ctx()
    run_ytdlp(ctx, ["https://youtube.com/watch?v=123"], threads=2, cookies_browser="chrome")
    assert "--cookies-from-browser" in captured_cmd
    idx = captured_cmd.index("--cookies-from-browser")
    assert captured_cmd[idx + 1] == "chrome"
