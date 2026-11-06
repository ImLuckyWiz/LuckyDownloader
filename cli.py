#!/usr/bin/env python3
"""
LuckyDownloader CLI - Command-line interface for LuckyDownloader.

A headless, lightweight interface to download and trim VODs and videos
using LuckyDownloader's core engine. Compatible with Google Colab,
Linux/macOS/Windows servers, and automated pipelines without any GUI dependencies.
"""

from __future__ import annotations

import argparse
import os
import sys
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

from core.errors import Cancelled, EngineError
from core.finalize import run_job
from core.job import Job, JobOptions
from core.paths import read_bundled_version
from core.planning import make_plan
from core.providers import Capability
from core.runtime import Ctx
from core.source_info import (
    QUALITY_BEST,
    describe_quality,
    get_source_info,
    resolve_format,
)
from core.timeutil import fmt_hms
from core.tools import ensure_tools


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
            return

        pct = int(min(max(frac, 0.0), 1.0) * 100)

        # In non-TTY environments (Google Colab, redirected logs, CI),
        # only emit progress on 5% milestones, stage changes, or after 5 seconds to avoid log spam.
        if not self.is_tty:
            should_print = (
                pct != self.last_pct
                and (pct % 10 == 0 or pct == 100 or text != self.last_label or (now - self.last_print_time) >= 5.0)
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


def main(argv: list[str] | None = None) -> int:
    """Main CLI execution routine."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.url:
        parser.print_help()
        return 1

    reporter = ConsoleReporter(quiet=args.quiet)
    ctx = Ctx(log=reporter.log, progress=reporter.progress)

    try:
        # Ensure tools (ffmpeg, yt-dlp) are present before fetching metadata or downloading
        reporter.log("Verifying tools (ffmpeg, yt-dlp)...")
        ensure_tools(ctx)

        reporter.log(f"Fetching metadata for: {args.url}")
        src = get_source_info(args.url, cookies_browser=args.cookies_browser or None)
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

        opts = JobOptions(
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
            quality=args.quality,
            audio_format=args.audio_format,
            rate_limit=args.rate_limit or "",
            cookies_browser=args.cookies_browser or "",
            subfolders=args.subfolders,
        )

        job = Job(source=src, opts=opts)
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
