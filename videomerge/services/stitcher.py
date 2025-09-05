from __future__ import annotations

import subprocess
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


def concat_videos_with_voiceover(video_paths: Iterable[Path], voiceover_path: Path, output_path: Path) -> Path:
    """Concat the given video files and mix with the given voiceover into output_path using ffmpeg."""
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
        '-movflags', '+faststart',
        str(output_path)
    ]
    logger.debug("[stitcher] FFmpeg concat cmd: %s", ' '.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.debug("[stitcher] ffmpeg rc=%s stdout=%s stderr=%s", result.returncode, result.stdout, result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat error: {result.stderr}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Stitched output not created or empty")
    return output_path


def generate_and_burn_subtitles(input_video: Path, final_path: Path, *, language: str = 'pt', model_size: str = 'small', position: str = 'bottom') -> Path:
    """Generate subtitles for input_video and burn them into final_path."""
    input_video = Path(input_video)
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    segments = run_whisper_segments(input_video, language=language, model_size=model_size)
    srt_path = final_path.parent / "generated.srt"
    chunks = build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
    write_srt_from_chunks(chunks, srt_path)

    burn_subtitles(input_video, srt_path, final_path, position=position or 'bottom', margin_v=None)
    if not final_path.exists() or final_path.stat().st_size == 0:
        raise RuntimeError("Final subtitled output not created or empty")
    return final_path
