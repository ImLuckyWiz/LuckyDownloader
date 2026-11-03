"""
Twitch chat download and video overlay rendering via TwitchDownloaderCLI.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.errors import Cancelled, EngineError
from core.i18n import t
from core.premiere_export import probe_video
from core.runtime import Ctx, _NO_WINDOW, _tool_env, find_tool
from core.timeutil import fmt_hms

if sys.version_info >= (3, 11):
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from core.job import JobOptions
        from core.planning import Part
        from core.source_info import SourceInfo


def unique_path(path: Path) -> Path:
    """Ensure a filename does not collide with an existing file by appending (2), (3)..."""
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
        n += 1


# --------------------------------------------------------------------------- #
# Chat download (TwitchDownloaderCLI, only used when "Download chat" is on)
# --------------------------------------------------------------------------- #
CHAT_FORMATS = ("json", "txt", "html")

_TDCLI_STATUS = re.compile(r"^\[STATUS\]\s*-\s*(?P<phase>.*?)\s*(?:(?P<pct>\d+)%)?\s*(?:\[\d+/\d+\])?\s*$")
_CHAT_PHASES = (("downloading", 0.0, 0.85), ("backfilling", 0.85, 0.98), ("writing", 0.98, 1.0))


def parse_tdcli_status(line: str) -> tuple[str, float | None] | None:
    """'[STATUS] - Downloading 16%' -> ('Downloading', 0.136). None if the line is not a status line."""
    m = _TDCLI_STATUS.match(line.strip())
    if not m:
        return None
    phase, pct = m.group("phase"), m.group("pct")
    for key, lo, hi in _CHAT_PHASES:
        if phase.lower().startswith(key):
            return phase, lo + (hi - lo) * (min(int(pct), 100) / 100 if pct else 0.0)
    return phase, None


def tdcli_error(lines: list[str]) -> str:
    """The useful part of what TwitchDownloaderCLI printed when it failed (it can dump a whole stack trace)."""
    for ln in lines:
        if "--->" in ln and "Exception:" in ln:
            return ln.split("Exception:", 1)[1].strip()
    for ln in lines:
        if ln.startswith("[ERROR]"):
            return ln[len("[ERROR]"):].lstrip(" -").strip()
    for ln in lines:
        if ln.startswith("Unhandled exception"):
            return ln.split(":", 1)[-1].strip()
    return " | ".join(lines[-3:]) or "no details"


def chat_command(tdcli: str, vod_id: str, start: float, end: float, out: Path, embed: bool, cache_dir: Path) -> list[str]:
    """Chat of [start, end] (VOD time, widened to whole seconds: the chat API only has whole seconds)."""
    cmd = [
        tdcli, "chatdownload", "--id", vod_id,
        "-b", f"{math.floor(start)}s", "-e", f"{math.ceil(end)}s",
        "-o", str(out),
        "--collision", "Overwrite",  # never wait for an answer: nobody can type into the pipe
        "--banner=false", "--log-level", "Status,Warning,Error",
        "--temp-path", str(cache_dir),
    ]
    if embed:
        cmd.append("--embed-images")
    return cmd


def _run_tdcli(ctx: Ctx, cmd: list[str], dest: Path, what: str,
               parse: Callable[[str], tuple[str, float | None] | None], log_steps: bool = False) -> list[str]:
    """
    Run one TwitchDownloaderCLI command that writes `dest` and send its progress to the bar. Never leaves a
    half-written file behind. Returns the [WARNING] lines the program printed (a render says there what it missed).
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=_tool_env(),
            creationflags=_NO_WINDOW, start_new_session=sys.platform != "win32",
        )
    except OSError as e:
        raise EngineError(t("Could not run TwitchDownloaderCLI:\n{error}").format(error=e)) from e

    tail: list[str] = []
    warnings: list[str] = []
    ok = False
    try:
        ctx.attach_proc(proc)
        assert proc.stdout is not None
        for line in proc.stdout:  # text mode: the program's «\r» progress updates arrive as separate lines
            line = line.strip()
            if not line:
                continue
            status = parse(line)
            if status:
                ctx.report(status[1], status[0])
                if log_steps and status[1] is not None:
                    ctx.log_progress(status[1], status[0].partition(" · ")[2])
                continue
            if len(tail) < 60:
                tail.append(line)
            if line.startswith("[WARNING]") and len(warnings) < 20:
                warnings.append(line)
        proc.wait()
        ctx.check_cancel()
        if proc.returncode != 0:
            raise EngineError(f"{what} failed: " + tdcli_error(tail))
        if not dest.is_file() or dest.stat().st_size == 0:
            raise EngineError(t("{what} finished but the file is empty.").format(what=what))
        ok = True
        return warnings
    finally:
        ctx.attach_proc(None)
        if not ok:
            try:  # a cancelled / failed run leaves an empty or half-written file behind
                dest.unlink(missing_ok=True)
            except OSError:
                pass


