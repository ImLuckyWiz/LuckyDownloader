"""Cut-point text -> parts -> strategy, and inserting a split point."""

import pytest

from luckytwitch_engine import (
    Part,
    PlanError,
    choose_strategy,
    insert_cut_point,
    make_plan,
    parse_cut_points,
    split_groups,
)

DUR = 7200.0  # a 2 hour VOD


def spans(text, duration=DUR):
    return [(p.start, p.end) for p in parse_cut_points(text, duration)]


# --------------------------------------------------------------------------- split_groups
def test_split_groups_semicolon_and_newline_separate_groups():
    assert split_groups("0:00 - 30:00 ; 2:00:00 - end") == [["0:00", "30:00"], ["2:00:00", "end"]]
    assert split_groups("0:00 - 30:00\n2:00:00 - end") == [["0:00", "30:00"], ["2:00:00", "end"]]


def test_split_groups_ignores_filler_words_and_accepts_dash_variants():
    assert split_groups("0:00 hasta 30:00 ; 1:00:00 – end") == [["0:00", "30:00"], ["1:00:00", "end"]]
    assert split_groups("0:00 — 30:00, 1:00:00") == [["0:00", "30:00", "1:00:00"]]


def test_split_groups_empty():
    assert split_groups("") == []
    assert split_groups("  ;  \n ; ") == []


# --------------------------------------------------------------------------- parse_cut_points
def test_consecutive_points_make_consecutive_parts():
    parts = parse_cut_points("0:00 - 30:00 - 1:30:00 - end", DUR)
    assert [(p.index, p.start, p.end) for p in parts] == [
        (1, 0.0, 1800.0),
        (2, 1800.0, 5400.0),
        (3, 5400.0, 7200.0),
    ]


def test_part_duration_property():
    assert Part(1, 100, 160).duration == 60


def test_gap_example_from_the_readme():
    # README: "0:00 - 30:00 ; 1:00:00 - end" skips the middle
    assert spans("0:00 - 30:00 ; 1:00:00 - end") == [(0.0, 1800.0), (3600.0, 7200.0)]


def test_groups_are_sorted_and_reindexed():
    parts = parse_cut_points("1:00:00 - 1:30:00 ; 0:00 - 10:00", DUR)
    assert [(p.index, p.start, p.end) for p in parts] == [(1, 0.0, 600.0), (2, 3600.0, 5400.0)]


def test_touching_parts_are_allowed():
    assert spans("0:00 - 10:00 ; 10:00 - 20:00") == [(0.0, 600.0), (600.0, 1200.0)]


@pytest.mark.parametrize("word", ["end", "END", "End", "fin", "final", "eof", "finish"])
def test_end_words(word):
    assert spans(f"0:00 - {word}") == [(0.0, 7200.0)]


def test_end_needs_the_duration():
    with pytest.raises(PlanError, match="«end» needs the VOD length"):
        parse_cut_points("0:00 - end", None)


def test_numeric_points_work_without_a_duration():
    assert [(p.start, p.end) for p in parse_cut_points("0 - 100", None)] == [(0.0, 100.0)]


def test_empty_text_is_an_error():
    with pytest.raises(PlanError, match="Write the cut points"):
        parse_cut_points("", DUR)


def test_a_group_needs_two_points():
    with pytest.raises(PlanError, match="at least two points"):
        parse_cut_points("30:00", DUR)


def test_points_must_increase():
    with pytest.raises(PlanError, match="must increase"):
        parse_cut_points("30:00 - 10:00", DUR)
    with pytest.raises(PlanError, match="must increase"):
        parse_cut_points("10:00 - 10:00", DUR)


def test_overlapping_parts_are_rejected():
    with pytest.raises(PlanError, match="overlap"):
        parse_cut_points("0:00 - 30:00 ; 20:00 - 40:00", DUR)


def test_invalid_token_is_reported():
    with pytest.raises(PlanError, match="Invalid time"):
        parse_cut_points("banana - 10:00", DUR)


def test_beyond_the_end_of_the_vod():
    with pytest.raises(PlanError, match="beyond the end"):
        parse_cut_points("0:00 - 3:00:00", DUR)
    with pytest.raises(PlanError, match="beyond the end"):
        parse_cut_points("2:00:00 - 2:10:00", DUR)  # starts at/after the end


