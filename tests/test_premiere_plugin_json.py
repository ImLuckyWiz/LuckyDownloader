"""The .markers.json for the Premiere plugin, and how it sits next to the plain .markers.xml.

Regenerate the shared sample (also read by the plugin's tests) with:  python tests/test_premiere_plugin_json.py
"""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import luckytwitch_engine as eng  # noqa: E402
from luckytwitch_engine import Chapter, GameSegment, premiere_markers_json  # noqa: E402

SAMPLE = Path(__file__).parent / "fixtures" / "markers_sample.json"


def _src(segments=()):
    return eng.SourceInfo(
        url="https://www.twitch.tv/videos/1", id="1", title="Big stream", uploader="Streamer",
        duration=26264.851, date="2026-01-01", twitch_vod_id="1", segments=list(segments),
    )


def _clip(cid="c1", title="Funny moment", views=120, end=1230.0, duration=20.0):
    return {"id": cid, "title": title, "creator_name": "bob", "view_count": views, "duration": duration,
            "vod_offset": end, "url": f"https://clips.twitch.tv/{cid}"}


def _sample_text() -> str:
    clip = _clip()
    chapters = [
        Chapter(7, 30, "Funny moment (bob, 120 views)", views=120, clips=[clip]),
        Chapter(0, 50, "Just Chatting", kind="game"),
        Chapter(50, 70, "Resident Evil 2", kind="game"),
    ]
    return premiere_markers_json("Streamer - 2026-01-01 - 1 - part1", chapters, 70.0, 29.97, _src(), 1200.0, 1270.0)


# --------------------------------------------------------------------------- the writer
def test_json_has_format_version_and_the_basics():
    data = json.loads(_sample_text())
    assert data["format"] == "luckytwitch-markers"
    assert data["version"] == 1
    assert data["fps"] == 29.97 and data["duration"] == 70.0
    assert data["part"] == {"start": 1200.0, "end": 1270.0}
    assert data["source"]["streamer"] == "Streamer" and data["source"]["vod_id"] == "1"


def test_markers_keep_kind_and_the_numbers_behind_them():
    markers = json.loads(_sample_text())["markers"]
    assert [m["kind"] for m in markers] == ["game", "clip", "game"]  # sorted by start time
    game, clip = markers[0], markers[1]
    assert game["game"] == "Just Chatting" and game["name"] == "Just Chatting"  # no "GAME:" prefix in the JSON
    assert clip["views"] == 120 and clip["start"] == 7 and clip["end"] == 30
    assert clip["comment"] == "bob · 120 views · https://clips.twitch.tv/c1"
    assert clip["clips"][0] == {
        "id": "c1", "title": "Funny moment", "creator": "bob", "views": 120, "duration": 20.0,
        "url": "https://clips.twitch.tv/c1",
    }


def test_game_and_clip_with_same_start_are_ordered_games_first():
    chs = [Chapter(5, 9, "clip", clips=[_clip()]), Chapter(5, 100, "Game", kind="game")]
    assert [m["kind"] for m in json.loads(premiere_markers_json("p", chs, 100, 30))["markers"]] == ["clip", "game"]


def test_non_ascii_titles_are_kept_as_they_are():
    chs = [Chapter(0, 10, "Ōkami: 大神 🎮", kind="game")]
    text = premiere_markers_json("p", chs, 10, 30)
    assert "Ōkami: 大神 🎮" in text  # not \\u escaped
    assert json.loads(text)["markers"][0]["name"] == "Ōkami: 大神 🎮"


def test_source_is_optional():
    data = json.loads(premiere_markers_json("p", [], 10, 30))
    assert "source" not in data and data["markers"] == [] and data["part"] == {"start": 0.0, "end": 10.0}


def test_source_fallback_to_id_when_twitch_vod_id_missing():
    src = eng.SourceInfo(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", id="dQw4w9WgXcQ", title="Video", uploader="Creator",
        duration=100.0, date="2026-01-01", twitch_vod_id=None,
    )
    data = json.loads(premiere_markers_json("p", [], 10, 30, src))
    assert data["source"]["vod_id"] == "dQw4w9WgXcQ"


