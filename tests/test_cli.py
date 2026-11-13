"""
Unit tests for the LuckyDownloader CLI (cli.py).
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

import cli
from core.errors import EngineError
from core.source_info import SourceInfo, VideoFormat


@pytest.fixture(autouse=True)
def _mock_cli_ensure_tools(monkeypatch):
    monkeypatch.setattr(cli, "ensure_tools", lambda *args, **kwargs: None)


def test_cli_does_not_import_pyside6():
    """Verify that importing cli.py never imports PySide6 or qt_ui into sys.modules."""
    code = (
        "import sys\n"
        "import cli\n"
        "assert 'PySide6' not in sys.modules, 'PySide6 was loaded!'\n"
        "assert 'qt_ui' not in sys.modules, 'qt_ui was loaded!'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, f"PySide6 or qt_ui was imported:\n{res.stderr}"


def test_cli_parser_defaults():
    """Verify default arguments of the CLI parser."""
    parser = cli.build_parser()
    args = parser.parse_args(["https://www.twitch.tv/videos/123456789"])

    assert args.url == "https://www.twitch.tv/videos/123456789"
    assert args.cuts == ""
    assert args.out == "./downloads"
    assert args.quality == "best"
    assert args.strategy == "auto"
    assert args.exact is False
    assert args.container == "mp4"
    assert args.audio_format == "m4a"
    assert args.chat is False
    assert args.chapters is False
    assert args.keep_full is False
    assert args.clean_title is True
    assert args.subfolders is True
    assert args.threads == 8
    assert args.name_template == ""
    assert args.dry_run is False


def test_cli_parser_custom_args():
    """Verify customized command line arguments."""
    parser = cli.build_parser()
    args = parser.parse_args([
        "https://www.twitch.tv/videos/123456789",
        "-c", "0:00:00 - 1:18:55 - end",
        "-o", "/custom/output",
        "-q", "720p60",
        "-s", "sections",
        "--exact",
        "--format", "mkv",
        "--chat",
        "--chat-format", "txt",
        "--chapters",
        "--keep-full",
        "--no-clean-title",
        "--no-subfolders",
        "--threads", "4",
        "--rate-limit", "10M",
        "--cookies-browser", "firefox",
        "--template", "{streamer} - {title} - {game} - part{n}",
        "--dry-run",
    ])

    assert args.cuts == "0:00:00 - 1:18:55 - end"
    assert args.out == "/custom/output"
    assert args.quality == "720p60"
    assert args.strategy == "sections"
    assert args.exact is True
    assert args.container == "mkv"
    assert args.chat is True
    assert args.chat_format == "txt"
    assert args.chapters is True
    assert args.keep_full is True
    assert args.clean_title is False
    assert args.subfolders is False
    assert args.threads == 4
    assert args.rate_limit == "10M"
    assert args.cookies_browser == "firefox"
    assert args.name_template == "{streamer} - {title} - {game} - part{n}"
    assert args.dry_run is True


def test_cli_no_args_shows_help(capsys):
    """Running without arguments should show help and return exit code 1."""
    ret = cli.main([])
    assert ret == 1
    out, err = capsys.readouterr()
    assert "usage:" in out


@patch("cli.get_source_info")
def test_cli_dry_run_execution(mock_get_source_info, capsys):
    """--dry-run should print video metadata and calculated parts without downloading."""
    mock_src = SourceInfo(
        url="https://www.twitch.tv/videos/123456789",
        id="123456789",
        title="Epic Speedrun Stream",
        uploader="LuckyStreamer",
        duration=7200.0,
        date="2026-11-06",
        formats=[VideoFormat(format_id="best", height=1080, fps=60.0, container="mp4")],
        site="twitch",
    )
    mock_get_source_info.return_value = mock_src

    ret = cli.main([
        "https://www.twitch.tv/videos/123456789",
        "-c", "0:00:00 - 1:18:55 - end",
        "--dry-run",
    ])

    assert ret == 0
    out, err = capsys.readouterr()
    assert "Epic Speedrun Stream" in out
    assert "LuckyStreamer" in out
    assert "2:00:00" in out
    assert "Part 1: 0:00:00 -> 1:18:55" in out
    assert "Part 2: 1:18:55 -> 2:00:00" in out
    assert "Dry run finished successfully" in out


@patch("cli.get_source_info")
def test_cli_engine_error_handling(mock_get_source_info, capsys):
    """EngineError should be caught cleanly and return exit code 2."""
    mock_get_source_info.side_effect = EngineError("This VOD is subscriber-only.")

    ret = cli.main(["https://www.twitch.tv/videos/999999"])
    assert ret == 2
    out, err = capsys.readouterr()
    assert "[LuckyDownloader ERROR]" in err
    assert "This VOD is subscriber-only." in err


@patch("cli.get_source_info")
def test_cli_invalid_cut_points(mock_get_source_info, capsys):
    """Invalid cut points (decreasing timestamps) should raise EngineError and exit with code 2."""
    mock_src = SourceInfo(
        url="https://www.twitch.tv/videos/123456789",
        id="123456789",
        title="Epic Stream",
        uploader="LuckyStreamer",
        duration=7200.0,
        date="2026-11-06",
        formats=[],
        site="twitch",
    )
    mock_get_source_info.return_value = mock_src

    ret = cli.main([
        "https://www.twitch.tv/videos/123456789",
        "-c", "0:30:00 - 0:10:00",
        "--dry-run",
    ])

    assert ret == 2
    out, err = capsys.readouterr()
    assert "[LuckyDownloader ERROR]" in err
    assert "Cut points must increase" in err


def test_console_reporter(capsys):
    """Test the ConsoleReporter output in quiet and normal modes."""
    # Normal mode
    reporter = cli.ConsoleReporter(quiet=False)
    reporter.is_tty = False  # Simulate Colab/CI log output
    reporter.log("Starting download")
    reporter.progress(0.1, "Downloading segment 1/10")
    reporter.progress(0.2, "Downloading segment 2/10")
    reporter.progress(-1.0, "Assembling video")
    reporter.progress(1.0, "Complete")

    out, _ = capsys.readouterr()
    assert "Starting download" in out
    assert "[ 10%] Downloading segment 1/10" in out
    assert "[ 20%] Downloading segment 2/10" in out
    assert "Assembling video ..." in out
    assert "[100%] Complete" in out

    # Quiet mode
    quiet_reporter = cli.ConsoleReporter(quiet=True)
    quiet_reporter.log("Secret log")
    quiet_reporter.progress(0.5, "Halfway")
    quiet_out, _ = capsys.readouterr()
    assert quiet_out == ""


@patch("cli.run_job")
@patch("cli.get_source_info")
def test_cli_template_passed_to_job(mock_get_source_info, mock_run_job):
    """Ensure --template sets both name_template and generic_name_template on JobOptions."""
    mock_src = SourceInfo(
        url="https://www.twitch.tv/videos/123456789",
        id="123456789",
        title="Epic Stream",
        uploader="LuckyStreamer",
        duration=7200.0,
        date="2026-11-06",
        formats=[],
        site="twitch",
    )
    mock_get_source_info.return_value = mock_src

    ret = cli.main([
        "https://www.twitch.tv/videos/123456789",
        "--template", "{streamer} - {title} - {game} - part{n}",
    ])

    assert ret == 0
    mock_run_job.assert_called_once()
    called_job = mock_run_job.call_args[0][0]
    assert called_job.opts.name_template == "{streamer} - {title} - {game} - part{n}"
    assert called_job.opts.generic_name_template == "{streamer} - {title} - {game} - part{n}"


@patch("cli.ensure_tools")
@patch("cli.get_source_info")
def test_cli_dry_run_skips_ensure_tools(mock_get_source_info, mock_ensure_tools):
    """--dry-run must not call ensure_tools()."""
    mock_get_source_info.return_value = SourceInfo(
        url="https://www.twitch.tv/videos/123456789",
        id="123456789",
        title="Dry Stream",
        uploader="Lucky",
        duration=3600.0,
        date="2026-11-06",
        formats=[],
        site="twitch",
    )
    ret = cli.main(["https://www.twitch.tv/videos/123456789", "--dry-run"])
    assert ret == 0
    mock_ensure_tools.assert_not_called()


@patch("cli.ensure_tools")
@patch("cli.make_client")
@patch("cli.run_job")
@patch("cli.get_source_info")
def test_cli_chapters_wires_make_client_and_new_flags(
    mock_get_source_info, mock_run_job, mock_make_client, mock_ensure_tools
):
    """--chapters should wire client=make_client() and forward new flags to JobOptions."""
    fake_client = MagicMock()
    mock_make_client.return_value = fake_client
    mock_get_source_info.return_value = SourceInfo(
        url="https://www.twitch.tv/videos/123456789",
        id="123456789",
        title="Chapter Stream",
        uploader="Lucky",
        duration=3600.0,
        date="2026-11-06",
        formats=[],
        site="twitch",
    )

    ret = cli.main([
        "https://www.twitch.tv/videos/123456789",
        "--chapters",
        "--download-archive", "archive.txt",
        "--premiere-xml",
        "--premiere-json",
        "--game-markers",
        "--muted-markers",
        "--chat-render",
        "--no-update-tools",
    ])
    assert ret == 0
    mock_ensure_tools.assert_called_once()
    assert mock_ensure_tools.call_args.kwargs["update_ytdlp"] is False
    called_job = mock_run_job.call_args[0][0]
    assert called_job.client is fake_client
    assert called_job.opts.chapters is True
    assert called_job.opts.download_archive == "archive.txt"
    assert called_job.opts.premiere_xml is True
    assert called_job.opts.premiere_plugin is True
    assert called_job.opts.game_markers is True
    assert called_job.opts.muted_markers is True
    assert called_job.opts.chat_render is True


@patch("cli.ensure_tools")
@patch("cli.split_copy")
@patch("cli._probe_duration", return_value=120.0)
def test_cli_cut_local_uses_split_copy(mock_probe, mock_split_copy, mock_ensure_tools, tmp_path):
    """cut-local should split a local file via split_copy and stage atomically."""
    src_video = tmp_path / "vod.mp4"
    src_video.write_bytes(b"fake-mp4")
    seg1 = tmp_path / "seg1.mp4"
    seg2 = tmp_path / "seg2.mp4"
    seg1.write_bytes(b"part1")
    seg2.write_bytes(b"part2")
    mock_split_copy.return_value = {1: (seg1, 0.0, 60.0), 2: (seg2, 60.0, 120.0)}

    out_dir = tmp_path / "out"
    ret = cli.main(["cut-local", str(src_video), "-c", "0:00-1:00-end", "-o", str(out_dir)])
    assert ret == 0
    mock_split_copy.assert_called_once()
    assert (out_dir / "vod - part1.mp4").read_bytes() == b"part1"
    assert (out_dir / "vod - part2.mp4").read_bytes() == b"part2"


@patch("cli.ensure_tools")
@patch("cli.run_job")
@patch("cli.get_source_info")
def test_cli_playlist_expansion(mock_get_source_info, mock_run_job, mock_ensure_tools, tmp_path):
    """PlaylistInfo should expand selected --items into individual run_job calls."""
    from core.source_info import PlaylistInfo, PlaylistItem

    mock_get_source_info.return_value = PlaylistInfo(
        id="PL1",
        title="My Playlist",
        url="https://www.youtube.com/playlist?list=PL1",
        uploader="Chan",
        entries=[
            PlaylistItem(id="v1", title="One", url="https://www.youtube.com/watch?v=v1", index=1),
            PlaylistItem(id="v2", title="Two", url="https://www.youtube.com/watch?v=v2", index=2),
        ],
    )
    ret = cli.main([
        "https://www.youtube.com/playlist?list=PL1",
        "--items", "2",
        "--download-archive", str(tmp_path / "arch.txt"),
        "-o", str(tmp_path),
    ])
    assert ret == 0
    mock_run_job.assert_called_once()
    assert mock_run_job.call_args[0][0].source.id == "v2"


def test_colab_transcribe_helpers(tmp_path):
    """tools/colab/transcribe.py should isolate chunk dirs per video and measure WAV duration accurately."""
    import wave
    from tools.colab import transcribe

    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    v1.write_bytes(b"")
    v2.write_bytes(b"")
    assert transcribe.video_chunks_dir(tmp_path, v1) != transcribe.video_chunks_dir(tmp_path, v2)

    wav_path = tmp_path / "test.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)  # 1.0 second
    assert transcribe.wav_duration(wav_path) == pytest.approx(1.0)
