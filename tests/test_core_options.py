"""``core.options`` (build_options / build_filter / tolerant numbers) and ``core.examples`` (the live example lines).

No Qt and no tkinter needed: these run everywhere. The comparison with the tkinter app's own ``build_options`` is in
tests/test_core_matches_tkinter.py (the golden test of Phase 5, needs tkinter).
"""

import luckytwitch_engine as eng
from core import examples, options
from core.settings import DEFAULTS


def s(**changes):
    return {**DEFAULTS, **changes}


# --------------------------------------------------------------------------- numbers and switches
def test_defaults_give_the_engines_defaults():
    o = options.build_options(s())
    assert (o.strategy, o.full_threshold, o.threads, o.container) == ("auto", 0.6, 8, "mp4")
    assert (o.chat_render_mode, o.chat_render_look, o.chat_render_fps) == ("transparent", "outline", 0)
    assert (o.chat_render_width, o.chat_render_height, o.chat_render_font_size) == (400, 0, 18)
    assert o.subfolders is True and o.chat is False and o.exact is False
    assert o.clip_filter == eng.ClipFilter(pad_before=3.0, title_template=DEFAULTS["title_tpl"], gap_title="Stream")


def test_text_that_is_not_a_number_gives_the_fallback_and_never_raises():
    for bad in ("", "abc", "1,5", "nan", "  ", "1e999", None):
        assert options.num(s(threads=bad), "threads", int, 8) == 8, bad
    assert options.num(s(threads=" 12 "), "threads", int, 8) == 12
    assert options.num(s(threads="7.9"), "threads", int, 8) == 7
    assert options.num(s(threads=5), "threads", int, 8) == 5  # a number that was written as a JSON number


def test_the_threshold_and_threads_are_clamped():
    assert options.build_options(s(threshold="0")).full_threshold == 0.01
    assert options.build_options(s(threshold="500")).full_threshold == 1.0
    assert options.build_options(s(threshold="abc")).full_threshold == 0.6
    assert options.build_options(s(threads="0")).threads == 1
    assert options.build_options(s(threads="-4")).threads == 1


def test_switches_read_booleans_and_tcl_style_words():
    for on in (True, "1", "true", "yes", "on", "True"):
        assert options.flag(s(exact=on), "exact") is True, on
    for off in (False, "0", "false", "no", "", "garbage", None):
        assert options.flag(s(exact=off), "exact") is False, off


def test_drop_down_words_map_to_engine_values_and_unknown_words_fall_back():
    o = options.build_options(s(strategy="Download only the parts",
                                chat_render_mode="Black background · H.264 (.mp4, smallest)",
                                chat_render_look="Dark see-through panel", chat_render_fps="60", chat_format="txt"))
    assert (o.strategy, o.chat_render_mode, o.chat_render_look, o.chat_render_fps, o.chat_format) == \
        ("sections", "compact", "panel", 60, "txt")
    o = options.build_options(s(strategy="???", chat_render_mode="???", chat_render_look="???",
                                chat_render_fps="45", chat_format="docx"))
    assert (o.strategy, o.chat_render_mode, o.chat_render_look, o.chat_render_fps, o.chat_format) == \
        ("auto", "transparent", "outline", 0, "json")


def test_empty_texts_fall_back_to_the_defaults():
    o = options.build_options(s(out_dir="  ", name_template=" ", folder_template="", clip_name_template="  ",
                                title_tpl="", gap_title="  "))
    assert o.out_dir == DEFAULTS["out_dir"] and o.name_template == DEFAULTS["name_template"]
    assert o.folder_template == DEFAULTS["folder_template"] and o.clip_name_template == DEFAULTS["clip_name_template"]
    assert o.clip_filter.title_template == DEFAULTS["title_tpl"] and o.clip_filter.gap_title == ""


def test_the_cut_text_is_trimmed_and_passed_on():
    assert options.build_options(s(), "  0:00 - 0:10\n").cut_text == "0:00 - 0:10"
    assert options.build_options(s()).cut_text == ""


