"""Chat download (TwitchDownloaderCLI wrapper) and game / category markers for Premiere Pro."""

import stat
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

import luckytwitch_engine as eng
from luckytwitch_engine import (
    Chapter,
    Cancelled,
    Ctx,
    EngineError,
    GameSegment,
    chapters_for_part,
    chat_command,
    download_chat,
    game_chapters,
    parse_tdcli_status,
    pick_tdcli_asset,
    premiere_markers_xml,
    tdcli_error,
)

# Release file names as listed by GitHub (the picker only relies on keywords, so renames do not matter much).
ASSETS = [
    "TwitchDownloaderCLI-1.56.5-LinuxAlpine-x64.zip",
    "TwitchDownloaderCLI-1.56.5-LinuxArm.zip",
    "TwitchDownloaderCLI-1.56.5-Linux-x64.zip",
    "TwitchDownloaderCLI-1.56.5-MacOS-x64.zip",
    "TwitchDownloaderCLI-1.56.5-MacOSArm64.zip",
    "TwitchDownloaderCLI-1.56.5-Windows-x64.zip",
    "TwitchDownloaderGUI-1.56.5-Windows-x64.zip",
    "TwitchDownloaderCLI-1.56.5-Windows-x64.zip.sha256",
]


# --------------------------------------------------------------------------- picking the right download
@pytest.mark.parametrize(
    "plat, machine, expected",
    [
        ("win32", "AMD64", "TwitchDownloaderCLI-1.56.5-Windows-x64.zip"),
        ("win32", "ARM64", "TwitchDownloaderCLI-1.56.5-Windows-x64.zip"),  # x64 build runs emulated
        ("darwin", "arm64", "TwitchDownloaderCLI-1.56.5-MacOSArm64.zip"),
        ("darwin", "x86_64", "TwitchDownloaderCLI-1.56.5-MacOS-x64.zip"),
        ("linux", "x86_64", "TwitchDownloaderCLI-1.56.5-Linux-x64.zip"),
        ("linux", "aarch64", "TwitchDownloaderCLI-1.56.5-LinuxArm.zip"),
    ],
)
def test_pick_asset_per_system(plat, machine, expected):
    assert pick_tdcli_asset(ASSETS, plat, machine) == expected


def test_pick_asset_none_when_nothing_fits():
    assert pick_tdcli_asset(["TwitchDownloaderCLI-1.56.5-Windows-x64.zip"], "darwin", "arm64") is None
    assert pick_tdcli_asset([], "win32", "AMD64") is None


# --------------------------------------------------------------------------- reading its output
@pytest.mark.parametrize(
    "line, phase, frac",
    [
        ("[STATUS] - Downloading 0%", "Downloading", 0.0),
        ("[STATUS] - Downloading 100%", "Downloading", 0.85),
        ("[STATUS] - Backfilling Commenter Info 100%", "Backfilling Commenter Info", 0.98),
        ("[STATUS] - Writing Output File", "Writing Output File", 0.98),
        ("[STATUS] - Fetching Video Info [1/1]", "Fetching Video Info", None),
        ("[STATUS] - Downloading 100% [2/4]", "Downloading", 0.85),
    ],
)
def test_parse_status_lines(line, phase, frac):
    got_phase, got_frac = parse_tdcli_status(line)
    assert got_phase == phase
    assert got_frac == pytest.approx(frac) if frac is not None else got_frac is None


def test_parse_status_ignores_other_lines():
    assert parse_tdcli_status("TwitchDownloaderCLI 1.56.5 Copyright (c) lay295 and contributors") is None
    assert parse_tdcli_status("") is None


def test_progress_never_goes_backwards_within_the_phases():
    fracs = [parse_tdcli_status(f"[STATUS] - Downloading {p}%")[1] for p in (0, 50, 100)]
    assert fracs == sorted(fracs)
    assert fracs[-1] <= parse_tdcli_status("[STATUS] - Backfilling Commenter Info 0%")[1]


def test_error_text_from_a_real_stack_trace():
    trace = [
        "Unhandled exception. System.AggregateException: One or more errors occurred. (Invalid VOD, deleted/expired VOD possibly?)",
        " ---> System.NullReferenceException: Invalid VOD, deleted/expired VOD possibly?",
        "   at TwitchDownloaderCore.ChatDownloader.InitChatRoot(DownloadType downloadType) in ChatDownloader.cs:line 375",
    ]
    assert tdcli_error(trace) == "Invalid VOD, deleted/expired VOD possibly?"


def test_error_text_fallbacks():
    assert tdcli_error(["[ERROR] - Something broke"]) == "Something broke"
    assert tdcli_error(["Unhandled exception. System.IO.IOException: disk full"]).endswith("disk full")
    assert tdcli_error(["a", "b", "c", "d"]) == "b | c | d"
    assert tdcli_error([]) == "no details"


