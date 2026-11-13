#!/usr/bin/env python3
"""Crash-resumable, parameterized Whisper transcription tool for Google Colab.

Isolates per-video audio chunks in /content/audio_chunks/<sha1> behind an
.extraction_done sentinel, computes exact chunk offsets via wave.open, and
writes transcripts atomically via .part files before os.replace.
"""

from __future__ import annotations

import argparse
import ctypes
import functools
import gc
import hashlib
import os
import shutil
import site
import subprocess
import sys
import wave
from pathlib import Path

print = functools.partial(print, flush=True)


def _preload_cuda_libs() -> None:
    for site_pkg in site.getsitepackages():
        for sub in ("cublas", "cudnn"):
            lib_dir = os.path.join(site_pkg, "nvidia", sub, "lib")
            if os.path.isdir(lib_dir):
                prev = os.environ.get("LD_LIBRARY_PATH", "")
                os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{prev}" if prev else lib_dir
                for fname in sorted(os.listdir(lib_dir)):
                    if fname.endswith(".so") or ".so." in fname:
                        try:
                            ctypes.CDLL(os.path.join(lib_dir, fname), mode=ctypes.RTLD_GLOBAL)
                        except Exception:
                            pass


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"


def format_srt_timestamp(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours = ms_total // 3_600_000
    minutes = (ms_total % 3_600_000) // 60_000
    secs = (ms_total % 60_000) // 1000
    ms = ms_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours = ms_total // 3_600_000
    minutes = (ms_total % 3_600_000) // 60_000
    secs = (ms_total % 60_000) // 1000
    ms = ms_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def wav_duration(wav_path: Path) -> float:
    """Compute exact WAV duration using wave.open (no hardcoded 44-byte header assumption)."""
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or 16000
        return frames / float(rate)


def video_chunks_dir(base_chunks_dir: Path, video_path: Path) -> Path:
    digest = hashlib.sha1(str(video_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return base_chunks_dir / digest


def extract_chunks(video_path: Path, chunks_dir: Path, segment_seconds: int = 1800) -> list[Path]:
    sentinel = chunks_dir / ".extraction_done"
    if sentinel.exists():
        chunks = sorted(chunks_dir.glob("chunk_*.wav"))
        if chunks:
            return chunks

    # Clean partial extraction before starting
    if chunks_dir.exists():
        shutil.rmtree(chunks_dir, ignore_errors=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)

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
        str(segment_seconds),
        str(chunks_dir / "chunk_%03d.wav"),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed extracting audio from {video_path.name}: {res.stderr[-500:]}")

    chunks = sorted(chunks_dir.glob("chunk_*.wav"))
    if chunks:
        sentinel.write_text("ok\n", encoding="utf-8")
    return chunks


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crash-resumable Whisper transcription tool.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-dir", "--input-dir", dest="source_dir", help="Directory of video files to transcribe.")
    group.add_argument("--file", dest="single_file", help="Single video file to transcribe.")
    p.add_argument("--output-dir", default="", help="Directory to write transcripts (defaults to source file directory).")
    p.add_argument("--model", default="deepdml/faster-whisper-large-v3-turbo-ct2", help="Whisper model name or path.")
    p.add_argument("--lang", default=None, help="Language code (e.g. 'en', 'es'). Defaults to auto-detect.")
    p.add_argument("--min-size-mb", type=float, default=0.0, help="Minimum video file size in MB (default: 0).")
    p.add_argument("--format", default="txt", help="Comma-separated output formats: txt,srt,vtt (default: txt).")
    p.add_argument("--chunks-root", default="/content/audio_chunks", help="Temporary root for per-video audio chunks.")
    p.add_argument("--device", default="cuda", help="Inference device (cuda/cpu, default: cuda).")
    p.add_argument("--compute-type", default="float16", help="CTranslate2 compute type (default: float16).")
    return p


def transcribe_video(
    video_path: Path,
    out_dir: Path,
    model,
    *,
    lang: str | None,
    formats: set[str],
    chunks_root: Path,
) -> None:
    targets = {fmt: out_dir / f"{video_path.stem}_transcript.{fmt}" for fmt in formats}
    if all(p.exists() and p.stat().st_size > 0 for p in targets.values()):
        print(f"--> Transcript(s) already complete for {video_path.name}, skipping.")
        return

    cdir = video_chunks_dir(chunks_root, video_path)
    chunks = extract_chunks(video_path, cdir)
    if not chunks:
        print(f"ERROR: No audio chunks extracted for {video_path.name}")
        return

    part_paths = {fmt: p.with_name(p.name + ".part") for fmt, p in targets.items()}
    handles = {fmt: open(pp, "w", encoding="utf-8") for fmt, pp in part_paths.items()}
    try:
        if "txt" in handles:
            handles["txt"].write(f"VOD: {video_path.name}\n")
            handles["txt"].write(f"Language: {lang or 'auto'}\n")
            handles["txt"].write("==========================================================\n\n")
        if "vtt" in handles:
            handles["vtt"].write("WEBVTT\n\n")

        srt_idx = 1
        offset = 0.0
        for c_idx, chunk_file in enumerate(chunks, 1):
            dur = wav_duration(chunk_file)
            print(
                f"  [Chunk {c_idx}/{len(chunks)}] "
                f"{format_timestamp(offset)} -> {format_timestamp(offset + dur)}"
            )
            kw = {"beam_size": 1, "vad_filter": False}
            if lang:
                kw["language"] = lang
            segments, _ = model.transcribe(str(chunk_file), **kw)
            for seg in segments:
                text = seg.text.strip()
                if not text:
                    continue
                start_s = seg.start + offset
                end_s = seg.end + offset
                if "txt" in handles:
                    handles["txt"].write(f"{format_timestamp(start_s)} {text}\n")
                if "srt" in handles:
                    handles["srt"].write(
                        f"{srt_idx}\n{format_srt_timestamp(start_s)} --> {format_srt_timestamp(end_s)}\n{text}\n\n"
                    )
                    srt_idx += 1
                if "vtt" in handles:
                    handles["vtt"].write(
                        f"{format_vtt_timestamp(start_s)} --> {format_vtt_timestamp(end_s)}\n{text}\n\n"
                    )
            for fh in handles.values():
                fh.flush()
            offset += dur
            gc.collect()
    finally:
        for fh in handles.values():
            fh.close()

    for fmt, part_path in part_paths.items():
        os.replace(part_path, targets[fmt])
        print(f"--> Saved: {targets[fmt]}")

    shutil.rmtree(cdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    _preload_cuda_libs()
    args = build_parser().parse_args(argv)
    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()} & {"txt", "srt", "vtt"}
    if not formats:
        formats = {"txt"}

    if args.single_file:
        vp = Path(args.single_file)
        if not vp.is_file():
            print(f"ERROR: File not found: {vp}", file=sys.stderr)
            return 1
        video_files = [vp]
        default_out = vp.parent
    else:
        src_dir = Path(args.source_dir)
        if not src_dir.is_dir():
            print(f"ERROR: Directory not found: {src_dir}", file=sys.stderr)
            return 1
        min_bytes = int(args.min_size_mb * 1024 * 1024)
        video_files = sorted(
            (
                f
                for ext in ("*.mp4", "*.mkv")
                for f in src_dir.glob(ext)
                if f.is_file() and f.stat().st_size >= min_bytes
            ),
            key=lambda p: p.name,
        )
        default_out = src_dir

    if not video_files:
        print("No matching video files found.")
        return 0

    out_dir = Path(args.output_dir) if args.output_dir else default_out
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_root = Path(args.chunks_root)

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    for idx, vf in enumerate(video_files, 1):
        print(f"[{idx}/{len(video_files)}] Transcribing {vf.name} ...")
        transcribe_video(vf, out_dir, model, lang=args.lang, formats=formats, chunks_root=chunks_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
