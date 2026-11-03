"""Clips -> filtered clips -> chapters -> per-part chapters -> ffmpeg metadata / Premiere XML."""

import xml.etree.ElementTree as ET

import pytest

import luckytwitch_engine as eng
from luckytwitch_engine import (
    Chapter,
    ClipFilter,
    PlanError,
    chapters_for_part,
    clip_cut_text,
    ffmetadata,
    clip_start,
    fill_gaps,
    filter_clips,
    make_chapters,
    premiere_markers_xml,
)


def clip(start, views=0, duration=30, title="T", creator="c", **extra):
    """A clip that STARTS at `start`. Twitch's vod_offset is where the clip ENDS (start + duration)."""
    offset = None if start is None else start + duration
    return {"vod_offset": offset, "view_count": views, "duration": duration, "title": title,
            "creator_name": creator, "url": f"https://clips.twitch.tv/{start}", **extra}


# --------------------------------------------------------------------------- filter_clips
def test_filter_drops_clips_without_a_position():
    assert filter_clips([clip(None), clip(10)], ClipFilter()) == [clip(10)]


def test_filter_min_views_and_min_duration():
    clips = [clip(10, views=5, duration=10), clip(20, views=50, duration=10), clip(30, views=50, duration=40)]
    assert [clip_start(c) for c in filter_clips(clips, ClipFilter(min_views=50))] == [20, 30]
    assert [clip_start(c) for c in filter_clips(clips, ClipFilter(min_duration=30))] == [30]


def test_filter_top_n_keeps_the_most_viewed_but_returns_them_in_time_order():
    clips = [clip(10, views=1), clip(20, views=100), clip(30, views=50), clip(40, views=100)]
    kept = filter_clips(clips, ClipFilter(top_n=2))
    assert [clip_start(c) for c in kept] == [20, 40]


def test_filter_top_n_ties_are_broken_by_earlier_offset():
    clips = [clip(30, views=10), clip(10, views=10), clip(20, views=10)]
    assert [clip_start(c) for c in filter_clips(clips, ClipFilter(top_n=2))] == [10, 20]


def test_filter_returns_time_order():
    assert [clip_start(c) for c in filter_clips([clip(50), clip(5), clip(20)], ClipFilter())] == [5, 20, 50]


# --------------------------------------------------------------------------- make_chapters
FLT = ClipFilter(pad_before=3, pad_after=0, title_template="{title}")


def test_chapter_times_use_the_lead_in_and_the_clip_length():
    (ch,) = make_chapters([clip(100, views=7, duration=20, title="Nice")], FLT)
    assert (ch.start, ch.end, ch.title, ch.views) == (97.0, 120.0, "Nice", 7)


def test_chapter_start_never_goes_below_zero():
    (ch,) = make_chapters([clip(1)], FLT)
    assert ch.start == 0.0


def test_chapter_pad_after_extends_the_end():
    (ch,) = make_chapters([clip(100, duration=20)], ClipFilter(pad_before=0, pad_after=5, title_template="{title}"))
    assert ch.end == 125.0


def test_default_title_template_has_creator_and_views():
    (ch,) = make_chapters([clip(100, views=12, title="Fail", creator="bob")], ClipFilter())
    assert ch.title == "Fail (bob, 12 views)"


def test_untitled_clip_gets_a_default_title():
    (ch,) = make_chapters([clip(100, title="")], FLT)
    assert ch.title == "Clip"


def test_broken_title_template_falls_back_to_the_clip_title():
    (ch,) = make_chapters([clip(100, title="Hi")], ClipFilter(title_template="{title"))
    assert ch.title == "Hi"
    (ch2,) = make_chapters([clip(100, title="Hi")], ClipFilter(title_template="{title.foo}"))
    assert ch2.title == "Hi"
    (ch3,) = make_chapters([clip(100, title="Hi")], ClipFilter(title_template="{duration[0]}"))
    assert ch3.title == "Hi"


def test_unknown_title_token_stays_as_it_is():
    (ch,) = make_chapters([clip(100, title="Hi")], ClipFilter(title_template="{title} {nope}"))
    assert ch.title == "Hi {nope}"