# --------------------------------------------------------------------------- the command line
def test_chat_command_covers_the_part_in_whole_seconds(tmp_path):
    cmd = chat_command("tdcli", "2888990596", 3600.0, 3720.4, tmp_path / "a.chat.json", False, tmp_path / "cache")
    assert cmd[:4] == ["tdcli", "chatdownload", "--id", "2888990596"]
    assert cmd[cmd.index("-b") + 1] == "3600s"
    assert cmd[cmd.index("-e") + 1] == "3721s"  # rounded up so the last second of chat is not lost
    assert cmd[cmd.index("--collision") + 1] == "Overwrite"  # a prompt would hang the queue
    assert "--banner=false" in cmd and "--embed-images" not in cmd
    assert cmd[cmd.index("-o") + 1].endswith("a.chat.json")


def test_chat_command_embed_flag(tmp_path):
    assert "--embed-images" in chat_command("t", "1", 0, 10, tmp_path / "x.json", True, tmp_path)


# --------------------------------------------------------------------------- running it (fake CLI)
posix_only = pytest.mark.skipif(False, reason="")


def fake_cli(tmp_path: Path, body: str) -> str:
    """A script that behaves like TwitchDownloaderCLI: `body` runs with `out` = the -o argument."""
    if sys.platform == "win32":
        py_file = tmp_path / "fake_tdcli.py"
        py_file.write_text(
            f"import sys, time\nargs = sys.argv[1:]\nout = args[args.index('-o') + 1]\n{body}\n",
            encoding="utf-8",
        )
        cmd_file = tmp_path / "fake_tdcli.cmd"
        cmd_file.write_text(
            f'@"{sys.executable}" "%~dp0fake_tdcli.py" %*\n',
            encoding="utf-8",
        )
        return str(cmd_file)
    script = tmp_path / "fake_tdcli"
    script.write_text(
        f"#!{sys.executable}\nimport sys, time\nargs = sys.argv[1:]\nout = args[args.index('-o') + 1]\n{body}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def make_ctx():
    reports, logs = [], []
    ctx = Ctx(log=logs.append, progress=lambda f, t: reports.append((f, t)))
    ctx.stage(0.0, 1.0, "Chat")
    return ctx, reports, logs


@posix_only
def test_download_chat_success(tmp_path):
    cli = fake_cli(tmp_path, (
        "print('[STATUS] - Downloading 50%', flush=True)\n"
        "print('[STATUS] - Downloading 100%', flush=True)\n"
        "print('[STATUS] - Writing Output File', flush=True)\n"
        "open(out, 'w').write('{}')\n"
    ))
    ctx, reports, _ = make_ctx()
    dest = tmp_path / "videos" / "part1.chat.json"
    got = download_chat(ctx, cli, "123", 100, 200, dest, False, tmp_path / "cache")
    assert got == dest and dest.read_text() == "{}"
    fracs = [f for f, _ in reports if f is not None and f >= 0]
    assert max(fracs) == pytest.approx(0.98)


@posix_only
def test_download_chat_does_not_overwrite_an_existing_file(tmp_path):
    cli = fake_cli(tmp_path, "open(out, 'w').write('new')")
    ctx, _, _ = make_ctx()
    dest = tmp_path / "part1.chat.json"
    dest.write_text("old")
    got = download_chat(ctx, cli, "123", 0, 10, dest, False, tmp_path / "cache")
    assert dest.read_text() == "old" and got.name == "part1.chat (2).json" and got.read_text() == "new"


@posix_only
def test_download_chat_failure_reports_the_reason_and_removes_the_file(tmp_path):
    cli = fake_cli(tmp_path, (
        "open(out, 'w').close()\n"  # like the real tool: a 0-byte file appears before it fails
        "print('Unhandled exception. System.AggregateException: x')\n"
        "print(' ---> System.NullReferenceException: Invalid VOD, deleted/expired VOD possibly?')\n"
        "sys.exit(1)\n"
    ))
    ctx, _, _ = make_ctx()
    dest = tmp_path / "part1.chat.json"
    with pytest.raises(EngineError) as e:
        download_chat(ctx, cli, "1", 0, 10, dest, False, tmp_path / "cache")
    assert "Invalid VOD" in str(e.value)
    assert not dest.exists()


@posix_only
def test_download_chat_empty_output_is_an_error(tmp_path):
    cli = fake_cli(tmp_path, "open(out, 'w').close()")
    ctx, _, _ = make_ctx()
    with pytest.raises(EngineError):
        download_chat(ctx, cli, "1", 0, 10, tmp_path / "p.chat.json", False, tmp_path / "cache")
    assert not (tmp_path / "p.chat.json").exists()


@posix_only
def test_download_chat_cancel_stops_the_process_and_removes_the_file(tmp_path):
    cli = fake_cli(tmp_path, (
        "open(out, 'w').close()\n"
        "print('[STATUS] - Downloading 10%', flush=True)\n"
        "time.sleep(60)\n"
    ))
    ctx, _, _ = make_ctx()
    dest = tmp_path / "p.chat.json"
    threading.Timer(1.0, ctx.cancel).start()
    t0 = time.monotonic()
    with pytest.raises(Cancelled):
        download_chat(ctx, cli, "1", 0, 10, dest, False, tmp_path / "cache")
    assert time.monotonic() - t0 < 20
    assert not dest.exists()


def test_download_chat_missing_program(tmp_path):
    ctx, _, _ = make_ctx()
    with pytest.raises(EngineError):
        download_chat(ctx, str(tmp_path / "nope"), "1", 0, 10, tmp_path / "p.chat.json", False, tmp_path / "c")


# --------------------------------------------------------------------------- unzipping the CLI
def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_extract_flat_zip(tmp_path):
    z = make_zip(tmp_path / "a.zip", {eng._TDCLI_EXE: b"exe", "license.txt": b"MIT"})
    eng._extract_tdcli(z, tmp_path / "out")
    assert (tmp_path / "out" / eng._TDCLI_EXE).read_bytes() == b"exe"
    assert (tmp_path / "out" / "license.txt").read_bytes() == b"MIT"


def test_extract_zip_with_a_folder_and_extra_files(tmp_path):
    z = make_zip(tmp_path / "a.zip", {
        f"TwitchDownloaderCLI-1.56.5/{eng._TDCLI_EXE}": b"exe",
        "TwitchDownloaderCLI-1.56.5/lib/helper.dll": b"dll",
        "unrelated/readme.txt": b"skip me",
    })
    eng._extract_tdcli(z, tmp_path / "out")
    assert (tmp_path / "out" / eng._TDCLI_EXE).exists()
    assert (tmp_path / "out" / "lib" / "helper.dll").exists()
    assert not (tmp_path / "out" / "readme.txt").exists()


def test_extract_never_writes_outside_the_folder(tmp_path):
    z = make_zip(tmp_path / "a.zip", {eng._TDCLI_EXE: b"exe", "../evil.txt": b"x", "sub/../../evil2.txt": b"x"})
    eng._extract_tdcli(z, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "evil2.txt").exists()


def test_extract_without_the_program_is_an_error(tmp_path):
    z = make_zip(tmp_path / "a.zip", {"readme.txt": b"x"})
    with pytest.raises(EngineError):
        eng._extract_tdcli(z, tmp_path / "out")


# --------------------------------------------------------------------------- game markers
GAMES = [GameSegment(0, 3600, "Just Chatting"), GameSegment(3600, 9000, "Resident Evil 2"), GameSegment(9000, 9500, "")]


def _markers(xml: str):
    root = ET.fromstring(xml.replace("<!DOCTYPE xmeml>", ""))
    return [(m.findtext("name"), m.findtext("comment"), int(m.findtext("in")), int(m.findtext("out"))) for m in root.iter("marker")]


def test_game_chapters_keep_times_and_name_empty_categories():
    chs = game_chapters(GAMES)
    assert [(c.start, c.end, c.title, c.kind) for c in chs] == [
        (0, 3600, "Just Chatting", "game"),
        (3600, 9000, "Resident Evil 2", "game"),
        (9000, 9500, "(no category)", "game"),
    ]


def test_full_vod_gets_every_game_as_a_marker():
    chs = chapters_for_part(game_chapters(GAMES), 0, 9500)
    markers = _markers(premiere_markers_xml("vod", chs, 9500, 30))
    assert [m[0] for m in markers] == ["GAME: Just Chatting", "GAME: Resident Evil 2", "GAME: (no category)"]
    assert markers[0][2:] == (0, 3600 * 30) and markers[1][2:] == (3600 * 30, 9000 * 30)
    assert all(m[1] == "Game / category" for m in markers)


def test_part_gets_only_the_games_inside_it_with_part_relative_times():
    chs = chapters_for_part(game_chapters(GAMES), 3000, 4000)  # 50:00 -> 1:06:40, the game changes at 1:00:00
    assert [(c.title, c.start, c.end) for c in chs] == [("Just Chatting", 0, 600), ("Resident Evil 2", 600, 1000)]
    assert all(c.kind == "game" for c in chs)  # the kind survives the cut


def test_clip_markers_are_unchanged_and_mix_with_game_markers():
    clip = {"creator_name": "bob", "view_count": 7, "url": "https://clips.example/x"}
    chs = [Chapter(10, 20, "Funny clip", clips=[clip]), Chapter(0, 100, "Just Chatting", kind="game")]
    chs.sort(key=lambda c: (c.start, c.kind))
    markers = _markers(premiere_markers_xml("seq", chs, 100, 30))
    assert markers[0][0] == "GAME: Just Chatting"
    assert markers[1][0] == "Funny clip" and "bob" in markers[1][1] and "https://clips.example/x" in markers[1][1]


def test_game_names_are_escaped_in_the_xml():
    chs = [Chapter(0, 10, "Tom & <Jerry>", kind="game")]
    markers = _markers(premiere_markers_xml("s", chs, 10, 30))
    assert markers[0][0] == "GAME: Tom & <Jerry>"
