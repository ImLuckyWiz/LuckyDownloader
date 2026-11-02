"""File and folder naming: safe_name, unique_path, part_stem, stream_dir."""

from pathlib import Path

import pytest

from luckytwitch_engine import (
    Ctx,
    GameSegment,
    JobOptions,
    Part,
    SourceInfo,
    clean_title,
    date_components,
    dominant_game,
    finalize_part,
    format_duration_tag,
    part_stem,
    safe_name,
    stream_dir,
    unique_path,
    VideoFormat,
)


def make_src(**kw):
    base = dict(url="https://www.twitch.tv/videos/123", id="v123", title="Big Stream", uploader="Streamer",
                duration=7200.0, date="2026-10-01", twitch_vod_id="123")
    base.update(kw)
    return SourceInfo(**base)


def make_opts(**kw):
    return JobOptions(cut_text="0:00 - end", out_dir="OUT", **kw)


# --------------------------------------------------------------------------- safe_name
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hello World", "Hello World"),
        ("a:b*c?d", "abcd"),
        ('He said "hi" <ok> | x/y\\z', "He said hi ok xyz"),
        ("  lots   of   space  ", "lots of space"),
        ("trailing dots...", "trailing dots"),
        (". leading dot", "leading dot"),
        ("Fun \U0001F602 stream", "Fun stream"),
        ("Ñandú – año", "Ñandú año"),
        ("keep (these) [brackets] - and-dashes", "keep (these) [brackets] - and-dashes"),
        ("???", ""),
    ],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


# --------------------------------------------------------------------------- unique_path
def test_unique_path_returns_the_same_path_when_free(tmp_path):
    p = tmp_path / "video.mp4"
    assert unique_path(p) == p


def test_unique_path_numbers_the_copies(tmp_path):
    p = tmp_path / "video.mp4"
    p.write_text("x")
    assert unique_path(p) == tmp_path / "video (2).mp4"
    (tmp_path / "video (2).mp4").write_text("x")
    assert unique_path(p) == tmp_path / "video (3).mp4"


# --------------------------------------------------------------------------- part_stem
def test_part_stem_default_template():
    stem = part_stem(make_src(), make_opts(), Part(1, 0, 600), 3)
    assert stem == "Streamer - 2026-10-01 - 123 - part1"


def test_part_stem_all_stream_tokens():
    opts = make_opts(name_template="{streamer}_{date}_{id}_{title}_{n}of{total}_{start}_{end}")
    stem = part_stem(make_src(), opts, Part(2, 3661, 7322), 5)
    assert stem == "Streamer_2026-10-01_123_Big Stream_2of5_01h01m01s_02h02m02s"


def test_part_stem_start_end_tags():
    opts = make_opts(name_template="{start}_{end}")
    assert part_stem(make_src(), opts, Part(1, 3661, 7322), 1) == "01h01m01s_02h02m02s"


def test_part_stem_uses_the_source_id_when_there_is_no_twitch_id():
    stem = part_stem(make_src(twitch_vod_id=None, id="abc"), make_opts(name_template="{id}"), Part(1, 0, 1), 1)
    assert stem == "abc"


def test_part_stem_unknown_token_survives_as_plain_text():
    # unknown {tokens} are kept by the template, then the braces are stripped by safe_name
    assert part_stem(make_src(), make_opts(name_template="{foo} x"), Part(1, 0, 1), 1) == "foo x"


@pytest.mark.parametrize("template", ["{n", "{0}"])
def test_part_stem_broken_template_falls_back(template):
    assert part_stem(make_src(), make_opts(name_template=template), Part(1, 0, 1), 1) == "123"
    assert part_stem(make_src(), make_opts(name_template=template), Part(1, 0, 1), 2) == "123 - part1"