def test_overlapping_clips_are_merged_and_keep_the_best_title():
    a = clip(100, views=10, duration=20, title="A")  # 97 -> 120
    b = clip(110, views=99, duration=30, title="B")  # 107 -> 140, overlaps A
    (ch,) = make_chapters([a, b], FLT)
    assert (ch.start, ch.end) == (97.0, 140.0)
    assert ch.title == "B  (+1 more)"
    assert ch.views == 99
    assert ch.clips == [a, b]


def test_three_way_merge_counts_the_extra_clips():
    clips = [clip(100, views=1, title="A"), clip(105, views=3, title="B"), clip(110, views=2, title="C")]
    (ch,) = make_chapters(clips, FLT)
    assert ch.title == "B  (+2 more)"
    assert len(ch.clips) == 3


def test_clips_that_touch_are_merged_but_separate_ones_are_not():
    touching = make_chapters([clip(100, duration=20), clip(123, duration=5)], FLT)  # 97-120 and 120-128
    assert len(touching) == 1
    apart = make_chapters([clip(100, duration=20), clip(200, duration=5)], FLT)
    assert [(c.start, c.end) for c in apart] == [(97.0, 120.0), (197.0, 205.0)]


def test_make_chapters_respects_the_filter():
    chapters = make_chapters([clip(10, views=1), clip(500, views=100)], ClipFilter(min_views=50, title_template="{title}"))
    assert len(chapters) == 1 and chapters[0].start == 497.0


# --------------------------------------------------------------------------- chapters_for_part
def test_chapters_for_part_are_relative_to_the_part():
    chs = [Chapter(100, 130, "A"), Chapter(500, 520, "B")]
    out = chapters_for_part(chs, 90, 200)
    assert [(c.start, c.end, c.title) for c in out] == [(10.0, 40.0, "A")]


def test_chapters_for_part_are_clamped_to_the_part_edges():
    out = chapters_for_part([Chapter(80, 130, "A")], 100, 120)
    assert [(c.start, c.end) for c in out] == [(0.0, 20.0)]


def test_chapters_outside_or_barely_inside_the_part_are_dropped():
    chs = [Chapter(0, 50, "before"), Chapter(200, 300, "after"), Chapter(99.5, 130, "straddles")]
    # part = 100..200: 'before' ends at 50, 'after' only starts where the part ends -> both dropped;
    # 'straddles' starts just before the part and keeps its 30 s inside it
    out = chapters_for_part(chs, 100, 200)
    assert [c.title for c in out] == ["straddles"]
    # a chapter that overlaps the part by less than 1 second is dropped
    assert chapters_for_part([Chapter(99, 100.5, "tiny")], 100, 200) == []


# --------------------------------------------------------------------------- fill_gaps
def test_fill_gaps_fills_before_between_and_after():
    chs = [Chapter(10, 20, "A"), Chapter(30, 40, "B")]
    out = fill_gaps(chs, 60, "Stream")
    assert [(c.start, c.end, c.title) for c in out] == [
        (0.0, 10, "Stream"), (10, 20, "A"), (20, 30, "Stream"), (30, 40, "B"), (40, 60, "Stream"),
    ]


def test_fill_gaps_does_not_add_slivers_under_one_second():
    chs = [Chapter(0, 20, "A"), Chapter(20.5, 59.5, "B")]
    out = fill_gaps(chs, 60, "Stream")
    assert [c.title for c in out] == ["A", "B"]


def test_fill_gaps_is_a_no_op_without_chapters_or_without_a_title():
    assert fill_gaps([], 60, "Stream") == []
    chs = [Chapter(10, 20, "A")]
    assert fill_gaps(chs, 60, "") is chs


# --------------------------------------------------------------------------- ffmetadata
def test_ffmetadata_layout():
    text = ffmetadata([Chapter(1.5, 10, "Intro")], {"title": "My VOD", "artist": ""})
    assert text == (
        ";FFMETADATA1\ntitle=My VOD\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1500\nEND=10000\ntitle=Intro\n"
    )


def test_ffmetadata_skips_empty_tags_and_escapes_special_characters():
    text = ffmetadata([Chapter(0, 1, "a=b;c#d\\e")], {"comment": "x=y", "date": ""})
    assert "comment=x\\=y" in text
    assert "date=" not in text
    assert "title=a\\=b\\;c\\#d\\\\e" in text


