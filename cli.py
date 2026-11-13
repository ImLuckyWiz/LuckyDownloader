#!/usr/bin/env python3
"""
LuckyDownloader CLI - Command-line interface for LuckyDownloader.

A headless, lightweight interface to download and trim VODs and videos
using LuckyDownloader's core engine. Compatible with Google Colab,
Linux/macOS/Windows servers, and automated pipelines without any GUI dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Ensure UTF-8 output across all consoles and environments (Windows cmd/powershell, Colab, CI)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.config import TWITCH_CLIENT_ID, make_client
from core.errors import Cancelled, EngineError
from core.finalize import cut_exact, run_job, split_copy
from core.i18n import t
from core.job import Job, JobOptions
from core.paths import read_bundled_version
from core.planning import make_plan
from core.playlist import expand_playlist_jobs, parse_item_range
from core.providers import Capability
from core.runtime import Ctx, find_tool
from core.source_info import (
    QUALITY_BEST,
    PlaylistInfo,
    describe_quality,
    get_source_info,
    resolve_format,
)
from core.timeutil import fmt_hms
from core.tools import ensure_tools
from core.twitch_api import TwitchClient


class ConsoleReporter:
    """Console reporter for logging and progress bars without GUI dependencies."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.last_pct = -1
        self.last_label = ""
        self.last_print_time = 0.0
        self.is_tty = sys.stdout.isatty()

    def log(self, msg: str) -> None:
        if self.quiet:
            return
        if self.last_pct >= 0 and self.is_tty:
            sys.stdout.write("\n")
            self.last_pct = -1
        print(f"[LuckyDownloader] {msg}", flush=True)

    def progress(self, frac: float, text: str) -> None:
        if self.quiet:
            return
        now = time.monotonic()
        if frac < 0:
            if self.is_tty:
                sys.stdout.write(f"\r[LuckyDownloader] {text} ...\033[K")
                sys.stdout.flush()
            else:
                if text != self.last_label or (now - self.last_print_time) >= 10.0:
                    self.last_label = text
                    self.last_print_time = now
                    print(f"[LuckyDownloader] {text} ...", flush=True)
            return

        pct = int(min(max(frac, 0.0), 1.0) * 100)

        # In non-TTY environments (Google Colab, redirected logs, CI),
        # only emit progress on 5% milestones, stage changes, or after 5 seconds to avoid log spam.
        if not self.is_tty:
            should_print = (
                pct != self.last_pct
                and (pct % 5 == 0 or pct == 100 or text != self.last_label or (now - self.last_print_time) >= 5.0)
            )
            if should_print:
                self.last_pct = pct
                self.last_label = text
                self.last_print_time = now
                print(f"[LuckyDownloader] [{pct:3d}%] {text}", flush=True)
            return

        # Interactive terminal: draw a neat progress bar in place
        bar_len = 25
        filled = int(bar_len * (pct / 100.0))
        bar = "=" * filled + (">" if filled < bar_len else "") + " " * (bar_len - filled - (1 if filled < bar_len else 0))
        sys.stdout.write(f"\r[LuckyDownloader] [{bar}] {pct:3d}%  {text[:50]}\033[K")
        sys.stdout.flush()
        self.last_pct = pct
        if pct >= 100:
            sys.stdout.write("\n")
            self.last_pct = -1


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the CLI argument parser."""
    version = read_bundled_version() or "dev"
    parser = argparse.ArgumentParser(
        prog="luckydownloader-cli",
        description="LuckyDownloader CLI - Fast headless VOD & video downloader with segment trimming.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="",
        help="VOD or video URL to download (Twitch, YouTube, etc.).",
    )
    parser.add_argument(
        "-c",
        "--cuts",
        default="",
        help='Cut points string (e.g. "0:00:00 - 1:18:55 - end" or "0:00 - 30:00 ; 1:00:00 - end"). '
        "Defaults to downloading the entire video.",
    )
    parser.add_argument(
        "-o",
        "--out",
        default="./downloads",
        help="Target output directory (default: ./downloads).",
    )
    parser.add_argument(
        "--template",
        "--name-template",
        dest="name_template",
        default="",
        help='Filename template for downloaded parts (e.g. "{streamer} - {title} - {game} - part{n}"). '
        'Defaults to "{streamer} - {date} - {id} - part{n}".',
    )
    parser.add_argument(
        "-q",
        "--quality",
        default=QUALITY_BEST,
        help=f'Quality preset or resolution (default: "{QUALITY_BEST}", or "1080p60", "720p60", "audio", etc.).',
    )
    parser.add_argument(
        "-s",
        "--strategy",
        choices=["auto", "sections", "full"],
        default="auto",
        help='Download strategy: "auto" (decides based on coverage), "sections" (download only selected parts), '
        'or "full" (download full stream, then cut). (default: auto).',
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Re-encode cut points for frame-exact trimming (slower).",
    )
    parser.add_argument(
        "--format",
        "--container",
        dest="container",
        choices=["mp4", "mkv"],
        default="mp4",
        help="Output video container format (default: mp4).",
    )
    parser.add_argument(
        "--audio-format",
        choices=["m4a", "mp3"],
        default="m4a",
        help="Audio format when quality is set to audio-only (default: m4a).",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Download Twitch chat for each downloaded part (Twitch VODs only).",
    )
    parser.add_argument(
        "--chat-format",
        choices=["json", "txt", "html"],
        default="json",
        help="Format for downloaded Twitch chat (default: json).",
    )
    parser.add_argument(
        "--chapters",
        action="store_true",
        help="Download and embed Twitch stream markers / chapters into the video.",
    )
    parser.add_argument(
        "--keep-full",
        action="store_true",
        help="Keep the uncut full VOD file when using full download strategy.",
    )
    parser.add_argument(
        "--clean-title",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clean promotional tags and bot commands from stream titles (default: True).",
    )
    parser.add_argument(
        "--subfolders",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Organize downloads into streamer/stream subfolders (default: True).",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=8,
        help="Number of download threads for segment fetching (default: 8).",
    )
    parser.add_argument(
        "--rate-limit",
        default="",
        help='Bandwidth rate limit for yt-dlp (e.g. "5M", "500K").',
    )
    parser.add_argument(
        "--cookies-browser",
        default="",
        help='Browser to extract cookies from for yt-dlp (e.g. "chrome", "firefox").',
    )
    parser.add_argument(
        "--local-file",
        default="",
        help="Path to a local video/audio file to split instead of downloading a URL.",
    )
    parser.add_argument(
        "--batch",
        default="",
        help="Path to a batch manifest (.json or .txt) of URLs/tasks to process.",
    )
    parser.add_argument(
        "--download-archive",
        default="",
        help="Path to a yt-dlp download archive file to skip already-downloaded items.",
    )
    parser.add_argument(
        "--items",
        default="all",
        help='Playlist/channel item selection (e.g. "1-5,8" or "all", default: all).',
    )
    parser.add_argument(
        "--premiere-xml",
        action="store_true",
        help="Export Premiere Pro XML markers.",
    )
    parser.add_argument(
        "--premiere-json",
        action="store_true",
        help="Export Premiere Pro CEP .markers.json sidecar.",
    )
    parser.add_argument(
        "--game-markers",
        action="store_true",
        help="Include Twitch game/category changes in Premiere markers.",
    )
    parser.add_argument(
        "--muted-markers",
        action="store_true",
        help="Include muted audio segment markers.",
    )
    parser.add_argument(
        "--chat-render",
        action="store_true",
        help="Render Twitch chat overlay video.",
    )
    parser.add_argument(
        "--no-update-tools",
        action="store_true",
        help="Skip online yt-dlp update checks when verifying tools.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect VOD metadata, parse cut points, display the plan and exit without downloading.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-essential log messages.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {version}",
        help="Show version and exit.",
    )
    return parser


def _resolve_twitch_client() -> TwitchClient | None:
    """Resolve Twitch API client from config.json or LUCKYDOWNLOADER_TWITCH_TOKEN."""
    client = make_client()
    if client is not None:
        return client
    token = os.environ.get("LUCKYDOWNLOADER_TWITCH_TOKEN", "").strip()
    if token:
        return TwitchClient(TWITCH_CLIENT_ID, access_token=token)
    return None


def _probe_duration(path: Path) -> float:
    """Return media duration in seconds via ffprobe, or 0.0 if unavailable."""
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0 and res.stdout.strip():
            return max(0.0, float(res.stdout.strip()))
    except Exception:
        pass
    return 0.0


def _build_job_options(args: argparse.Namespace, cut_text: str) -> JobOptions:
    """Build JobOptions from parsed CLI arguments."""
    opts_kwargs: dict = {}
    if args.name_template:
        opts_kwargs["name_template"] = args.name_template
        opts_kwargs["generic_name_template"] = args.name_template

    return JobOptions(
        cut_text=cut_text,
        out_dir=os.path.abspath(args.out),
        container=args.container,
        strategy=args.strategy,
        exact=args.exact,
        keep_full=args.keep_full,
        threads=args.threads,
        chapters=args.chapters,
        clean_title=args.clean_title,
        chat=args.chat,
        chat_format=args.chat_format,
        chat_render=args.chat_render,
        premiere_xml=args.premiere_xml,
        premiere_plugin=args.premiere_json,
        game_markers=args.game_markers,
        muted_markers=args.muted_markers,
        quality=args.quality,
        audio_format=args.audio_format,
        rate_limit=args.rate_limit or "",
        cookies_browser=args.cookies_browser or "",
        subfolders=args.subfolders,
        download_archive=args.download_archive or "",
        **opts_kwargs,
    )


def _needs_twitch_client(args: argparse.Namespace) -> bool:
    return bool(
        args.chapters
        or args.game_markers
        or args.muted_markers
        or args.premiere_xml
        or args.premiere_json
        or args.chat
        or args.chat_render
    )


def _run_local_cut(args: argparse.Namespace, ctx: Ctx, reporter: ConsoleReporter) -> int:
    """Split or trim a local video/audio file using core.finalize.split_copy or cut_exact."""
    local_path = Path(args.local_file).expanduser().resolve()
    if not local_path.is_file():
        raise EngineError(t("Local file not found: {path}", path=local_path))

    duration = _probe_duration(local_path)
    cut_text = (args.cuts or "").strip() or "0:00:00 - end"
    plan = make_plan(cut_text, duration, "full")

    reporter.log(f"Local file: {local_path.name}")
    if duration > 0:
        reporter.log(f"Duration: {fmt_hms(duration)}")
    reporter.log(f"Plan: {len(plan.parts)} part(s)")
    for p in plan.parts:
        part_dur = fmt_hms(p.end - p.start) if p.end > p.start else "end"
        reporter.log(f"  Part {p.index}: {fmt_hms(p.start)} -> {fmt_hms(p.end)} ({part_dur})")

    if args.dry_run:
        reporter.log("Dry run finished successfully. No files were written.")
        return 0

    out_dir = Path(os.path.abspath(args.out))
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = args.audio_format if args.quality == "audio" else args.container

    with tempfile.TemporaryDirectory(prefix=".lucky_cut_", dir=str(out_dir)) as tmp:
        workdir = Path(tmp)
        if args.exact:
            for part in plan.parts:
                seg_path = cut_exact(ctx, local_path, part, ext, workdir)
                dest = out_dir / f"{local_path.stem} - part{part.index}.{ext}"
                part_dest = dest.with_name(dest.name + ".part")
                shutil.move(str(seg_path), str(part_dest))
                os.replace(part_dest, dest)
                reporter.log(f"Saved: {dest}")
        else:
            segments = split_copy(
                ctx,
                local_path,
                plan.parts,
                duration,
                ext,
                workdir,
                audio_only=(args.quality == "audio"),
            )
            for part in plan.parts:
                seg_path, _, _ = segments[part.index]
                dest = out_dir / f"{local_path.stem} - part{part.index}.{ext}"
                part_dest = dest.with_name(dest.name + ".part")
                if seg_path.resolve() == local_path:
                    shutil.copy2(str(seg_path), str(part_dest))
                else:
                    shutil.move(str(seg_path), str(part_dest))
                os.replace(part_dest, dest)
                reporter.log(f"Saved: {dest}")

    reporter.log("Local cut completed successfully!")
    return 0


def _run_batch(args: argparse.Namespace, reporter: ConsoleReporter) -> int:
    """Execute a batch manifest (.json or .txt) of download/cut tasks."""
    manifest_path = Path(args.batch).expanduser().resolve()
    if not manifest_path.is_file():
        raise EngineError(t("Batch manifest not found: {path}", path=manifest_path))

    tasks: list[dict] = []
    if manifest_path.suffix.lower() == ".json":
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = raw.get("tasks", []) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            raise EngineError(t("Batch JSON must be a list of tasks or {'tasks': [...]}."))
        for item in items:
            if isinstance(item, str):
                tasks.append({"url": item})
            elif isinstance(item, dict):
                tasks.append(item)
    else:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "|" in s:
                u, c = s.split("|", 1)
                tasks.append({"url": u.strip(), "cuts": c.strip()})
            else:
                tasks.append({"url": s})

    if not tasks:
        reporter.log("Batch manifest is empty.")
        return 0

    reporter.log(f"Running batch manifest: {len(tasks)} task(s)")
    failures = 0
    for idx, task in enumerate(tasks, 1):
        target = str(task.get("local_file") or task.get("url") or "").strip()
        if not target:
            continue
        reporter.log(f"--- Batch [{idx}/{len(tasks)}]: {target} ---")
        task_argv: list[str] = []
        if task.get("local_file"):
            task_argv.extend(["--local-file", str(task["local_file"])])
        else:
            task_argv.append(str(task["url"]))

        cuts = str(task.get("cuts") or args.cuts or "").strip()
        if cuts:
            task_argv.extend(["-c", cuts])
        task_argv.extend(["-o", str(task.get("out") or args.out)])
        task_argv.extend(["-q", str(task.get("quality") or args.quality)])
        if task.get("template") or args.name_template:
            task_argv.extend(["--template", str(task.get("template") or args.name_template)])
        if args.dry_run:
            task_argv.append("--dry-run")
        if args.quiet:
            task_argv.append("--quiet")
        if args.no_update_tools:
            task_argv.append("--no-update-tools")
        if args.download_archive:
            task_argv.extend(["--download-archive", args.download_archive])

        rc = main(task_argv)
        if rc != 0:
            failures += 1

    return 0 if failures == 0 else 2


def main(argv: list[str] | None = None) -> int:
    """Main CLI execution routine."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    cut_local_subcmd = bool(raw_argv and raw_argv[0] == "cut-local")
    if cut_local_subcmd:
        raw_argv = raw_argv[1:]

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    if cut_local_subcmd and not args.local_file and args.url:
        args.local_file = args.url
        args.url = ""

    if not args.url and not args.local_file and not args.batch:
        parser.print_help()
        return 1

    reporter = ConsoleReporter(quiet=args.quiet)
    ctx = Ctx(log=reporter.log, progress=reporter.progress)

    try:
        if args.batch:
            return _run_batch(args, reporter)

        if not args.dry_run:
            reporter.log("Verifying tools (ffmpeg, yt-dlp)...")
            ensure_tools(ctx, update_ytdlp=not args.no_update_tools)

        if args.local_file:
            return _run_local_cut(args, ctx, reporter)

        reporter.log(f"Fetching metadata for: {args.url}")
        src = get_source_info(args.url, cookies_browser=args.cookies_browser or None)

        if isinstance(src, PlaylistInfo):
            reporter.log(f"Playlist: {src.title} ({len(src.entries)} item(s))")
            indices = parse_item_range(args.items or "all", len(src.entries))
            picked = [item for item in src.entries if item.index in indices] if indices else list(src.entries)
            reporter.log(f"Selected {len(picked)} item(s) for processing.")
            if args.dry_run:
                for item in picked:
                    reporter.log(f"  [{item.index}] {item.title} ({item.url})")
                reporter.log("Dry run finished successfully. No files were downloaded.")
                return 0
            opts = _build_job_options(args, cut_text="")
            jobs = expand_playlist_jobs(
                src,
                picked,
                opts,
                skip_existing=bool(args.download_archive),
                archive_file=args.download_archive or None,
            )
            for idx, job in enumerate(jobs, 1):
                reporter.log(f"Starting playlist item {idx}/{len(jobs)}: {job.source.title}")
                run_job(job, ctx)
            reporter.log("Playlist download completed successfully!")
            return 0

        reporter.log(f"Title: {src.title or 'Unknown'}")
        if src.uploader:
            reporter.log(f"Uploader: {src.uploader}")
        if src.duration and src.duration > 0:
            reporter.log(f"Duration: {fmt_hms(src.duration)}")

        cut_text = (args.cuts or "").strip()
        if not cut_text:
            if src.has_capability(Capability.TIMELINE) or (src.duration and src.duration > 0):
                cut_text = "0:00:00 - end"
            else:
                cut_text = ""

        # Validate and build the cut plan
        if cut_text:
            plan = make_plan(cut_text, src.duration, args.strategy, threshold=0.6)
        else:
            from core.planning import Part, Plan
            dur = max(1.0, float(src.duration or 1.0))
            plan = Plan(parts=[Part(index=1, start=0.0, end=dur)], strategy="full", coverage=1.0, duration=src.duration or 0.0)

        # Print plan summary
        reporter.log(f"Plan: {len(plan.parts)} part(s), coverage: {plan.coverage * 100:.1f}%")
        reporter.log(f"Strategy: {plan.strategy} ({'Full VOD then split' if plan.strategy == 'full' else 'Direct section downloads'})")
        for p in plan.parts:
            part_dur = fmt_hms(p.end - p.start)
            reporter.log(f"  Part {p.index}: {fmt_hms(p.start)} -> {fmt_hms(p.end)} ({part_dur})")

        fmt = resolve_format(src.formats, args.quality)
        if fmt:
            reporter.log(f"Quality: {describe_quality(fmt, args.quality)}")
        elif src.formats:
            reporter.log(f"Quality: Requested '{args.quality}', using best available format.")

        if args.dry_run:
            reporter.log("Dry run finished successfully. No files were downloaded.")
            return 0

        opts = _build_job_options(args, cut_text=cut_text)
        client = _resolve_twitch_client() if _needs_twitch_client(args) else None
        job = Job(source=src, opts=opts, client=client)
        reporter.log(f"Starting download to '{opts.out_dir}'...")
        run_job(job, ctx)
        reporter.log("Download completed successfully!")
        return 0

    except KeyboardInterrupt:
        print("\n[LuckyDownloader] Operation cancelled by user.", file=sys.stderr)
        return 130
    except Cancelled:
        print("\n[LuckyDownloader] Cancelled.", file=sys.stderr)
        return 130
    except EngineError as e:
        print(f"\n[LuckyDownloader ERROR] {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"\n[LuckyDownloader UNEXPECTED ERROR] {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