def download_chat(ctx: Ctx, tdcli: str, vod_id: str, start: float, end: float, dest: Path,
                  embed: bool, cache_dir: Path) -> Path:
    """Run TwitchDownloaderCLI for one stretch of a VOD. Never leaves a half-written file behind."""
    ctx.check_cancel()
    eng = sys.modules.get("luckytwitch_engine")
    _uniq = getattr(eng, "unique_path", unique_path) if eng else unique_path
    dest = _uniq(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _run_tdcli(ctx, chat_command(tdcli, vod_id, start, end, dest, embed, cache_dir), dest, "Chat download",
               parse_tdcli_status)
    return dest


# --------------------------------------------------------------------------- #
# Chat overlay: the chat as a video for the editor (TwitchDownloaderCLI chatrender)
# --------------------------------------------------------------------------- #
CHAT_RENDER_MODES = ("transparent", "prores", "compact")
CHAT_RENDER_LOOKS = ("outline", "panel")
CHAT_RENDER_EXT = {"transparent": ".mov", "prores": ".mov", "compact": ".mp4"}
CHAT_RENDER_LABELS = {
    "transparent": "transparent, Animation",
    "prores": "transparent, ProRes 4444",
    "compact": "black background, H.264",
}
_TDCLI_RENDER_STATUS = re.compile(
    r"^\[STATUS\]\s*-\s*(?P<phase>[A-Za-z][A-Za-z ]*?)\s*(?:(?P<pct>\d+)%)?\s*"
    r"(?:\([^|()]*Elapsed\s*\|\s*(?P<left>[^()]*?)\s*Remaining\))?\s*(?:\[\d+/\d+\])?\s*$"
)
_TDCLI_DURATION = re.compile(r"(\d+)h(\d+)m(\d+)s")


def parse_render_status(line: str) -> tuple[str, float | None] | None:
    """
    '[STATUS] - Rendering Video 12% (0h0m1s Elapsed | 0h1m8s Remaining)' -> ('Rendering Video · 0:01:08 left', 0.12).
    Phases without a percentage («Fetching Images [1/2]») give None as the fraction. None if it is not a status line.
    """
    m = _TDCLI_RENDER_STATUS.match(line.strip())
    if not m:
        return None
    phase, pct = m.group("phase"), m.group("pct")
    frac = min(int(pct), 100) / 100 if pct else None
    label = phase
    left = _TDCLI_DURATION.fullmatch((m.group("left") or "").strip())
    if left and pct and int(pct) >= 1:  # at 0% the program's estimate is nonsense
        label += f" · {int(left[1])}:{int(left[2]):02d}:{int(left[3]):02d} left"
    return label, frac


def chat_render_size(width: int, height: int, video_height: int | None) -> tuple[int, int]:
    """(width, height) of the overlay in pixels: even numbers (H.264 needs them), height 0 = the video's height."""
    w = min(max(int(width or 0) or 400, 100), 3840)
    h = min(max(int(height or 0) or int(video_height or 0) or 1080, 100), 4320)
    return w - w % 2, h - h % 2


def chat_render_fps(option: int, video_fps: float | None) -> int:
    """Frame rate of the overlay: the one asked for, or (0) 60 for a 60 fps video and 30 for anything else."""
    if option and option > 0:
        return min(int(option), 120)
    return 60 if video_fps and video_fps >= 45 else 30


def chat_render_output_args(mode: str, lead: float = 0.0) -> str:
    """
    The ffmpeg output arguments of the render. `lead` seconds are cut off the start: the chat file begins at a whole
    second and the part may begin a bit later, so this keeps the overlay lined up with the video. (Never use ffmpeg's
    -t here: it closes the pipe early and TwitchDownloaderCLI crashes. The end is set by the chat file instead.)
    """
    skip = f"-ss {lead:.3f} " if lead >= 0.005 else ""
    if mode == "prores":
        enc = "-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le -vendor apl0"
    elif mode == "compact":
        enc = "-c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -movflags +faststart"
    else:  # QuickTime Animation: lossless, keeps the alpha, and a chat that only changes a few times a second is tiny
        enc = "-c:v qtrle -pix_fmt argb"
    return f'{skip}{enc} "{{save_path}}"'


def chat_render_command(tdcli: str, chat_json: Path, out: Path, *, mode: str, look: str, width: int, height: int,
                        font_size: int, fps: int, smooth: bool, ffmpeg: str | None, cache_dir: Path,
                        lead: float = 0.0) -> list[str]:
    """Render the chat file `chat_json` (the stretch it covers, from its own start) to the video `out`."""
    solid = mode == "compact"  # no alpha channel: black, and the editor's Screen blend mode makes it see-through
    panel = look == "panel" and not solid
    cmd = [
        tdcli, "chatrender", "-i", str(chat_json), "-o", str(out),
        "--chat-width", str(width), "--chat-height", str(height),
        "--font-size", str(min(max(int(font_size or 0) or 18, 6), 96)),
        "--framerate", str(fps), "--update-rate", "0" if smooth else "0.2",
        "--background-color", "#000000" if solid else ("#B3000000" if panel else "#00000000"),
        "--collision", "Overwrite",  # never wait for an answer: nobody can type into the pipe
        "--banner=false", "--log-level", "Status,Warning,Error",
        "--temp-path", str(cache_dir),
    ]
    if not solid and not panel:
        cmd.append("--outline")  # nothing behind the text: the outline keeps it readable over any picture
    if ffmpeg:
        cmd += ["--ffmpeg-path", ffmpeg]
    cmd.append("--output-args=" + chat_render_output_args(mode, lead))  # «=»: the value starts with «-»
    return cmd


def render_chat(ctx: Ctx, tdcli: str, chat_json: Path, dest: Path, *, mode: str, look: str, width: int,
                height: int, font_size: int, fps: int, smooth: bool, cache_dir: Path, lead: float = 0.0) -> Path:
    """Render one chat file as an overlay video. Never leaves a half-written file behind."""
    ctx.check_cancel()
    eng = sys.modules.get("luckytwitch_engine")
    _uniq = getattr(eng, "unique_path", unique_path) if eng else unique_path
    _find = getattr(eng, "find_tool", find_tool) if eng else find_tool
    dest = _uniq(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cmd = chat_render_command(tdcli, chat_json, dest, mode=mode, look=look, width=width, height=height,
                              font_size=font_size, fps=fps, smooth=smooth, ffmpeg=_find("ffmpeg"),
                              cache_dir=cache_dir, lead=lead)
    for w in _run_tdcli(ctx, cmd, dest, "Chat render", parse_render_status, log_steps=True)[:3]:
        ctx.log("Warning: chat overlay: " + w[len("[WARNING]"):].lstrip(" -").strip())
    return dest


def chat_overlay_settings(opts: JobOptions, probe: tuple[float, int, int] | None) -> tuple[str, str, int, int, int]:
    """(mode, look, width, height, fps) of an overlay: what the options say, and the video's size and rate where they say «like the video»."""
    mode = opts.chat_render_mode if opts.chat_render_mode in CHAT_RENDER_MODES else "transparent"
    look = opts.chat_render_look if opts.chat_render_look in CHAT_RENDER_LOOKS else "outline"
    width, height = chat_render_size(opts.chat_render_width, opts.chat_render_height, probe[2] if probe else None)
    fps = chat_render_fps(opts.chat_render_fps, probe[0] if probe else None)
    return mode, look, width, height, fps


# --------------------------------------------------------------------------- #
# Overlay from a chat file that is already on disk («name.chat.json»)
# --------------------------------------------------------------------------- #
PART_VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".ts", ".m4v", ".webm")


@dataclass
class ChatFileInfo:
    """What a TwitchDownloader .json chat says about itself (all of it is read from the file)."""
    vod_id: str
    streamer: str
    title: str
    start: float  # the stretch of the VOD the file covers, in seconds from the start of the VOD
    end: float
    messages: int
    embedded: bool  # emotes and badges are inside the file (it can be drawn offline)


def read_chat_info(path: Path) -> ChatFileInfo:
    """Read a «.chat.json» saved by TwitchDownloader. Raises EngineError, saying why, if it is not one."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise EngineError(t("Could not read the chat file: {error}").format(error=e)) from e
    comments = data.get("comments") if isinstance(data, dict) else None
    video = data.get("video") if isinstance(data, dict) else None
    if not isinstance(comments, list) or not isinstance(video, dict):
        raise EngineError(t("This is not a chat file saved by TwitchDownloader (a «.chat.json»)."))
    if not comments:
        raise EngineError(t("This chat file has no messages, so there is nothing to draw."))

    def seconds(value, fallback: float) -> float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback

    def offset(c) -> float:
        return seconds(c.get("content_offset_seconds") if isinstance(c, dict) else None, 0.0)

    streamer = data.get("streamer") if isinstance(data.get("streamer"), dict) else {}
    embedded = data.get("embeddedData")
    return ChatFileInfo(
        vod_id=str(video.get("id") or ""),
        streamer=str(streamer.get("name") or ""),
        title=str(video.get("title") or ""),
        start=seconds(video.get("start"), offset(comments[0])),
        end=seconds(video.get("end"), offset(comments[-1])),
        messages=len(comments),
        embedded=isinstance(embedded, dict) and any(isinstance(v, list) and v for v in embedded.values()),
    )


def chat_base_name(chat_json: Path) -> str:
    """«Streamer - part1.chat.json» → «Streamer - part1»: the name the part's other files share."""
    name = chat_json.name
    for ending in (".chat.json", ".json"):
        if name.lower().endswith(ending):
            return name[: -len(ending)]
    return chat_json.stem


def find_part_video(chat_json: Path) -> Path | None:
    """The video the chat belongs to («name.mp4» next to «name.chat.json»), if it is there."""
    base = chat_base_name(chat_json)
    for ext in PART_VIDEO_EXTS:
        candidate = chat_json.with_name(base + ext)
        if candidate.is_file():
            return candidate
    return None


def chat_lead_from_markers(chat_json: Path, info: ChatFileInfo) -> float:
    """
    Seconds the overlay must be trimmed at its start to line up with the part: the fraction of the part's start,
    read from «name.markers.json» next to the chat when it is there. The chat file itself only has whole seconds.
    Only used when that file is really about this chat (same whole second); 0 otherwise.
    """
    path = chat_json.with_name(chat_base_name(chat_json) + ".markers.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("format") != "luckytwitch-markers":
            return 0.0
        part_start = float(data["part"]["start"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0.0
    if not math.isfinite(part_start) or math.floor(part_start) != math.floor(info.start):
        return 0.0
    return part_start - math.floor(part_start)


def existing_chat_overlay_path(chat_json: Path, mode: str) -> Path:
    """Where the overlay of «name.chat.json» goes: «name.chat-overlay.mov» (or .mp4), next to it."""
    return chat_json.with_name(chat_base_name(chat_json) + ".chat-overlay" + CHAT_RENDER_EXT.get(mode, ".mov"))


def render_existing_chat(ctx: Ctx, tdcli: str, chat_json: Path, opts: JobOptions, cache_dir: Path) -> Path:
    """
    Draw the overlay of a chat file that is already on disk, with the overlay settings of `opts`. Nothing is
    downloaded and neither the chat nor the video is touched. Size and frame rate follow «name.mp4» (or .mkv…)
    next to the chat when it exists; the fraction of the part's start comes from «name.markers.json» when it exists.
    """
    eng = sys.modules.get("luckytwitch_engine")
    _probe = getattr(eng, "probe_video", probe_video) if eng else probe_video
    _render = getattr(eng, "render_chat", render_chat) if eng else render_chat

    info = read_chat_info(chat_json)
    video = find_part_video(chat_json)
    mode, look, width, height, fps = chat_overlay_settings(opts, _probe(video) if video else None)
    lead = chat_lead_from_markers(chat_json, info)
    out = _render(
        ctx, tdcli, chat_json, existing_chat_overlay_path(chat_json, mode), mode=mode, look=look, width=width,
        height=height, font_size=opts.chat_render_font_size, fps=fps, smooth=opts.chat_render_smooth,
        cache_dir=cache_dir, lead=lead)
    ctx.log(f"✔ {out.name}  ({width}x{height}, {fps} fps, {CHAT_RENDER_LABELS[mode]}; "
            + ("starts together with the part" if lead or video else "starts at the first second of the chat")
            + ")")
    return out


def describe_chat_overlay(chat_json: Path, opts: JobOptions) -> str:
    """What drawing the overlay of this chat file will do, in plain words (to confirm before the long render)."""
    eng = sys.modules.get("luckytwitch_engine")
    _probe = getattr(eng, "probe_video", probe_video) if eng else probe_video

    info = read_chat_info(chat_json)
    video = find_part_video(chat_json)
    mode, _look, width, height, fps = chat_overlay_settings(opts, _probe(video) if video else None)
    base = chat_base_name(chat_json)
    lines = [
        " · ".join(x for x in (info.streamer, f"VOD {info.vod_id}" if info.vod_id else "") if x) or chat_json.name,
        f"Covers {fmt_hms(info.start)} to {fmt_hms(info.end)} of the VOD · {info.messages:,} messages",
        "",
        f"Video next to it: {video.name}" if video else "No video next to it, so the size and frame rate come from Options.",
        f"Overlay: {width}x{height}, {fps} fps, {CHAT_RENDER_LABELS[mode]}",
        f"File: {existing_chat_overlay_path(chat_json, mode).name}",
    ]
    if chat_lead_from_markers(chat_json, info) > 0:
        lines.append(f"Lined up to the fraction of a second with {base}.markers.json.")
    elif not chat_json.with_name(base + ".markers.json").is_file():
        lines.append(f"No {base}.markers.json: lined up to the whole second (up to 1 s ahead of the video).")
    lines.append("Emotes and badges are inside the file." if info.embedded
                 else "Emotes and badges are fetched from the internet while it draws.")
    return "\n".join(lines)


def chat_files_for_part(ctx: Ctx, tool: str, src: SourceInfo, opts: JobOptions, part: Part, total_parts: int,
                        dest: Path, real_start: float, real_end: float, workdir: Path) -> None:
    """
    The chat files of one finished part, next to it: the saved chat («.chat.json / .txt / .html») and / or the overlay
    video («.chat-overlay.mov / .mp4»). A failure here is only logged: the video itself is fine.
    """
    chat_fmt = opts.chat_format if opts.chat_format in CHAT_FORMATS else "json"
    vod_id = src.twitch_vod_id or ""
    cache = workdir / "chat_cache"
    lo, hi = ctx.span()

    def stage(a: float, b: float, label: str) -> None:  # a slice of this part's share of the progress bar
        ctx.stage(lo + (hi - lo) * a, lo + (hi - lo) * b, label)

    chat_json: Path | None = None  # the file the overlay is drawn from
    temp_json = False
    chat_failed = False
    eng = sys.modules.get("luckytwitch_engine")
    _dl_chat = getattr(eng, "download_chat", download_chat) if eng else download_chat
    _render_chat = getattr(eng, "render_chat", render_chat) if eng else render_chat
    _probe = getattr(eng, "probe_video", probe_video) if eng else probe_video

    try:
        if opts.chat:
            try:
                label = f"Chat for part {part.index}/{total_parts}"
                if opts.chat_render:
                    stage(0.0, 0.1, label)
                else:
                    ctx.relabel(label)
                chat_file = _dl_chat(
                    ctx, tool, vod_id, real_start, real_end,
                    dest.with_suffix(f".chat.{chat_fmt}"), opts.chat_embed, cache)
                ctx.log(t("✔ {name}  (chat from {start} to {end} of the VOD)").format(name=chat_file.name, start=fmt_hms(real_start), end=fmt_hms(real_end)))
                if chat_fmt == "json":
                    chat_json = chat_file
            except Cancelled:
                raise
            except EngineError as e:
                chat_failed = True
                ctx.log(t("Chat for part {part} failed (the video is fine): {error}").format(part=part.index, error=e))
        if not opts.chat_render:
            return
        if chat_failed:
            ctx.log(t("Chat overlay for part {part} skipped: the chat could not be downloaded.").format(part=part.index))
            return
        try:
            if chat_json is None:  # the saved chat is not a .json (or not wanted): the overlay needs its own copy
                stage(0.0, 0.1, f"Chat for the overlay of part {part.index}/{total_parts}")
                chat_json = _dl_chat(ctx, tool, vod_id, real_start, real_end,
                                     cache / f"part{part.index}.chat.json", False, cache)
                temp_json = True
            mode, look, width, height, fps = chat_overlay_settings(opts, _probe(dest))
            lead = max(0.0, real_start - math.floor(real_start))  # the chat file starts at a whole second
            stage(0.1, 1.0, f"Chat overlay for part {part.index}/{total_parts}")
            out = _render_chat(
                ctx, tool, chat_json, dest.with_suffix(".chat-overlay" + CHAT_RENDER_EXT[mode]), mode=mode, look=look,
                width=width, height=height, font_size=opts.chat_render_font_size, fps=fps,
                smooth=opts.chat_render_smooth, cache_dir=cache, lead=lead)
            ctx.log(t("✔ {name}  ({width}x{height}, {fps} fps, {label}; starts together with the part)").format(name=out.name, width=width, height=height, fps=fps, label=CHAT_RENDER_LABELS[mode]))
        except Cancelled:
            raise
        except EngineError as e:
            ctx.log(t("Chat overlay for part {part} failed (the video is fine): {error}").format(part=part.index, error=e))
    finally:
        if temp_json and chat_json is not None:
            chat_json.unlink(missing_ok=True)
