from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List

from videomerge.services.subtitles import (
    run_whisper_segments,
    build_chunks_from_words,
    write_srt_from_chunks,
    burn_subtitles,
)
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def concat_videos(video_paths: Iterable[Path], output_path: Path) -> Path:
    """Concat the given video files into output_path using ffmpeg (no voiceover).

    Robust against non-seekable/network volumes by writing to a local temp file first
    (so ffmpeg can safely move the moov atom with +faststart), then moving to output.
    If we hit an "Error writing trailer" from ffmpeg, retry once without +faststart.
    """
    video_paths = [Path(p) for p in video_paths]
    output_path = Path(output_path)

    if not video_paths:
        raise ValueError("video_paths must contain at least one video")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    concat_list = output_path.parent / "inputs.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in video_paths:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")

    def _run_ffmpeg(dst: Path, with_faststart: bool) -> subprocess.CompletedProcess:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(concat_list),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-an',
        ]
        if with_faststart:
            cmd += ['-movflags', '+faststart']
        cmd += [str(dst)]
        logger.debug("[stitcher] FFmpeg concat(no-audio) cmd: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.debug("[stitcher] ffmpeg rc=%s stdout=%s stderr=%s", result.returncode, result.stdout, result.stderr)
        return result

    # Always write to a local temp file first, then move to final location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp_path = Path(tmp.name)
    try:
        # First attempt with +faststart
        result = _run_ffmpeg(tmp_path, with_faststart=True)
        if result.returncode != 0 and "Error writing trailer" in (result.stderr or ""):
            logger.warning("[stitcher] ffmpeg reported trailer write error. Retrying without +faststart.")
            result = _run_ffmpeg(tmp_path, with_faststart=False)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat error: {result.stderr}")
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError("Stitched temp output not created or empty")
        # Ensure output directory exists and move
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), str(output_path))
    finally:
        # Best-effort cleanup if temp still exists
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:  # pragma: no cover
            pass

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Stitched output not created or empty")
    return output_path


def concat_videos_with_voiceover(video_paths: Iterable[Path], voiceover_path: Path, output_path: Path) -> Path:
    """Concat the given video files and mix with the given voiceover into output_path using ffmpeg.

    Robust against non-seekable/network volumes by writing to a local temp file first
    (so ffmpeg can safely move the moov atom with +faststart), then moving to output.
    If we hit an "Error writing trailer" from ffmpeg, retry once without +faststart.
    """
    video_paths = [Path(p) for p in video_paths]
    voiceover_path = Path(voiceover_path)
    output_path = Path(output_path)

    if not video_paths:
        raise ValueError("video_paths must contain at least one video")
    if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
        raise ValueError("voiceover_path does not exist or is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    concat_list = output_path.parent / "inputs.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in video_paths:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")

    def _run_ffmpeg(dst: Path, with_faststart: bool) -> subprocess.CompletedProcess:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(concat_list),
            '-i', str(voiceover_path),
            '-filter_complex', '[1:a]loudnorm=I=-14:TP=-1.5:LRA=7,apad[aud]',
            '-map', '0:v:0', '-map', '[aud]',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac',
            '-shortest',
        ]
        if with_faststart:
            cmd += ['-movflags', '+faststart']
        cmd += [str(dst)]
        logger.debug("[stitcher] FFmpeg concat cmd: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.debug("[stitcher] ffmpeg rc=%s stdout=%s stderr=%s", result.returncode, result.stdout, result.stderr)
        return result

    # Always write to a local temp file first, then move to final location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp_path = Path(tmp.name)
    try:
        # First attempt with +faststart
        result = _run_ffmpeg(tmp_path, with_faststart=True)
        if result.returncode != 0 and "Error writing trailer" in (result.stderr or ""):
            logger.warning("[stitcher] ffmpeg reported trailer write error. Retrying without +faststart.")
            result = _run_ffmpeg(tmp_path, with_faststart=False)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat error: {result.stderr}")
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError("Stitched temp output not created or empty")
        # Ensure output directory exists and move
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), str(output_path))
    finally:
        # Best-effort cleanup if temp still exists
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:  # pragma: no cover
            pass

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Stitched output not created or empty")
    return output_path


def generate_and_burn_subtitles(input_video: Path, final_path: Path, *, language: str = 'pt', model_size: str = 'small', position: str = 'bottom', audio_hint: Path | None = None) -> Path:
    """Generate subtitles for input_video and burn them into final_path."""
    input_video = Path(input_video)
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer a provided audio hint (e.g., voiceover.mp3) for transcription to avoid failures on videos without audio
    transcription_source = Path(audio_hint) if audio_hint else input_video
    segments = run_whisper_segments(transcription_source, language=language, model_size=model_size)
    srt_path = final_path.parent / "generated.srt"
    chunks = build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
    write_srt_from_chunks(chunks, srt_path)

    burn_subtitles(input_video, srt_path, final_path, position=position or 'bottom', margin_v=None)
    if not final_path.exists() or final_path.stat().st_size == 0:
        raise RuntimeError("Final subtitled output not created or empty")
    return final_path
