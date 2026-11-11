#!/usr/bin/env python3
"""Batch Whisper transcription runner for Google Colab (T4 GPU).

Scans Google Drive for gameplay VODs, extracts lightweight audio,
runs faster-whisper (large-v3-turbo on CUDA), and outputs timestamped
text files directly into Google Drive for AI chapter analysis.
"""

import os
import subprocess
import sys
from pathlib import Path


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

    for idx, video_path in enumerate(video_files, 1):
        out_txt = drive_dir / f"{video_path.stem}_transcript.txt"

        print("==========================================================")
        print(f" [{idx}/{len(video_files)}] Processing: {video_path.name}")
        print("==========================================================")

        if out_txt.exists() and out_txt.stat().st_size > 1024:
            print(f"--> Transcript already exists! Skipping: {out_txt.name}")
            continue

        # 1. Extract audio
        print("--> Step 1: Extracting 16kHz mono audio via ffmpeg...")
        if temp_audio.exists():
            temp_audio.unlink(missing_ok=True)

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
            str(temp_audio),
        ]
        ret = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret.returncode != 0 or not temp_audio.exists():
            print(f"ERROR: Failed to extract audio from {video_path.name}")
            continue

        audio_size_mb = temp_audio.stat().st_size / (1024 * 1024)
        print(f"--> Audio extracted successfully ({audio_size_mb:.1f} MB).")

        # 2. Transcribe
        print("--> Step 2: Transcribing with Whisper (VAD enabled)...")
        segments, info = model.transcribe(
            str(temp_audio),
            beam_size=5,
            language="en",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        print(f"--> Detected language: {info.language} ({info.language_probability:.2%})")
        print("--> Writing transcript...")

        line_count = 0
        with open(out_txt, "w", encoding="utf-8") as f_out:
            f_out.write(f"VOD: {video_path.name}\n")
            f_out.write(f"Language: {info.language}\n")
            f_out.write("==========================================================\n\n")

            for seg in segments:
                ts = format_timestamp(seg.start)
                text = seg.text.strip()
                if text:
                    f_out.write(f"{ts} {text}\n")
                    f_out.flush()
                    line_count += 1
                    if line_count % 200 == 0:
                        print(f"    {ts} ({line_count} lines transcribed...)")

        print(f"--> Done! Total {line_count} spoken lines saved to:")
        print(f"    {out_txt}")

        # Clean up temp audio to keep VM clean
        if temp_audio.exists():
            temp_audio.unlink(missing_ok=True)

    print("\n==========================================================")
    print(" ALL TRANSCRIPTIONS COMPLETED SUCCESSFULLY!")
    print(f" Transcripts saved in: {drive_dir}")
    print("==========================================================")


if __name__ == "__main__":
    main()