def test_part_stem_omits_part_on_single_part():
    stem_single = part_stem(make_src(), make_opts(), Part(1, 0, 600), 1)
    assert stem_single == "Streamer - 2026-10-01 - 123"
    stem_multi = part_stem(make_src(), make_opts(), Part(1, 0, 600), 2)
    assert stem_multi == "Streamer - 2026-10-01 - 123 - part1"


def test_part_stem_empty_name_becomes_partN():
    stem = part_stem(make_src(title="", uploader="", date="", twitch_vod_id="9"),
                     make_opts(name_template="???"), Part(2, 0, 1), 2)
    assert stem == "part2"


CLIP = {"title": "Epic fail", "creator_name": "viewer1", "view_count": 12, "id": "ClipId", "duration": 29.6}


def test_part_stem_single_clip_uses_the_clip_template():
    opts = make_opts(clip_name_template="{clip_title} by {creator} ({views}) {clip_duration}s")
    assert part_stem(make_src(), opts, Part(1, 0, 1), 1, CLIP) == "Epic fail by viewer1 (12) 30s"


def test_part_stem_single_clip_can_use_vod_tokens_too():
    opts = make_opts(clip_name_template="{streamer} - {clip_title}")
    assert part_stem(make_src(), opts, Part(1, 0, 1), 1, CLIP) == "Streamer - Epic fail"


def test_part_stem_single_clip_name_is_truncated_to_150_chars():
    clip = {**CLIP, "title": "x" * 400}
    assert len(part_stem(make_src(), make_opts(), Part(1, 0, 1), 1, clip)) == 150


def test_part_stem_single_clip_empty_name_falls_back_to_the_clip_id():
    opts = make_opts(clip_name_template="???")
    assert part_stem(make_src(), opts, Part(1, 0, 1), 1, CLIP) == "clip ClipId"


def test_part_stem_single_clip_untitled():
    clip = {**CLIP, "title": ""}
    assert part_stem(make_src(), make_opts(), Part(1, 0, 1), 1, clip) == "Clip"


# --------------------------------------------------------------------------- stream_dir
def test_stream_dir_default_layout():
    assert stream_dir(make_src(), make_opts()) == Path("OUT") / "Streamer" / "2026-10-01 - Big Stream - 123"


def test_stream_dir_without_subfolders_is_the_output_folder():
    assert stream_dir(make_src(), make_opts(subfolders=False)) == Path("OUT")


def test_stream_dir_cleans_names():
    src = make_src(uploader="Str:eamer?", title="Big *Stream*")
    assert stream_dir(src, make_opts()) == Path("OUT") / "Streamer" / "2026-10-01 - Big Stream - 123"


def test_stream_dir_missing_streamer_becomes_vod():
    assert stream_dir(make_src(uploader=""), make_opts()).parts[-2] == "vod"


def test_stream_dir_broken_template_falls_back_to_date_and_id():
    assert stream_dir(make_src(), make_opts(folder_template="{")).name == "2026-10-01 - 123"


def test_stream_dir_long_names_are_truncated():
    src = make_src(uploader="u" * 200, title="t" * 300)
    p = stream_dir(src, make_opts())
    assert len(p.parts[-2]) == 60
    assert len(p.name) <= 100


# --------------------------------------------------------------------------- clean_title
def test_clean_title_removes_bot_commands_and_promos():
    raw = "🐍 Pretty face, tragic reactions. BIG ANNOUNCEMENT! 🐍 !gsupps !links !clash"
    assert clean_title(raw) == "Pretty face, tragic reactions. BIG ANNOUNCEMENT!"


def test_clean_title_removes_hashtags_and_trailing_separators():
    raw = "🔴 Chill stream | !discord !specs | #ad - "
    assert clean_title(raw) == "Chill stream"


def test_clean_title_keeps_normal_title_intact():
    raw = "Playing Elden Ring with friends! Having lots of fun."
    assert clean_title(raw) == "Playing Elden Ring with friends! Having lots of fun."


