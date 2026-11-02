"""
Safety-net test for Phase E (Engine Split).

Freezes the public symbol surface of luckytwitch_engine.py so that modularizing
code into core/ modules never causes a symbol to disappear from the facade.
"""

from __future__ import annotations

import luckytwitch_engine

# The 176 public symbols + cross-module private symbols exported by luckytwitch_engine
EXPECTED_ENGINE_EXPORTS = frozenset({
    "API_URL",
    "APP_DIR",
    "AUDIO_FORMATS",
    "AUDIO_SKIPPED",
    "CHAT_FORMATS",
    "CHAT_RENDER_EXT",
    "CHAT_RENDER_LABELS",
    "CHAT_RENDER_LOOKS",
    "CHAT_RENDER_MODES",
    "Cancelled",
    "Chapter",
    "ChatFileInfo",
    "ClipFilter",
    "Ctx",
    "DEVICE_GRANT",
    "DEVICE_URL",
    "END_WORDS",
    "EXE",
    "Edge",
    "EngineError",
    "FFMPEG_BUILDS",
    "FILLER_WORDS",
    "FfmpegProgress",
    "GameSegment",
    "HLS_USER_AGENT",
    "Job",
    "JobOptions",
    "MARKERS_JSON_FORMAT",
    "MARKERS_JSON_VERSION",
    "MEDIA_EXTS",
    "MIN_PART",
    "MP4_MOVIE_TIMESCALE",
    "MUTED_COMMENT",
    "MUTED_TITLE",
    "PART_VIDEO_EXTS",
    "PROGRESS_TEMPLATE",
    "Part",
    "Plan",
    "PlanError",
    "QUALITY_AUDIO",
    "QUALITY_BEST",
    "Range",
    "Segment",
    "SourceInfo",
    "Storyboard",
    "TDCLI_REPO",
    "TDCLI_VERSION",
    "TOKEN_URL",
    "TOOLS_DIR",
    "TWITCH_CLIENT_ID",
    "TwitchClient",
    "USER_AGENT",
    "VIDEO_TYPES",
    "VideoFormat",
    "YTDLP_MISSING",
    "YTDLP_RELEASES",
    "_SafeDict",
    "_download_file",
    "add_cut",
    "audio_codec_args",
    "audio_only_options",
    "audio_out_container",
    "chapters_for_part",
    "chat_base_name",
    "chat_command",
    "chat_files_for_part",
    "chat_lead_from_markers",
    "chat_overlay_settings",
    "chat_render_command",
    "chat_render_fps",
    "chat_render_output_args",
    "chat_render_size",
    "choose_strategy",
    "clean_title",
    "clip_cut_text",
    "clip_end",
    "clip_start",
    "cut_exact",
    "date_components",
    "describe_chat_overlay",
    "describe_quality",
    "describe_tools",
    "device_login_poll",
    "device_login_start",
    "dominant_game",
    "download_chat",
    "download_full",
    "download_section",
    "download_section_aligned",
    "edges_of",
    "ensure_tdcli",
    "ensure_tools",
    "estimate_bytes",
    "existing_chat_overlay_path",
    "fetch_clips_for_vod",
    "fetch_muted_ranges",
    "fetch_storyboard_sheet",
    "fetch_thumbnail",
    "fetch_videos",
    "ffmetadata",
    "fill_gaps",
    "filter_clips",
    "finalize_audio_part",
    "finalize_part",
    "find_part_video",
    "find_tdcli",
    "find_tool",
    "fmt_hms",
    "format_duration_tag",
    "game_chapters",
    "get_playlist_url",
    "get_source_info",
    "insert_cut_point",
    "install_ffmpeg",
    "install_tdcli",
    "install_ytdlp",
    "installed_ytdlp_version",
    "isolate_span",
    "kill_process_tree",
    "latest_ytdlp_tag",
    "load_storyboard_frames",
    "make_chapters",
    "make_plan",
    "move_edge",
    "mp4_flags",
    "mp4_movie_timescale",
    "muted_chapters",
    "muted_from_playlist_url",
    "muted_overlap",
    "nearest_edge",
    "normalize_url",
    "parse_cut_points",
    "parse_ffmpeg_stats",
    "parse_formats",
    "parse_game_segments",
    "parse_hls_playlist",
    "parse_muted_ranges",
    "parse_progress",
    "parse_render_status",
    "parse_source_info",
    "parse_storyboard",
    "parse_tdcli_status",
    "parse_time",
    "parse_twitch_duration",
    "part_index_at",
    "part_stem",
    "pick_playlist_url",
    "pick_tdcli_asset",
    "premiere_markers_json",
    "premiere_markers_xml",
    "probe_video",
    "ranges_of",
    "ranges_to_text",
    "read_chat_info",
    "remove_cut",
    "render_chat",
    "render_existing_chat",
    "resolve_format",
    "run_ffmpeg",
    "run_job",
    "run_ytdlp",
    "safe_name",
    "search_channels",
    "select_segments",
    "split_copy",
    "split_groups",
    "stream_dir",
    "tdcli_dir",
    "tdcli_error",
    "toggle_part",
    "twitch_vod_id",
    "unique_path",
    "user_data_dir",
    "write_local_playlist",
    "write_markers_json",
    "write_premiere_xml",
    "_TDCLI_EXE",
    "_extract_tdcli",
})


def test_engine_public_exports_are_preserved():
    """Assert all expected symbols remain importable from luckytwitch_engine."""
    missing = [name for name in EXPECTED_ENGINE_EXPORTS if not hasattr(luckytwitch_engine, name)]
    assert not missing, f"The following symbols were removed from luckytwitch_engine: {sorted(missing)}"


def test_engine_exports_are_not_none():
    """Assert no exported symbol is accidentally set to None."""
    for name in EXPECTED_ENGINE_EXPORTS:
        val = getattr(luckytwitch_engine, name)
        assert val is not None, f"Symbol {name} on luckytwitch_engine is None"


def test_engine_monkeypatch_targets_preserved():
    """Tests in test_qt_twitch_dialog.py patch engine.time and engine.requests."""
    assert hasattr(luckytwitch_engine, "time"), "engine.time must be preserved for test monkeypatching"
    assert hasattr(luckytwitch_engine, "requests"), "engine.requests must be preserved for test monkeypatching"


def test_luckydownloader_facade_modules():
    """Assert modern luckydownloader_engine and luckydownloader_qt facade modules exist and export key symbols."""
    import luckydownloader_engine
    import luckydownloader_qt

    assert hasattr(luckydownloader_engine, "Job")
    assert hasattr(luckydownloader_engine, "SourceInfo")
    assert hasattr(luckydownloader_engine, "run_job")
    assert hasattr(luckydownloader_qt, "MainWindow")
    assert hasattr(luckydownloader_qt, "main")

