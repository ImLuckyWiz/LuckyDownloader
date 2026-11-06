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
    reporter.progress(1.0, "Complete")

    out, _ = capsys.readouterr()
    assert "Starting download" in out
    assert "[ 10%] Downloading segment 1/10" in out
    assert "[ 20%] Downloading segment 2/10" in out
    assert "[100%] Complete" in out

    # Quiet mode
    quiet_reporter = cli.ConsoleReporter(quiet=True)
    quiet_reporter.log("Secret log")
    quiet_reporter.progress(0.5, "Halfway")
    quiet_out, _ = capsys.readouterr()
    assert quiet_out == ""
