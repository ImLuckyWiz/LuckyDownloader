#!/usr/bin/env python3
"""Lossless batch video cutter for Google Colab.

Reads source VODs from Google Drive, cuts exact chapters using FFmpeg stream copy
(-c copy), and uploads finished parts directly to Lucky/Vexoria_The_SunEater.
Enforces strict local disk hygiene so the Colab VM never uses more than ~5-8 GB.
"""

import functools
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Force unbuffered prints
print = functools.partial(print, flush=True)

SOURCE_DIR = Path("/content/drive/MyDrive/VideosParaSubir/Vexoria")
TARGET_DIR = Path("/content/drive/MyDrive/Lucky/Vexoria_The_SunEater")
LOCAL_TEMP = Path("/content/temp_cut.mp4")

# Defined chapter cuts per Zelda day
TASKS = [
    {
        "day": "Zelda 1",
        "pattern": "*Day 1*part2.mp4",
        "base_title": "Vexoria - Zelda Day 1",
        "cuts": [
            ("00:00:00", "01:54:30"),
            ("01:54:30", "03:31:03"),
            ("03:31:03", "06:06:58"),
            ("06:06:58", "08:36:30"),
            ("08:36:30", "10:56:26"),
            ("10:56:26", None),  # to end
        ],
    },
    {
        "day": "Zelda 2",
        "pattern": "*Day 2*.mp4",
        "base_title": "Vexoria - Zelda Day 2",
        "cuts": [
            ("00:00:00", "01:34:40"),
            ("01:34:40", "02:58:42"),
            ("02:58:42", "04:50:48"),
            ("04:50:48", "07:16:33"),
            ("07:16:33", "08:53:40"),
            ("08:53:40", "10:30:00"),
            ("10:30:00", None),
        ],
    },
    {
        "day": "Zelda 3",
        "pattern": "*Day 3*.mp4",
        "base_title": "Vexoria - Zelda Day 3",
        "cuts": [
            ("00:00:00", "01:29:54"),
            ("01:29:54", "03:20:50"),
            ("03:20:50", "05:44:32"),
            ("05:44:32", "08:12:28"),
            ("08:12:28", "10:07:05"),
            ("10:07:05", None),
        ],
    },
    {
        "day": "Zelda 4",
        "pattern": "*Day 4*.mp4",
        "base_title": "Vexoria - Zelda Day 4",
        "cuts": [
            ("00:00:00", "01:43:35"),
            ("01:43:35", "03:40:11"),
            ("03:40:11", None),
        ],
    },
]


def print_vm_disk_usage():
    try:
        usage = shutil.disk_usage("/content")
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        print(f"--> [VM Disk Monitor] Free space: {free_gb:.1f} GB / {total_gb:.1f} GB")
    except Exception:
        pass


def find_matching_file(directory: Path, pattern: str) -> Path | None:
    matches = list(directory.glob(pattern))
    if not matches:
        return None
    # Pick the largest if multiple
    matches.sort(key=lambda p: p.stat().st_size, reverse=True)
    return matches[0]


def cut_segment(input_file: Path, start: str, end: str | None, output_file: Path) -> bool:
    if LOCAL_TEMP.exists():
        LOCAL_TEMP.unlink(missing_ok=True)

    cmd = ["ffmpeg", "-y", "-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += [
        "-i",
        str(input_file),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(LOCAL_TEMP),
    ]

    t0 = time.time()
    ret = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elapsed = time.time() - t0

    if ret.returncode != 0 or not LOCAL_TEMP.exists() or LOCAL_TEMP.stat().st_size < 1024 * 1024:
        print(f"ERROR: ffmpeg cut failed for {start} -> {end or 'end'}")
        if LOCAL_TEMP.exists():
            LOCAL_TEMP.unlink(missing_ok=True)
        return False

    temp_size_gb = LOCAL_TEMP.stat().st_size / (1024**3)
    print(f"    --> Lossless cut completed in {elapsed:.1f}s (Part size: {temp_size_gb:.2f} GB)")

    # Transfer to Google Drive
    print(f"    --> Moving part to Google Drive destination...")
    t_upload = time.time()
    shutil.copy2(LOCAL_TEMP, output_file)
    LOCAL_TEMP.unlink(missing_ok=True)
    print(f"    --> Saved successfully to Drive in {time.time() - t_upload:.1f}s!")

    return True


def main():
    print("==========================================================")
    print(" [LuckyDownloader] Lossless Colab Video Chapter Cutter")
    print("==========================================================")

    if not SOURCE_DIR.exists():
        print(f"ERROR: Source directory does not exist: {SOURCE_DIR}")
        print("Please verify Google Drive is mounted at /content/drive.")
        sys.exit(1)

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Source Folder     : {SOURCE_DIR}")
    print(f"Destination Folder: {TARGET_DIR}\n")
    print_vm_disk_usage()
    print("==========================================================\n")

    total_tasks = sum(len(t["cuts"]) for t in TASKS)
    processed_count = 0

    for task_idx, task in enumerate(TASKS, 1):
        day_label = task["day"]
        pattern = task["pattern"]
        base_title = task["base_title"]
        cuts = task["cuts"]

        print(f"\n##########################################################")
        print(f" [{task_idx}/{len(TASKS)}] Processing {day_label} ({len(cuts)} parts)")
        print(f"##########################################################")

        input_video = find_matching_file(SOURCE_DIR, pattern)
        if not input_video:
            print(f"WARNING: Video file matching '{pattern}' not found in {SOURCE_DIR}. Skipping.")
            continue

        print(f"Found input video: {input_video.name} ({input_video.stat().st_size / (1024**3):.2f} GB)")

        for part_num, (start, end) in enumerate(cuts, 1):
            processed_count += 1
            out_filename = f"{base_title} - Chapter {part_num}.mp4"
            final_target = TARGET_DIR / out_filename
            end_label = end if end else "END"

            print(f"\n--- Part {part_num:02d}/{len(cuts):02d} [{start} -> {end_label}] ---")
            print(f"Target: {out_filename}")

            if final_target.exists() and final_target.stat().st_size > 50 * 1024 * 1024:
                print(f"--> Already completed ({final_target.stat().st_size / (1024**3):.2f} GB)! Skipping.")
                continue

            success = cut_segment(input_video, start, end, final_target)
            if not success:
                print(f"Failed to process part {part_num}. Moving to next.")

            print_vm_disk_usage()

    print("\n==========================================================")
    print(" ALL VIDEO CUTS COMPLETED SUCCESSFULLY!")
    print(f" Files stored in: {TARGET_DIR}")
    print("==========================================================")


if __name__ == "__main__":
    main()