def test_end_up_to_two_seconds_past_the_duration_is_clamped():
    assert spans("0:00 - 2:00:01") == [(0.0, 7200.0)]
    with pytest.raises(PlanError):
        parse_cut_points("0:00 - 2:00:03", DUR)


# --------------------------------------------------------------------------- strategy
def test_choose_strategy_forced_modes_ignore_coverage():
    parts = [Part(1, 0, 10)]
    assert choose_strategy(parts, 1000, "full") == ("full", 0.01)
    assert choose_strategy(parts, 1000, "sections") == ("sections", 0.01)


def test_choose_strategy_auto_uses_the_threshold():
    big = [Part(1, 0, 700)]
    small = [Part(1, 0, 500)]
    assert choose_strategy(big, 1000, "auto", 0.6)[0] == "full"
    assert choose_strategy(small, 1000, "auto", 0.6)[0] == "sections"


def test_choose_strategy_auto_at_exactly_the_threshold_is_full():
    assert choose_strategy([Part(1, 0, 600)], 1000, "auto", 0.6)[0] == "full"


def test_choose_strategy_without_duration_assumes_full_coverage():
    assert choose_strategy([Part(1, 0, 10)], None, "auto", 0.6) == ("full", 1.0)


def test_make_plan_ties_it_together():
    plan = make_plan("0:00 - 5:00", DUR, "auto", 0.6)
    assert plan.strategy == "sections"
    assert plan.coverage == pytest.approx(300 / 7200)
    assert plan.duration == DUR
    assert [(p.start, p.end) for p in plan.parts] == [(0.0, 300.0)]
    assert make_plan("0:00 - end", DUR).strategy == "full"


# --------------------------------------------------------------------------- insert_cut_point
def test_insert_into_a_simple_range():
    assert insert_cut_point("0:00:00 - end", 3600, DUR) == "0:00:00 - 1:00:00 - end"


def test_insert_keeps_the_text_the_user_typed():
    assert insert_cut_point("0 - 1h", 1800, DUR) == "0 - 0:30:00 - 1h"


def test_insert_into_the_right_group_and_keeps_gaps():
    out = insert_cut_point("0:00 - 30:00 ; 1:00:00 - end", 4000, DUR)
    assert out == "0:00 - 30:00\n1:00:00 - 1:06:40 - end"
    assert spans(out) == [(0.0, 1800.0), (3600.0, 4000.0), (4000.0, 7200.0)]


def test_insert_into_empty_text():
    assert insert_cut_point("", 600, DUR) == "0:00:00 - 0:10:00 - end"
    assert insert_cut_point("", 600, None) == "0:00:00 - 0:10:00 - 0:10:01"


def test_insert_rounds_the_time_to_whole_seconds():
    assert insert_cut_point("0:00 - 2:00:00", 3597.4, DUR) == "0:00 - 0:59:57 - 2:00:00"


def test_insert_outside_any_part_is_an_error():
    with pytest.raises(PlanError, match="not inside any of your parts"):
        insert_cut_point("0:00 - 10:00", 3600, DUR)


@pytest.mark.parametrize("t", [0, 600])  # exactly on the edges of the only part
def test_insert_on_the_edges_of_a_part_is_an_error(t):
    with pytest.raises(PlanError, match="not inside any of your parts"):
        insert_cut_point("0:00 - 10:00", t, DUR)


def test_insert_skips_groups_it_cannot_read():
    out = insert_cut_point("banana - 5:00\n0:00 - end", 100, DUR)
    assert out == "banana - 5:00\n0:00 - 0:01:40 - end"


def test_insert_at_an_existing_boundary_gives_valid_text():
    once = insert_cut_point("0:00:00 - end", 3597, DUR)
    twice = insert_cut_point(once, 3597, DUR)
    assert twice == once  # no duplicate boundary: asking for the same cut again changes nothing
    parse_cut_points(twice, DUR)  # and the text is still valid


def test_cut_points_with_zero_or_unknown_duration():
    parts = parse_cut_points("0:00 - 1:00", duration=0.0)
    assert len(parts) == 1
    assert (parts[0].start, parts[0].end) == (0.0, 60.0)

    parts_none = parse_cut_points("0:00 - 1:00", duration=None)
    assert len(parts_none) == 1
    assert (parts_none[0].start, parts_none[0].end) == (0.0, 60.0)

    with pytest.raises(PlanError, match="«end» needs the VOD length"):
        parse_cut_points("0:00 - end", duration=0.0)