def test_the_shared_sample_matches_what_the_app_writes():
    # the plugin's tests read this same file, so if the format changes both sides notice
    assert SAMPLE.read_text(encoding="utf-8") == _sample_text(), (
        "tests/fixtures/markers_sample.json is out of date: run  python tests/test_premiere_plugin_json.py")


# --------------------------------------------------------------------------- how run_job writes the files
GAMES = [GameSegment(0, 1250, "Just Chatting"), GameSegment(1250, 26264, "Resident Evil 2")]


def _run(monkeypatch, tmp_path, **flags):
    """Run a one-part job (1200 s -> 1270 s of the VOD, one clip and two games inside) with the given options."""
    monkeypatch.setattr(eng, "find_tool", lambda n: "/bin/true")
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)
    monkeypatch.setattr(eng, "download_section_aligned", lambda ctx, url, p, wd: (raw, 1200.0, 1270.0))
    monkeypatch.setattr(eng, "probe_video", lambda path: (29.97, 1920, 1080))

    def fake_finalize(ctx, f, stem, container, chapters, tags, total, copy=False):
        stem.parent.mkdir(parents=True, exist_ok=True)
        return stem.with_suffix(".mp4")

    monkeypatch.setattr(eng, "finalize_part", fake_finalize)
    opts = eng.JobOptions(cut_text="0:20:03 - 0:21:03", out_dir=str(tmp_path / "out"), strategy="sections", **flags)
    opts = replace(opts, clip_filter=eng.ClipFilter(pad_before=3))
    job = eng.Job(source=_src(GAMES), opts=opts, clips=[_clip()])
    logs = []
    (dest,) = eng.run_job(job, eng.Ctx(log=logs.append))
    return dest, logs


def _files(dest):
    return dest.with_name(dest.stem + ".markers.xml"), dest.with_name(dest.stem + ".markers.json")


def test_plugin_option_writes_only_the_json(monkeypatch, tmp_path):
    dest, logs = _run(monkeypatch, tmp_path, premiere_plugin=True)
    xml, js = _files(dest)
    assert js.exists() and not xml.exists()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert [m["kind"] for m in data["markers"]] == ["clip"]  # no game markers asked for
    assert data["markers"][0]["start"] == 7 and data["markers"][0]["end"] == 30  # relative to the part
    assert data["fps"] == 29.97 and data["part"] == {"start": 1200.0, "end": 1270.0}
    assert any(".markers.json" in m and "Premiere plugin" in m for m in logs)


def test_xml_option_still_writes_only_the_xml(monkeypatch, tmp_path):
    dest, _ = _run(monkeypatch, tmp_path, premiere_xml=True)
    xml, js = _files(dest)
    assert xml.exists() and not js.exists()
    assert "<marker>" in xml.read_text(encoding="utf-8")


def test_both_options_write_both_files(monkeypatch, tmp_path):
    dest, _ = _run(monkeypatch, tmp_path, premiere_xml=True, premiere_plugin=True, game_markers=True)
    xml, js = _files(dest)
    assert xml.exists() and js.exists()
    xml_text = xml.read_text(encoding="utf-8")
    assert "GAME: Just Chatting" in xml_text and "GAME: Resident Evil 2" in xml_text
    kinds = [m["kind"] for m in json.loads(js.read_text(encoding="utf-8"))["markers"]]
    assert kinds == ["game", "clip", "game"]  # game starts at 0, clip at 7, second game at 50


def test_game_markers_alone_keep_making_the_xml_as_before(monkeypatch, tmp_path):
    dest, _ = _run(monkeypatch, tmp_path, game_markers=True)
    xml, js = _files(dest)
    assert xml.exists() and not js.exists()
    text = xml.read_text(encoding="utf-8")
    assert "GAME: Just Chatting" in text and "Funny moment" not in text  # games only, as in v1.6.0