# --------------------------------------------------------------------------- finalize_part dot safety
def test_finalize_part_preserves_dots_in_title(tmp_path):
    src_file = tmp_path / "temp.mp4"
    src_file.write_text("video_data")
    dest_stem = tmp_path / "Vexoria - Pretty face tragic reactions. BIG ANNOUNCEMENT - part1"
    ctx = Ctx(log=lambda m: None, progress=lambda *a: None)
    out = finalize_part(ctx, src_file, dest_stem, "mp4", [], {}, 10.0, copy_instead_of_move=True)
    assert out.name == "Vexoria - Pretty face tragic reactions. BIG ANNOUNCEMENT - part1.mp4"


# --------------------------------------------------------------------------- {quality} token
def test_part_stem_quality_token():
    fmts = [
        VideoFormat("1080p60", 1080, 60, 6000, False, True),
        VideoFormat("720p60", 720, 60, 3000, False, False),
        VideoFormat("Audio_Only", 0, 0, 160, True, False),
    ]
    src_with_fmts = make_src(formats=fmts)
    src_no_fmts = make_src()

    opts_720 = make_opts(name_template="{streamer} - {id} - {quality} - part{n}", quality="720p")
    assert part_stem(src_with_fmts, opts_720, Part(1, 0, 60), 2) == "Streamer - 123 - 720p60 - part1"

    opts_audio = make_opts(name_template="{streamer} - {id} - {quality} - part{n}", quality="audio")
    assert part_stem(src_with_fmts, opts_audio, Part(1, 0, 60), 2) == "Streamer - 123 - audio - part1"

    # No formats in source -> {quality} is empty
    opts_no_fmts = make_opts(name_template="{streamer} - {id}{quality} - part{n}", quality="720p")
    assert part_stem(src_no_fmts, opts_no_fmts, Part(1, 0, 60), 2) == "Streamer - 123 - part1"

    # Old template without {quality} is unchanged
    opts_old = make_opts(name_template="{streamer} - {id} - part{n}", quality="720p")
    assert part_stem(src_with_fmts, opts_old, Part(1, 0, 60), 2) == "Streamer - 123 - part1"


# --------------------------------------------------------------------------- date_components & format_duration_tag
def test_date_components():
    assert date_components("2026-10-26") == ("2026", "10", "26")
    assert date_components("1999-01-05") == ("1999", "01", "05")
    assert date_components("") == ("", "", "")
    assert date_components(None) == ("", "", "")
    assert date_components("invalid-date") == ("", "", "")
    assert date_components("2026-10") == ("2026", "10", "")


def test_format_duration_tag():
    assert format_duration_tag(0) == "00h00m00s"
    assert format_duration_tag(59) == "00h00m59s"
    assert format_duration_tag(61) == "00h01m01s"
    assert format_duration_tag(3661) == "01h01m01s"
    assert format_duration_tag(7322.9) == "02h02m02s"


# --------------------------------------------------------------------------- dominant_game
def test_dominant_game():
    segs = [
        GameSegment(0, 1800, "Just Chatting"),
        GameSegment(1800, 5400, "Elden Ring"),
        GameSegment(5400, 7200, "Just Chatting"),
    ]
    # In range 0..1000: Just Chatting only
    assert dominant_game(segs, 0, 1000) == "Just Chatting"
    # In range 1000..3000: Just Chatting has 800s (1000..1800), Elden Ring has 1200s (1800..3000) -> Elden Ring
    assert dominant_game(segs, 1000, 3000) == "Elden Ring"
    # Whole stream: Elden Ring is 3600s, Just Chatting is 1800+1800 = 3600s (first encounter wins)
    assert dominant_game(segs, 0, 7200) in ("Just Chatting", "Elden Ring")
    # Empty / None / Out of range
    assert dominant_game(None, 0, 100) == ""
    assert dominant_game([], 0, 100) == ""
    assert dominant_game(segs, 8000, 9000) == ""
    assert dominant_game(segs, 100, 100) == ""