def test_ffmetadata_without_chapters():
    assert ffmetadata([]) == ";FFMETADATA1\n"


# --------------------------------------------------------------------------- clip_cut_text
def test_clip_cut_text_adds_padding_and_rounds_outwards():
    assert clip_cut_text({"vod_offset": 630.4, "duration": 30}, 7200) == "0:09:57 - 0:10:34"


def test_clip_cut_text_is_clamped_to_the_vod():
    assert clip_cut_text({"vod_offset": 31, "duration": 30}, 7200) == "0:00:00 - 0:00:34"
    assert clip_cut_text({"vod_offset": 7220, "duration": 30}, 7200) == "1:59:47 - 2:00:00"


def test_clip_cut_text_errors():
    with pytest.raises(PlanError, match="no position"):
        clip_cut_text({"vod_offset": None, "duration": 30}, 7200)
    with pytest.raises(PlanError, match="outside the VOD"):
        clip_cut_text({"vod_offset": 9000, "duration": 30}, 7200)


# --------------------------------------------------------------------------- Premiere XML
@pytest.mark.parametrize(
    "fps, expected",
    [(25, (25, False)), (30, (30, False)), (24, (24, False)), (60, (60, False)),
     (23.976, (24, True)), (29.97, (30, True)), (59.94, (60, True)), (29.5, (30, False))],
)
def test_timebase(fps, expected):
    assert eng._timebase(fps) == expected


def _markers(xml):
    root = ET.fromstring(xml)
    return root, root.findall("./sequence/marker")


def test_premiere_xml_is_well_formed_with_one_marker_per_chapter():
    chs = [Chapter(10, 20, "A", clips=[clip(0)]), Chapter(30, 40, "B")]
    root, markers = _markers(premiere_markers_xml("seq", chs, 60, 30))
    assert root.tag == "xmeml"
    assert len(markers) == 2
    assert root.findtext("./sequence/name") == "seq"
    assert root.findtext("./sequence/duration") == str(60 * 30)


def test_premiere_xml_marker_frames_at_30fps():
    _, (m,) = _markers(premiere_markers_xml("seq", [Chapter(10, 20, "A")], 60, 30))
    assert (m.findtext("in"), m.findtext("out")) == ("300", "600")


def test_premiere_xml_ntsc_flag_for_fractional_rates():
    root, _ = _markers(premiere_markers_xml("seq", [], 10, 29.97))
    assert root.findtext("./sequence/rate/ntsc") == "TRUE"
    assert root.findtext("./sequence/rate/timebase") == "30"


def test_premiere_xml_escapes_titles_and_comments():
    ch = Chapter(1, 5, "Tom & <Jerry>", clips=[clip(0, creator="a&b")])
    xml = premiere_markers_xml("s & s", [ch], 10, 30)
    root, (m,) = _markers(xml)  # parsing proves the escaping is valid XML
    assert m.findtext("name") == "Tom & <Jerry>"
    assert "a&b" in m.findtext("comment")
    assert root.findtext("./sequence/name") == "s & s"


def test_premiere_xml_zero_length_marker_has_no_out_point():
    _, (m,) = _markers(premiere_markers_xml("seq", [Chapter(5, 5, "A")], 10, 30))
    assert m.findtext("out") == "-1"


# --------------------------------------------------------------------------- vod_offset is the END of the clip
def test_clip_start_is_the_offset_minus_the_duration():
    # real case: the clip ends at 0:22:15 and lasts 60 s, so it starts at 0:21:15
    assert clip_start({"vod_offset": 22 * 60 + 15, "duration": 60}) == 21 * 60 + 15
    assert clip_start({"vod_offset": None, "duration": 60}) is None
    assert clip_start({"vod_offset": 10, "duration": 60}) == 0  # never before the start of the VOD


def test_chapter_for_a_real_clip_covers_the_clip_not_what_comes_after_it():
    (ch,) = make_chapters([{"vod_offset": 22 * 60 + 15, "duration": 60, "title": "x", "view_count": 5}],
                          ClipFilter(pad_before=3, title_template="{title}"))
    assert (ch.start, ch.end) == (21 * 60 + 12, 22 * 60 + 15)
