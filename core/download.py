"""
Download engines: full VOD, HLS segments, yt-dlp/ffmpeg execution, and MP4 timescale fix.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urljoin

import requests

from core.errors import Cancelled, EngineError
from core.i18n import t, tn
from core.planning import Part
from core.runtime import Ctx, _NO_WINDOW, _tool_env, find_tool
from core.source_info import YTDLP_MISSING
from core.timeutil import fmt_hms

if sys.version_info >= (3, 11):
    from typing import Any, TYPE_CHECKING
    if TYPE_CHECKING:
        from core.job import JobOptions


_FF_PROGRESS_KEYS = {"out_time_us", "out_time_ms", "total_size", "speed", "progress"}


class FfmpegProgress:
    """
    Reads the `-progress pipe:1` key=value lines of ffmpeg. feed(line) returns (fraction, text) at the end of
    each update block (text = "12.3 MiB · 2.9x · ETA 1:04:33"), otherwise None.
    """

    def __init__(self, total: float | None):
        self.total = total
        self.t: float | None = None
        self.size: float | None = None  # bytes
        self.speed: float | None = None

    def feed(self, line: str) -> tuple[float | None, str] | None:
        key, _, value = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms"):
            try:
                self.t = int(value) / 1_000_000
            except ValueError:
                pass
        elif key == "total_size":
            try:
                self.size = float(value)
            except ValueError:
                pass
        elif key == "speed":
            try:
                self.speed = float(value.strip().rstrip("x"))
            except ValueError:
                self.speed = None
        elif key == "progress" and self.t is not None:
            frac = min(max(self.t / self.total, 0.0), 1.0) if self.total else None
            bits = []
            if self.size:
                mib = self.size / (1024 * 1024)
                bits.append(f"{mib:.1f} MiB" if mib < 10 else f"{mib:.0f} MiB")
            if self.speed and self.speed > 0:
                bits.append(f"{self.speed:.1f}x")
                if self.total:
                    bits.append(f"ETA {fmt_hms(max(self.total - self.t, 0) / self.speed)}")
            return frac, " · ".join(bits)
        return None


# --------------------------------------------------------------------------- #
# MP4 movie timescale
# --------------------------------------------------------------------------- #
# Newer ffmpeg builds set the MP4 "movie timescale" to the least common multiple of the track timescales
# (720000 for 90 kHz video + 48 kHz audio) instead of 1000. The edit list lengths are then stored in
# 1/720000 s, and on a part longer than ~99 min they no longer fit in 32 bits. Premiere Pro's importer
# crashes on such files (QT::QTTrack::CalcTrim) although every video player opens them. Forcing 1000
# keeps the edit list (so audio and video stay in sync) and its numbers small.
MP4_MOVIE_TIMESCALE = 1000


def mp4_flags(container: str) -> list[str]:
    """ffmpeg output options that keep an MP4 readable by Premiere Pro. Empty for other containers."""
    return ["-movie_timescale", str(MP4_MOVIE_TIMESCALE)] if container.lower().lstrip(".") == "mp4" else []


def audio_out_container(opts: JobOptions) -> str:
    return opts.audio_format if opts.audio_format in AUDIO_FORMATS else "m4a"


def audio_codec_args(container: str) -> list[str]:
    """m4a: Twitch's AAC copied as it is. mp3: converted."""
    return ["-c:a", "libmp3lame", "-b:a", "192k"] if container == "mp3" else ["-c:a", "copy"]


def audio_only_options(opts: JobOptions) -> tuple[JobOptions, list[str]]:
    """The options with every video-only extra switched off, and the names of the ones that were on."""
    skipped = [label for key, label in AUDIO_SKIPPED if getattr(opts, key)]
    return replace(opts, **{key: False for key, _ in AUDIO_SKIPPED}), skipped