def test_a_missing_key_reads_as_its_default():
    partial = {"threads": "3"}
    assert options.build_options(partial).threads == 3
    assert options.build_options(partial).container == "mp4"


# --------------------------------------------------------------------------- the live examples
def test_examples_use_a_sample_vod_until_one_is_loaded():
    assert examples.example_file_name(s()) == "Streamer - 2026-10-01 - 123 - part1.mp4"
    assert examples.example_folder_name(s()) == "Streamer/2026-10-01 - Big Stream - 123"
    real = eng.SourceInfo(**dict(examples.SAMPLE_SOURCE, uploader="Zed", title="Late night", date="2026-12-24",
                                 twitch_vod_id="999"))
    assert examples.example_file_name(s(), real) == "Zed - 2026-12-24 - 999 - part1.mp4"
    assert examples.example_folder_name(s(), real) == "Zed/2026-12-24 - Late night - 999"


def test_the_example_follows_the_template_and_the_container():
    assert examples.example_file_name(s(name_template="{n} of {total} - {title}")) == "1 of 3 - Big Stream.mp4"
    assert examples.example_file_name(s(name_template="{n} of {total} - {title}", container="mkv")) == \
        "1 of 3 - Big Stream.mkv"


def test_a_half_typed_template_never_raises():
    for bad in ("{", "{title", "{0}", "}{", "", "{n:}", "{title!x}", "{{}"):
        t = s(name_template=bad, folder_template=bad, clip_name_template=bad, title_tpl=bad)
        for fn in (examples.example_file_name, examples.example_folder_name, examples.example_clip_name):
            assert isinstance(fn(t), str), (bad, fn.__name__)
        assert isinstance(examples.example_chapter(t), str), bad


def test_the_example_matches_what_the_engine_really_names_the_file():
    src = eng.SourceInfo(**examples.SAMPLE_SOURCE)
    opts = eng.JobOptions(cut_text="", out_dir="OUT", name_template="{streamer}_{start}-{end}")
    expect = eng.part_stem(src, opts, eng.Part(1, 0, 3600), 3) + ".mp4"
    assert examples.example_file_name(s(name_template="{streamer}_{start}-{end}")) == expect


def test_clip_and_chapter_examples():
    assert examples.example_clip_name(s(clip_name_template="{clip_title} by {creator} ({views})")) == \
        "Epic fail by viewer1 (500).mp4"
    assert examples.example_chapter(s()) == "Epic fail (viewer1, 500 views)"
    assert examples.example_chapter(s(title_tpl="{title} - {nope}")) == "Epic fail - {nope}"
    assert examples.example_chapter(s(title_tpl="{title")) == "(the template has an unfinished {…})"


def test_quality_and_audio_format_resolution():
    # Defaults
    o = options.build_options(s())
    assert o.quality == "best"
    assert o.audio_format == "m4a"

    # Settings mapping
    assert options.build_options(s(default_quality="720p")).quality == "720p"
    assert options.build_options(s(default_quality="Audio only")).quality == "audio"
    assert options.build_options(s(default_quality="unknown")).quality == "best"
    assert options.build_options(s(audio_format="mp3 · converted")).audio_format == "mp3"
    assert options.build_options(s(audio_format="unknown")).audio_format == "m4a"

    # Explicit quality argument overrides settings
    assert options.build_options(s(default_quality="720p"), quality="480p").quality == "480p"
    assert options.build_options(s(default_quality="720p"), quality="best").quality == "best"


def test_video_encoder_option_mapping():
    assert options.build_options(s()).video_encoder == "auto"
    assert options.build_options(s(video_encoder="nvenc")).video_encoder == "nvenc"
    assert options.build_options(s(video_encoder="h264_qsv")).video_encoder == "qsv"
    assert options.build_options(s(video_encoder="libx264")).video_encoder == "cpu"
    assert options.build_options(s(video_encoder="unknown")).video_encoder == "auto"
