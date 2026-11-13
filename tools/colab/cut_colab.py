#!/usr/bin/env python3
"""Parameterized local/Google Drive batch video cutter for Google Colab.

Uses core.finalize.split_copy (or cut_exact with --exact) and core.planning.make_plan
to cut local/Drive videos in a single pass with atomic .part staging.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

print = functools.partial(print, flush=True)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.finalize import cut_exact, split_copy
from core.planning import make_plan
from core.runtime import Ctx, find_tool


def _probe_duration(path: Path) -> float:
    ffprobe = find_tool("ffprobe") or shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
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
        try:
            return max(0.0, float(res.stdout.strip()))
        except ValueError:
            return 0.0
    return 0.0


def _find_matching_file(directory: Path, pattern: str) -> Path | None:
    matches = [p for p in directory.glob(pattern) if p.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_size, reverse=True)
    return matches[0]


def _cut_one_file(
    src_file: Path,
    cuts: str,
    target_dir: Path,
    *,
    base_title: str = "",
    container: str = "mp4",
    exact: bool = False,
) -> None:
    duration = _probe_duration(src_file)
    plan = make_plan(cuts, duration, "full")
    stem = base_title or src_file.stem
    ctx = Ctx(log=lambda m: print(f"[cut] {m}"), progress=lambda f, t: None)

    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".lucky_cut_") as tmp:
        workdir = Path(tmp)
        if exact:
            for part in plan.parts:
                dest = target_dir / f"{stem} - part{part.index}.{container}"
                if dest.exists():
                    print(f"--> Already exists, skipping: {dest.name}")
                    continue
                seg = cut_exact(ctx, src_file, part, container, workdir)
                part_dest = dest.with_name(dest.name + ".part")
                shutil.move(str(seg), str(part_dest))
                os.replace(part_dest, dest)
                print(f"--> Saved: {dest}")
        else:
            segments = split_copy(ctx, src_file, plan.parts, duration, container, workdir)
            for part in plan.parts:
                dest = target_dir / f"{stem} - part{part.index}.{container}"
                if dest.exists():
                    print(f"--> Already exists, skipping: {dest.name}")
                    continue
                seg_path, _, _ = segments[part.index]
                part_dest = dest.with_name(dest.name + ".part")
                if seg_path.resolve() == src_file.resolve():
                    shutil.copy2(str(seg_path), str(part_dest))
                else:
                    shutil.move(str(seg_path), str(part_dest))
                os.replace(part_dest, dest)
                print(f"--> Saved: {dest}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Parameterized batch video cutter for Colab.")
    p.add_argument("--source-dir", required=True, help="Directory containing source video files.")
    p.add_argument("--target-dir", required=True, help="Directory to write cut parts into.")
    p.add_argument("--tasks-json", default="", help="Optional JSON file with list of {pattern, cuts, base_title} tasks.")
    p.add_argument("--pattern", default="*.mp4", help="Glob pattern when --tasks-json is not used (default: *.mp4).")
    p.add_argument("--cuts", "-c", default="", help="Cut points string when --tasks-json is not used.")
    p.add_argument("--container", default="mp4", choices=["mp4", "mkv"], help="Output container (default: mp4).")
    p.add_argument("--exact", action="store_true", help="Re-encode cut points for frame-exact trimming.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_dir = Path(args.source_dir)
    target_dir = Path(args.target_dir)

    if not source_dir.is_dir():
        print(f"ERROR: Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    if args.tasks_json:
        tasks = json.loads(Path(args.tasks_json).read_text(encoding="utf-8"))
        for idx, task in enumerate(tasks, 1):
            pattern = task.get("pattern", "*.mp4")
            cuts = task.get("cuts", "")
            base_title = task.get("base_title", "")
            if isinstance(cuts, list):
                cuts = " ; ".join(f"{s} - {e or 'end'}" for s, e in cuts)
            match = _find_matching_file(source_dir, pattern)
            if not match:
                print(f"[{idx}/{len(tasks)}] WARNING: No file matching '{pattern}' in {source_dir}")
                continue
            print(f"[{idx}/{len(tasks)}] Cutting {match.name} ...")
            _cut_one_file(match, cuts, target_dir, base_title=base_title, container=args.container, exact=args.exact)
    else:
        if not args.cuts:
            print("ERROR: Provide --cuts or --tasks-json.", file=sys.stderr)
            return 1
        matches = sorted(p for p in source_dir.glob(args.pattern) if p.is_file())
        if not matches:
            print(f"No files matching '{args.pattern}' in {source_dir}.")
            return 0
        for idx, match in enumerate(matches, 1):
            print(f"[{idx}/{len(matches)}] Cutting {match.name} ...")
            _cut_one_file(match, args.cuts, target_dir, container=args.container, exact=args.exact)

    return 0


if __name__ == "__main__":
    sys.exit(main())