def test_plugin_plus_game_markers_puts_the_games_in_the_json_only(monkeypatch, tmp_path):
    dest, _ = _run(monkeypatch, tmp_path, premiere_plugin=True, game_markers=True)
    xml, js = _files(dest)
    assert js.exists() and not xml.exists()
    games = [m for m in json.loads(js.read_text(encoding="utf-8"))["markers"] if m["kind"] == "game"]
    assert [(g["game"], g["start"], g["end"]) for g in games] == [("Just Chatting", 0, 50), ("Resident Evil 2", 50, 70)]


def test_nothing_to_mark_writes_no_json(monkeypatch, tmp_path):
    monkeypatch.setattr(eng, "find_tool", lambda n: "/bin/true")
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x" * 5000)
    monkeypatch.setattr(eng, "download_section_aligned", lambda ctx, url, p, wd: (raw, 1200.0, 1270.0))
    monkeypatch.setattr(eng, "finalize_part", lambda ctx, f, stem, *a, **k: (stem.parent.mkdir(parents=True, exist_ok=True), stem.with_suffix(".mp4"))[1])
    opts = eng.JobOptions(cut_text="0:20:03 - 0:21:03", out_dir=str(tmp_path / "out"), strategy="sections", premiere_plugin=True)
    (dest,) = eng.run_job(eng.Job(source=_src(), opts=opts, clips=[]), eng.Ctx(log=lambda m: None))
    assert not any(dest.parent.glob("*.markers.*"))


def test_plugin_option_is_off_by_default():
    assert eng.JobOptions(cut_text="", out_dir="x").premiere_plugin is False




def test_markers_json_includes_preferences_when_provided():
    prefs = {"pad_before": 3.0, "pad_after": 4.0}
    text = premiere_markers_json("p", [], 10.0, 30.0, preferences=prefs)
    data = json.loads(text)
    assert data.get("preferences") == prefs


def test_run_job_markers_json_avoids_double_padding(monkeypatch, tmp_path):
    """F-02: run_job() bakes pad_before/pad_after into markers[] and writes 0.0 in preferences."""
    from core.finalize import PipelineDeps, run_job
    from core.job import ClipFilter, Job, JobOptions
    from core.runtime import Ctx
    from core.source_info import SourceInfo

    monkeypatch.setattr("core.finalize.check_disk_space", lambda *a, **kw: None)
    dummy_in = tmp_path / "in.mp4"
    dummy_in.write_bytes(b"0" * 1024)

    def fake_fin(ctx, src_file, dest_stem, container, chs, tags, total, copy=False):
        dest = dest_stem.with_suffix(f".{container}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"1" * 1024)
        return dest

    deps = PipelineDeps(
        find_tool=lambda name: "ffmpeg",
        download_full=lambda *a, **kw: dummy_in,
        finalize_part=fake_fin,
        load_muted=lambda ctx, job: [],
    )
    src = SourceInfo(
        url="https://twitch.tv/videos/4242",
        id="4242",
        title="Padded Stream",
        date="2026-01-01",
        duration=120.0,
        uploader="Tester",
    )
    clips = [{"title": "Clip1", "vod_offset": 30.0, "duration": 10.0, "view_count": 50}]
    opts = JobOptions(
        cut_text="",
        out_dir=str(tmp_path),
        strategy="full",
        chapters=True,
        premiere_plugin=True,
        clip_filter=ClipFilter(pad_before=3.0, pad_after=4.0),
    )
    res = run_job(Job(source=src, opts=opts, clips=clips), Ctx(log=lambda m: None), deps=deps)
    mj = res[0].with_suffix(".markers.json")
    data = json.loads(mj.read_text(encoding="utf-8"))
    assert data["markers"][0]["start"] == pytest.approx(17.0)
    assert data["markers"][0]["end"] == pytest.approx(34.0)
    assert data["preferences"] == {"pad_before": 0.0, "pad_after": 0.0}

if __name__ == "__main__":
    SAMPLE.write_text(_sample_text(), encoding="utf-8")
    print("wrote", SAMPLE)