def mp4_movie_timescale(path: Path) -> int | None:
    """Movie timescale (mvhd) of an MP4 / MOV file, read from its header only. None if it cannot be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            total = f.tell()
            pos = 0
            while pos + 8 <= total:
                f.seek(pos)
                head = f.read(16)
                size, typ = int.from_bytes(head[:4], "big"), head[4:8]
                hdr = 8
                if size == 1 and len(head) >= 16:
                    size, hdr = int.from_bytes(head[8:16], "big"), 16
                elif size == 0:
                    size = total - pos
                if size < hdr:
                    return None
                if typ == b"moov":
                    f.seek(pos + hdr)
                    data = f.read(min(size - hdr, 1 << 20))  # mvhd is the first box inside moov
                    i = data.find(b"mvhd")
                    if i < 4:
                        return None
                    body = i + 4  # version(1) flags(3) then times
                    version = data[body]
                    off = body + (20 if version == 1 else 12)
                    return int.from_bytes(data[off:off + 4], "big")
                pos += size
    except OSError:
        return None
    return None


def run_ffmpeg(ctx: Ctx, args: list[str], total: float | None = None) -> str:
    """Run ffmpeg, report progress when `total` (seconds of output) is known."""
    eng = sys.modules.get("luckytwitch_engine")
    import core.tools
    _find = find_tool if find_tool is not getattr(core.tools, "find_tool", None) else (getattr(eng, "find_tool", find_tool) if eng else find_tool)
    ffmpeg = _find("ffmpeg")
    if not ffmpeg:
        raise EngineError(t("ffmpeg was not found. Install it and add it to PATH."))
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats"] + args
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    ctx.check_cancel()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )
    ctx.proc = proc
    errors: list[str] = []
    progress = FfmpegProgress(total)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.partition("=")[0] in _FF_PROGRESS_KEYS:
                parsed = progress.feed(line)
                if parsed and total:
                    ctx.report(parsed[0], parsed[1])
                    ctx.log_progress(parsed[0], parsed[1])
            elif line and "=" not in line.split(" ")[0]:
                errors.append(line)
        proc.wait()
    finally:
        ctx.proc = None
    ctx.check_cancel()
    if proc.returncode != 0:
        raise EngineError("ffmpeg failed:\n" + "\n".join(errors[-8:]))
    return "\n".join(errors)


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #
PROGRESS_TEMPLATE = (
    "download:LTPROG|%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s"
    "|%(progress.total_bytes_estimate)s|%(progress.fragment_index)s|%(progress.fragment_count)s"
    "|%(progress.speed)s|%(progress.eta)s"
)


def _num(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:  # "NA" = field not available
        return None


def parse_progress(line: str) -> tuple[float | None, str] | None:
    """One line printed by yt-dlp with PROGRESS_TEMPLATE -> (fraction or None, text), else None."""
    if not line.startswith("LTPROG|"):
        return None
    fields = line.split("|")
    if len(fields) < 9:
        return None
    dl, total, est, f_idx, f_cnt, speed, eta = (_num(x) for x in fields[2:9])
    frac = None
    if f_cnt:
        frac = (f_idx or 0) / f_cnt
    elif total or est:
        frac = (dl or 0) / (total or est)  # type: ignore[operator]
    bits = []  # the percentage is shown by the GUI itself
    if dl:
        bits.append(f"{dl / 1048576:.0f} MiB")
    if speed:
        bits.append(f"{speed / 1048576:.1f} MiB/s")
    if eta is not None:
        bits.append(f"ETA {fmt_hms(eta)}")
    return frac, " · ".join(bits)


# Sections are downloaded by ffmpeg (yt-dlp hands the job over) and yt-dlp reports nothing
# while it does, so we read ffmpeg's own stats lines:  "size=  1234KiB time=00:01:23.45 ... speed=12.3x"
_FF_TIME = re.compile(r"\btime=(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_FF_SIZE = re.compile(r"\bL?size=\s*(\d+(?:\.\d+)?)\s*([kKMG]i?B)\b")
_FF_SPEED = re.compile(r"\bspeed=\s*(\d+(?:\.\d+)?)x")


def parse_ffmpeg_stats(line: str, total: float | None) -> tuple[float | None, str] | None:
    """One ffmpeg stats line -> (fraction of `total` seconds, text), or None if it is not one."""
    m = _FF_TIME.search(line)
    if not m:
        return None
    t = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    frac = min(t / total, 1.0) if total else None
    bits = []
    if frac is None:
        bits.append(fmt_hms(t))
    ms = _FF_SIZE.search(line)
    if ms:
        value, unit = float(ms[1]), ms[2].lower()
        mib = value / 1024 if unit.startswith("k") else value * 1024 if unit.startswith("g") else value
        bits.append(f"{mib:.1f} MiB" if mib < 10 else f"{mib:.0f} MiB")
    mp = _FF_SPEED.search(line)
    if mp:
        speed = float(mp[1])
        bits.append(f"{speed:.1f}x")
        if total and speed > 0:
            bits.append(f"ETA {fmt_hms(max(total - t, 0) / speed)}")
    return frac, " · ".join(bits)


def _out_template(folder: Path, stem: str) -> str:
    """yt-dlp output template; '%' in the folder name must be escaped."""
    return str(folder).replace("%", "%%") + os.sep + stem + ".%(ext)s"


def _folder_size(folder: Path) -> int:
    total = 0
    try:
        for p in folder.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def _watch_folder(ctx: Ctx, folder: Path, stop: threading.Event, last_real: list[float]) -> None:
    """Fallback progress: if the downloader reports nothing for a while, show how much has landed on disk."""
    samples: list[tuple[float, int]] = []
    while not stop.wait(1.0):
        now = time.monotonic()
        size = _folder_size(folder)
        samples = (samples + [(now, size)])[-8:]
        if now - last_real[0] < 5 or size <= 0:
            continue
        t0, s0 = samples[0]
        speed = (size - s0) / (now - t0) if now > t0 else 0
        text = f"{size / 1048576:.0f} MiB" + (f" · {speed / 1048576:.1f} MiB/s" if speed > 0 else "")
        ctx.report(None, text)
        ctx.log_progress(None, text)


def run_ytdlp(
    ctx: Ctx,
    args: list[str],
    threads: int,
    total_secs: float | None = None,
    watch_dir: Path | None = None,
    format_id: str | None = None,
    rate_limit: str | None = None,
    cookies_browser: str | None = None,
) -> None:
    """
    Run the yt-dlp binary, forwarding progress to ctx. Cancel kills the whole process tree.
    total_secs: length of what is being downloaded (sections) so ffmpeg's stats become a percentage.
    watch_dir: folder where the download lands, used as a fallback progress source.
    """
    eng = sys.modules.get("luckytwitch_engine")
    import core.tools
    _find = find_tool if find_tool is not getattr(core.tools, "find_tool", None) else (getattr(eng, "find_tool", find_tool) if eng else find_tool)
    _subp = getattr(eng, "subprocess", subprocess) if eng else subprocess
    ytdlp = _find("yt-dlp")
    if not ytdlp:
        raise EngineError(YTDLP_MISSING)
    quality_args = ["-f", format_id] if format_id else ["-S", "res,fps,tbr"]
    cmd = [
        ytdlp,
        *quality_args,
        "--concurrent-fragments", str(max(1, threads)),
        "--retries", "10",
        "--fragment-retries", "10",
        "--continue",
        "--quiet", "--progress", "--newline",
        "--progress-template", PROGRESS_TEMPLATE,
    ]
    if total_secs:
        # --quiet makes yt-dlp run ffmpeg with -loglevel quiet; -stats brings its progress line back.
        cmd += ["--downloader-args", "ffmpeg:-stats"]
    if rate_limit and str(rate_limit).strip():
        cmd += ["--limit-rate", str(rate_limit).strip()]
    if cookies_browser and str(cookies_browser).strip().lower() not in ("none", "disabled", ""):
        cmd += ["--cookies-from-browser", str(cookies_browser).strip().lower()]
    ffmpeg = _find("ffmpeg")
    if ffmpeg:
        cmd += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
    cmd += args
    ctx.check_cancel()
    try:
        proc = _subp.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_tool_env(),
            creationflags=_NO_WINDOW,
            start_new_session=sys.platform != "win32",
        )
    except OSError as e:
        raise EngineError(t("Could not run yt-dlp:\n{error}").format(error=e)) from e
    ctx.proc = proc
    last_real = [time.monotonic()]
    stop = threading.Event()
    watcher = None
    if watch_dir is not None:
        watcher = threading.Thread(target=_watch_folder, args=(ctx, watch_dir, stop, last_real), daemon=True)
        watcher.start()
    tail: list[str] = []
    try:
        assert proc.stdout is not None
        # text mode turns the "\r" that ffmpeg uses between stats updates into line breaks
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            parsed = parse_progress(line) or parse_ffmpeg_stats(line, total_secs)
            if parsed:
                last_real[0] = time.monotonic()
                ctx.report(*parsed)
                ctx.log_progress(*parsed)
                continue
            tail.append(line)
            if line.startswith(("WARNING", "ERROR")):
                ctx.log(t("yt-dlp: {line}").format(line=line))
        proc.wait()
    finally:
        stop.set()
        if watcher:
            watcher.join(timeout=2)
        ctx.proc = None
    ctx.check_cancel()
    if proc.returncode != 0:
        raise EngineError("Download failed:\n" + "\n".join(tail[-8:]))


AUDIO_FORMATS = ("m4a", "mp3")
MEDIA_EXTS = {".mp4", ".mkv", ".ts", ".webm", ".mov", ".m4v", ".m4a", ".mp3"}
AUDIO_SKIPPED = (  # settings that need a video track -> what the log calls them
    ("exact", "frame-exact cuts"),
    ("premiere_xml", "Premiere XML markers"),
    ("premiere_plugin", "Premiere plugin markers"),
    ("game_markers", "game markers"),
    ("muted_markers", "muted markers"),
    ("chat_render", "chat overlay video"),
)


def _find_media(folder: Path) -> Path | None:
    files = [p for p in folder.glob("*") if p.suffix.lower() in MEDIA_EXTS and p.is_file()]
    return max(files, key=lambda p: p.stat().st_size) if files else None


def download_full(
    ctx: Ctx,
    url: str,
    workdir: Path,
    threads: int,
    format_id: str | None = None,
    rate_limit: str | None = None,
    cookies_browser: str | None = None,
    **kwargs: Any,
) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    done = workdir / "full.done"
    existing = _find_media(workdir)
    if done.exists() and existing:
        ctx.log(t("Full VOD already downloaded in the work folder, reusing it."))
        return existing
    kw = {}
    if format_id is not None:
        kw["format_id"] = format_id
    if rate_limit and str(rate_limit).strip():
        kw["rate_limit"] = str(rate_limit).strip()
    if cookies_browser and str(cookies_browser).strip().lower() not in ("none", "disabled", ""):
        kw["cookies_browser"] = str(cookies_browser).strip().lower()
    eng = sys.modules.get("luckytwitch_engine")
    _ytdlp = getattr(eng, "run_ytdlp", run_ytdlp) if eng else run_ytdlp
    _ytdlp(ctx, ["-o", _out_template(workdir, "full"), url], threads, **kw)
    media = _find_media(workdir)
    if not media:
        raise EngineError(t("yt-dlp finished but no video file was found."))
    done.write_text("ok")
    return media


def download_section(
    ctx: Ctx,
    url: str,
    part: Part,
    workdir: Path,
    threads: int,
    exact: bool,
    format_id: str | None = None,
    rate_limit: str | None = None,
    cookies_browser: str | None = None,
    **kwargs: Any,
) -> Path:
    pdir = workdir / f"part{part.index}"
    if pdir.exists():
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)
    args = ["-o", _out_template(pdir, "part"), "--download-sections", f"*{part.start:.3f}-{part.end:.3f}"]
    if exact:
        args.append("--force-keyframes-at-cuts")
    kw = {}
    if format_id is not None:
        kw["format_id"] = format_id
    if rate_limit and str(rate_limit).strip():
        kw["rate_limit"] = str(rate_limit).strip()
    if cookies_browser and str(cookies_browser).strip().lower() not in ("none", "disabled", ""):
        kw["cookies_browser"] = str(cookies_browser).strip().lower()
    eng = sys.modules.get("luckytwitch_engine")
    _ytdlp = getattr(eng, "run_ytdlp", run_ytdlp) if eng else run_ytdlp
    _ytdlp(ctx, args + [url], threads, total_secs=part.duration, watch_dir=pdir, **kw)
    media = _find_media(pdir)
    if not media or media.stat().st_size < 4096:
        raise EngineError(t("Part {index} ({start}–{end}) came out empty. Try again, or use strategy «full» to download the whole VOD and split it.").format(index=part.index, start=fmt_hms(part.start), end=fmt_hms(part.end)))
    return media


# --------------------------------------------------------------------------- #
# Sections by whole HLS segments (no ffmpeg -ss, so the real start is known)
# --------------------------------------------------------------------------- #
HLS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class Segment:
    start: float  # seconds from the start of the VOD
    end: float
    url: str
    # fMP4 playlists: (absolute init-section URL, "length@offset" or None) from #EXT-X-MAP
    init: tuple[str, str | None] | None = None
    # "length@offset" from #EXT-X-BYTERANGE, with the offset always explicit
    byterange: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def _hls_attrs(text: str) -> dict[str, str]:
    """Attributes of a tag like  URI="x",BYTERANGE="10@0"  ->  {"URI": "x", "BYTERANGE": "10@0"}."""
    return {k.upper(): v.strip('"') for k, v in re.findall(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)', text)}


def parse_hls_playlist(text: str, base_url: str) -> list[Segment]:
    """
    Parse a finished (VOD) media playlist into segments with cumulative times.
    Supports fMP4 playlists (#EXT-X-MAP init section) and byte ranges.
    Raises ValueError for anything where segment time = cumulative duration is not safe
    (live stream, encryption, discontinuities, master playlist).
    """
    segments: list[Segment] = []
    pending: float | None = None
    pending_range: tuple[int, int | None] | None = None  # (length, offset or None)
    init: tuple[str, str | None] | None = None
    next_offset: dict[str, int] = {}  # resource URL -> where the next implicit byte range starts
    t = 0.0
    ended = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            tag = line.split(":", 1)[0]
            rest = line.split(":", 1)[1] if ":" in line else ""
            if tag in ("#EXT-X-KEY", "#EXT-X-SESSION-KEY", "#EXT-X-DISCONTINUITY", "#EXT-X-STREAM-INF"):
                raise ValueError(f"unsupported playlist tag {tag}")
            if tag == "#EXT-X-MAP":
                attrs = _hls_attrs(rest)
                if "URI" not in attrs:
                    raise ValueError(f"bad line: {line}")
                init = (urljoin(base_url, attrs["URI"]), attrs.get("BYTERANGE"))
            elif tag == "#EXT-X-BYTERANGE":
                try:
                    length_s, _, offset_s = rest.partition("@")
                    pending_range = (int(length_s), int(offset_s) if offset_s else None)
                except ValueError as e:
                    raise ValueError(f"bad line: {line}") from e
            elif tag == "#EXT-X-ENDLIST":
                ended = True
            elif tag == "#EXTINF":
                try:
                    pending = float(rest.split(",", 1)[0])
                except (ValueError, IndexError) as e:
                    raise ValueError(f"bad line: {line}") from e
            continue
        if pending is None:
            raise ValueError("segment without #EXTINF")
        seg_url = urljoin(base_url, line)
        byterange = None
        if pending_range is not None:
            length, offset = pending_range
            if offset is None:
                offset = next_offset.get(seg_url, 0)
            next_offset[seg_url] = offset + length
            byterange = f"{length}@{offset}"
            pending_range = None
        segments.append(Segment(t, t + pending, seg_url, init, byterange))
        t += pending
        pending = None
    if not ended:
        raise ValueError("playlist is not finished (no #EXT-X-ENDLIST)")
    if not segments:
        raise ValueError("playlist has no segments")
    return segments


def select_segments(segments: list[Segment], start: float, end: float) -> tuple[int, int]:
    """
    Index range (first, last) of the segments that cover [start, end].
    The first segment is the one containing `start`, the last one the one containing `end`
    (an end exactly on a boundary belongs to the segment that ends there). Times outside the VOD are clamped.
    """
    eps = 1e-6
    total = segments[-1].end
    if end <= start:
        raise ValueError("empty time range")
    if start >= total - eps:
        raise ValueError("the part starts after the end of the VOD")
    first = 0
    for i, seg in enumerate(segments):
        if seg.start <= start + eps:
            first = i
        else:
            break
    last = len(segments) - 1
    for i, seg in enumerate(segments):
        if seg.end >= end - eps:
            last = i
            break
    return first, max(first, last)


def write_local_playlist(segments: list[Segment], dest: Path) -> None:
    target = max(1, math.ceil(max(s.duration for s in segments)))
    needs_map = any(s.init for s in segments)
    lines = [
        "#EXTM3U",
        f"#EXT-X-VERSION:{7 if needs_map else 4 if any(s.byterange for s in segments) else 3}",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    current_init = None
    for s in segments:
        if s.init and s.init != current_init:
            uri, brange = s.init
            lines.append(f'#EXT-X-MAP:URI="{uri}"' + (f',BYTERANGE="{brange}"' if brange else ""))
            current_init = s.init
        lines.append(f"#EXTINF:{s.duration:.3f},")
        if s.byterange:
            lines.append(f"#EXT-X-BYTERANGE:{s.byterange}")
        lines.append(s.url)
    lines.append("#EXT-X-ENDLIST")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_playlist_url(ctx: Ctx, url: str, format_id: str | None = None) -> str:
    """The media playlist (.m3u8) yt-dlp would download, chosen with the same quality flags."""
    eng = sys.modules.get("luckytwitch_engine")
    import core.tools
    _find = find_tool if find_tool is not getattr(core.tools, "find_tool", None) else (getattr(eng, "find_tool", find_tool) if eng else find_tool)
    _subp = getattr(eng, "subprocess", subprocess) if eng else subprocess
    ytdlp = _find("yt-dlp")
    if not ytdlp:
        raise EngineError(YTDLP_MISSING)
    ctx.check_cancel()
    quality_args = ["-f", format_id] if format_id else ["-S", "res,fps,tbr"]
    try:
        proc = _subp.run(
            [ytdlp, "-g", *quality_args, "--no-warnings", url],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_tool_env(), creationflags=_NO_WINDOW, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise EngineError(t("Could not get the playlist address: {error}").format(error=e)) from e
    ctx.check_cancel()
    urls = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if proc.returncode != 0 or len(urls) != 1:
        raise EngineError(tn("yt-dlp gave {n} address instead of one playlist", "yt-dlp gave {n} addresses instead of one playlist", len(urls)))
    if not urls[0].startswith("http") or ".m3u8" not in urls[0].split("?", 1)[0]:
        raise EngineError(t("the video address is not an HLS playlist"))
    return urls[0]


def download_section_aligned(
    ctx: Ctx, url: str, part: Part, workdir: Path, format_id: str | None = None, audio_only: bool = False
) -> tuple[Path, float, float] | None:
    """
    Download [part.start, part.end] as whole HLS segments with a single ffmpeg stream copy and NO -ss.
    Returns (file, real_start, real_end) in VOD time: the file starts at a segment boundary at or
    before part.start (never after) and the caller knows exactly where.
    Returns None when this method cannot be used (the caller then uses the old method).
    """
    try:
        kw = {"format_id": format_id} if format_id is not None else {}
        eng = sys.modules.get("luckytwitch_engine")
        _get_pl = getattr(eng, "get_playlist_url", get_playlist_url) if eng else get_playlist_url
        _run_ff = getattr(eng, "run_ffmpeg", run_ffmpeg) if eng else run_ffmpeg

        playlist_url = _get_pl(ctx, url, **kw)
        resp = requests.get(playlist_url, headers={"User-Agent": HLS_USER_AGENT}, timeout=30)
        resp.raise_for_status()
        segments = parse_hls_playlist(resp.text, playlist_url)
        first, last = select_segments(segments, part.start, part.end)
        chosen = segments[first : last + 1]
        real_start, real_end = chosen[0].start, min(chosen[-1].end, segments[-1].end)

        pdir = workdir / f"part{part.index}"
        if pdir.exists():
            shutil.rmtree(pdir)
        pdir.mkdir(parents=True)
        local = pdir / "part.m3u8"
        write_local_playlist(chosen, local)
        out = pdir / ("part.m4a" if audio_only else "part.mp4")
        map_args = ["-map", "0:a:0"] if audio_only else ["-map", "0:v:0", "-map", "0:a?"]
        _run_ff(
            ctx,
            [
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-i", str(local),
                *map_args,
                "-c", "copy", *mp4_flags("mp4"), "-f", "mp4", str(out),
            ],
            total=real_end - real_start,
        )
        if not out.exists() or out.stat().st_size < 4096:
            raise EngineError(t("the downloaded file is empty"))
    except Cancelled:
        raise
    except (EngineError, requests.RequestException, ValueError, OSError) as e:
        # Keep every line of the message (ffmpeg's real error comes after the "ffmpeg failed:" header).
        reason = " | ".join(ln.strip() for ln in str(e).splitlines() if ln.strip())[:500] or type(e).__name__
        ctx.log(t("Could not use the segment download ({reason}); using the old method. Markers may be up to 10 s off.").format(reason=reason))
        return None
    return out, real_start, real_end
