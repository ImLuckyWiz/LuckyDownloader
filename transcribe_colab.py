#!/usr/bin/env python3
"""Batch Whisper transcription runner for Google Colab (T4 GPU).

Scans Google Drive for gameplay VODs, extracts lightweight audio in 30-minute
chunks to prevent PyAV/Python RAM exhaustion, runs faster-whisper
(large-v3-turbo on CUDA), and outputs timestamped text files directly into
Google Drive for AI chapter analysis.
"""

import ctypes
import functools
import gc
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

# Force unbuffered streaming output in Google Colab / pipes
print = functools.partial(print, flush=True)

# Preload CUDA 12 libraries (cuBLAS, cuDNN) so CTranslate2 dlopen succeeds
for site_pkg in site.getsitepackages():
    for sub in ("cublas", "cudnn"):
        lib_dir = os.path.join(site_pkg, "nvidia", sub, "lib")
        if os.path.isdir(lib_dir):
            if "LD_LIBRARY_PATH" in os.environ:
                os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{os.environ['LD_LIBRARY_PATH']}"
            else:
                os.environ["LD_LIBRARY_PATH"] = lib_dir
            for fname in sorted(os.listdir(lib_dir)):
                if fname.endswith(".so") or ".so." in fname:
                    try:
                        ctypes.CDLL(os.path.join(lib_dir, fname), mode=ctypes.RTLD_GLOBAL)
                    except Exception:
                        pass


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"


def main():
    drive_dir = Path("/content/drive/MyDrive/VideosParaSubir/Vexoria")
    if not drive_dir.exists():
        print(f"ERROR: Directory not found: {drive_dir}")
        print("Please verify that Google Drive is mounted at /content/drive.")
        sys.exit(1)

    print("==========================================================")
    print(" [LuckyDownloader] AI Video Transcriber (Whisper Turbo)")
    print(f" Target Folder: {drive_dir}")
    print("==========================================================")

    # Collect video files (> 5 GB to skip small intro clips)
    MIN_SIZE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB
    video_files = []
    for ext in ("*.mp4", "*.mkv"):
        for f in drive_dir.glob(ext):
            try:
                if f.stat().st_size >= MIN_SIZE_BYTES:
                    video_files.append(f)
                else:
                    print(f"--> Skipping small file ({f.stat().st_size / (1024**3):.2f} GB): {f.name}")
            except Exception as e:
                print(f"Warning: could not stat {f.name}: {e}")

    # Sort files consistently
    video_files.sort(key=lambda x: x.name)

    if not video_files:
        print("No video files >= 5 GB found to transcribe!")
        sys.exit(0)

    print(f"\nFound {len(video_files)} video(s) to transcribe:")
    for i, vf in enumerate(video_files, 1):
        print(f"  {i}. {vf.name} ({vf.stat().st_size / (1024**3):.2f} GB)")

    # Lazy-load faster-whisper model
    print("\n--> Loading Whisper large-v3-turbo model on CUDA GPU...")
    from faster_whisper import WhisperModel

    model = WhisperModel(
        "deepdml/faster-whisper-large-v3-turbo-ct2",
        device="cuda",
        compute_type="float16",
    )
    print("--> Whisper model loaded successfully on GPU!\n")

    temp_audio = Path("/content/temp_audio.wav")
    chunks_dir = Path("/content/audio_chunks")

    for idx, video_path in enumerate(video_files, 1):
        out_txt = drive_dir / f"{video_path.stem}_transcript.txt"

        print("==========================================================")
        print(f" [{idx}/{len(video_files)}] Processing: {video_path.name}")
        print("==========================================================")

        if out_txt.exists() and out_txt.stat().st_size > 1024:
            print(f"--> Transcript already exists! Skipping: {out_txt.name}")
            continue

        # Check if chunks already exist from an interrupted run
        chunks = sorted(chunks_dir.glob("chunk_*.wav")) if chunks_dir.exists() else []

        if chunks:
            print(f"--> Reusing {len(chunks)} already extracted audio chunks!")
        else:
            chunks_dir.mkdir(parents=True, exist_ok=True)
            # 1. Generate 30-minute (1800s) audio chunks to stay well within RAM limits
            if temp_audio.exists() and temp_audio.stat().st_size > 100 * 1024 * 1024:
                audio_size_mb = temp_audio.stat().st_size / (1024 * 1024)
                print(f"--> Splitting existing temp_audio.wav ({audio_size_mb:.1f} MB) into 30m chunks...")
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(temp_audio),
                    "-f",
                    "segment",
                    "-segment_time",
                    "1800",
                    "-c",
                    "copy",
                    str(chunks_dir / "chunk_%03d.wav"),
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                temp_audio.unlink(missing_ok=True)
            else:
                print("--> Extracting audio into 30m chunks directly from video via ffmpeg...")
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-f",
                    "segment",
                    "-segment_time",
                    "1800",
                    str(chunks_dir / "chunk_%03d.wav"),
                ]
                ret = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if ret.returncode != 0:
                    print(f"ERROR: Failed to extract audio chunks from {video_path.name}")
                    continue

            chunks = sorted(chunks_dir.glob("chunk_*.wav"))

        if not chunks:
            print(f"ERROR: No audio chunks found for {video_path.name}")
            continue

        print(f"--> Total {len(chunks)} audio chunk(s) ready (~30 min each). Starting GPU transcription...\n")

        line_count = 0
        current_time_offset = 0.0

        with open(out_txt, "w", encoding="utf-8") as f_out:
            f_out.write(f"VOD: {video_path.name}\n")
            f_out.write("Language: en\n")
            f_out.write("==========================================================\n\n")

            for c_idx, chunk_file in enumerate(chunks, 1):
                chunk_bytes = chunk_file.stat().st_size - 44
                chunk_duration = max(0.0, chunk_bytes / (16000 * 2))

                print(
                    f"  [Chunk {c_idx}/{len(chunks)}] Transcribing "
                    f"{format_timestamp(current_time_offset)} -> {format_timestamp(current_time_offset + chunk_duration)}..."
                )

                segments, _ = model.transcribe(
                    str(chunk_file),
                    beam_size=1,
                    language="en",
                    vad_filter=False,
                )

                chunk_lines = 0
                for seg in segments:
                    actual_ts = format_timestamp(seg.start + current_time_offset)
                    text = seg.text.strip()
                    if text:
                        f_out.write(f"{actual_ts} {text}\n")
                        f_out.flush()
                        line_count += 1
                        chunk_lines += 1
                        if chunk_lines % 15 == 0:
                            print(f"    {actual_ts} {text[:75]}")

                current_time_offset += chunk_duration

                # Delete processed chunk to save disk & free memory
                chunk_file.unlink(missing_ok=True)
                gc.collect()

        print(f"\n--> Done! Total {line_count} spoken lines saved to:")
        print(f"    {out_txt}\n")

        # Clean up chunk dir
        if chunks_dir.exists():
            shutil.rmtree(chunks_dir, ignore_errors=True)

    print("==========================================================")
    print(" ALL TRANSCRIPTIONS COMPLETED SUCCESSFULLY!")
    print(f" Transcripts saved in: {drive_dir}")
    print("==========================================================")


if __name__ == "__main__":
    main()