# --------------------------------------------------------------------------- expanded naming tokens
def test_expanded_naming_tokens_in_part_stem():
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    segs = [GameSegment(0, 3600, "Minecraft"), GameSegment(3600, 7200, "Overwatch")]
    fmts = [VideoFormat("1080p60", 1080, 60, 6000, False, True)]
    src = make_src(date="2026-10-27", segments=segs, formats=fmts)

    # stream_date, download_date, date, year, month, day
    opts_dates = make_opts(name_template="{stream_date}_{date}_{download_date}_{year}_{month}_{day}")
    assert part_stem(src, opts_dates, Part(1, 0, 1800), 1) == f"2026-10-27_2026-10-27_{today}_2026_10_27"

    # game, category, duration
    opts_content = make_opts(name_template="{game} - {category} - {duration} - part{n}")
    assert part_stem(src, opts_content, Part(1, 0, 1800), 2) == "Minecraft - Minecraft - 00h30m00s - part1"
    assert part_stem(src, opts_content, Part(2, 3600, 7200), 2) == "Overwatch - Overwatch - 01h00m00s - part2"

    # resolution as synonym for quality
    opts_res = make_opts(name_template="{streamer} - {resolution} - part{n}", quality="1080p")
    assert part_stem(src, opts_res, Part(1, 0, 1800), 2) == "Streamer - 1080p60 - part1"


def test_expanded_naming_tokens_in_stream_dir():
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    segs = [GameSegment(0, 1000, "Intro"), GameSegment(1000, 7200, "Cyberpunk 2077")]
    fmts = [VideoFormat("720p60", 720, 60, 3000, False, True)]
    src = make_src(date="2026-10-27", duration=7200.0, segments=segs, formats=fmts)

    opts = make_opts(
        folder_template="{year}-{month}-{day} - {game} - {duration} - {quality} - {id}",
        quality="720p",
    )
    p = stream_dir(src, opts)
    assert p == Path("OUT") / "Streamer" / "2026-10-27 - Cyberpunk 2077 - 02h00m00s - 720p60 - 123"

    # test download_date, stream_date, category, resolution in folder
    opts2 = make_opts(
        folder_template="{download_date} - {stream_date} - {category} - {resolution}",
        quality="720p",
    )
    p2 = stream_dir(src, opts2)
    assert p2 == Path("OUT") / "Streamer" / f"{today} - 2026-10-27 - Cyberpunk 2077 - 720p60"



def test_site_and_provider_tokens_and_provider_routing_in_stream_dir():
    src_yt = make_src(site="youtube", uploader="YouTuber", id="dQw4w9WgXcQ", twitch_vod_id=None, title="Never Gonna Give You Up")

    # 1. Test {site} and {provider} tokens in folder_template
    opts_tokens = make_opts(folder_template="{site} - {provider} - {id}")
    p = stream_dir(src_yt, opts_tokens)
    assert p == Path("OUT") / "YouTuber" / "youtube - youtube - dQw4w9WgXcQ"

    # 2. Test {site} and {provider} tokens in part_stem
    opts_name = make_opts(generic_name_template="{provider} - {site} - {id} - part{n}")
    stem = part_stem(src_yt, opts_name, Part(1, 0, 100), 1)
    assert stem == "youtube - youtube - dQw4w9WgXcQ"

    # 3. Test provider_subfolders routing in stream_dir
    opts_sub = make_opts(provider_subfolders=True, folder_template="{title}")
    p_sub = stream_dir(src_yt, opts_sub)
    assert p_sub == Path("OUT") / "YouTube" / "YouTuber" / "Never Gonna Give You Up"

    # 4. Test provider_out_dirs custom override in stream_dir
    opts_custom = make_opts(
        provider_out_dirs={"youtube": "E:/MyYouTubeArchive"},
        provider_subfolders=True,
        folder_template="{title}"
    )
    p_custom = stream_dir(src_yt, opts_custom)
    assert p_custom == Path("E:/MyYouTubeArchive") / "YouTuber" / "Never Gonna Give You Up"
