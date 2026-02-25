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
from videomerge.services.media import get_duration
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def _compute_clip_plan(video_paths: List[Path], voiceover_duration: float, video_speed_factor: float = 1.0) -> tuple[List[Path], float, bool]:
    """
    Decide which clips to use to best match the voiceover duration.
    Returns (selected_video_paths, last_clip_trim_seconds, needs_trimming)

    - selected_video_paths: list of full clips to include; if needs_trimming is True, the last
      item in this list is the source to trim by last_clip_trim_seconds.
    - last_clip_trim_seconds: if > 0 and needs_trimming True, trim this many seconds from the start
      (0) to duration 'last_clip_trim_seconds' (i.e., target length for the last clip).
    - needs_trimming: whether we must trim the last clip to fit.

    When video_speed_factor > 1.0 the video plays back faster, so the source clips must be
    longer than the voiceover by that factor. The plan therefore targets
    ``voiceover_duration * video_speed_factor`` seconds of source material.
    """
    # Compute how many seconds of source video are needed so that after playback
    # at video_speed_factor the output matches the voiceover duration.
    target_source_duration = voiceover_duration * max(video_speed_factor, 1.0)

    durations: List[float] = []
    for p in video_paths:
        d = get_duration(p)
        if d is None:
            raise RuntimeError(f"Could not determine duration for video: {p}")
        durations.append(d)
    total = sum(durations)
    if target_source_duration >= total:
        # No trimming needed; we may still pad audio as before.
        return list(video_paths), 0.0, False

    # Voiceover is shorter: choose as many full clips as fit, then possibly a partial last one.
    selected: List[Path] = []
    acc = 0.0
    for p, d in zip(video_paths, durations):
        if acc + d < target_source_duration - 1e-3:  # strictly fits
            selected.append(p)
            acc += d
        else:
            # This clip is the one to trim (if any remainder exists)
            remaining = max(0.0, target_source_duration - acc)
            if remaining > 1e-3:
                selected.append(p)
                return selected, remaining, True
            else:
                # No remainder, exactly fits with previous clips
                return selected, 0.0, False

    # If we exhausted all clips (shouldn't happen due to earlier guard), return as-is
    return selected, 0.0, False


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
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
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
        if result.returncode != 0:
            logger.error("[stitcher] ffmpeg error rc=%s stderr=%s", result.returncode, result.stderr)
        return result

    # Always write to a local temp file first, then move to final location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir=output_path.parent) as tmp:
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
        # Clean up trimmed temp if created
        try:
            if 'trimmed_temp' in locals() and trimmed_temp and trimmed_temp.exists():
                trimmed_temp.unlink(missing_ok=True)
        except Exception:
            pass

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Stitched output not created or empty")
    return output_path


def concat_videos_with_voiceover(
    video_paths: Iterable[Path],
    voiceover_path: Path,
    output_path: Path,
    video_speed_factor: float = 1.0,
) -> Path:
    """Concat the given video files and mix with the given voiceover into output_path using ffmpeg.

    Robust against non-seekable/network volumes by writing to a local temp file first
    (so ffmpeg can safely move the moov atom with +faststart), then moving to output.
    If we hit an "Error writing trailer" from ffmpeg, retry once without +faststart.

    Args:
        video_paths: Iterable of video clip paths to concatenate.
        voiceover_path: Path to the voiceover audio file.
        output_path: Destination path for the final stitched video.
        video_speed_factor: Playback speed multiplier for the video stream
            (e.g. 1.2 = 20 % faster). The voiceover is left untouched so
            it acts as the timing reference via ``-shortest``.
    """
    video_paths = [Path(p) for p in video_paths]
    voiceover_path = Path(voiceover_path)
    output_path = Path(output_path)

    if not video_paths:
        raise ValueError("video_paths must contain at least one video")
    if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
        raise ValueError("voiceover_path does not exist or is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine whether we need to trim to voiceover duration
    use_apad = True
    selected_paths: List[Path] = list(video_paths)
    last_clip_target_len = 0.0
    needs_trim = False
    try:
        vo_dur_val = get_duration(voiceover_path)
        if vo_dur_val is None:
            raise RuntimeError(f"Could not determine duration for voiceover: {voiceover_path}")
        selected_paths, last_clip_target_len, needs_trim = _compute_clip_plan(video_paths, vo_dur_val, video_speed_factor)
        # If we are trimming to voiceover length, do NOT pad audio; let audio define the end.
        # Compare the effective post-speedup duration of selected clips against the voiceover.
        selected_source_dur = 0.0
        for p in selected_paths:
            d = get_duration(p)
            if d is None:
                raise RuntimeError(f"Could not determine duration for video: {p}")
            selected_source_dur += d
        effective_video_dur = selected_source_dur / max(video_speed_factor, 1.0)
        if needs_trim or effective_video_dur > vo_dur_val + 1e-3:
            use_apad = False
        video_too_short = effective_video_dur < vo_dur_val - 1e-3
    except Exception as e:
        logger.warning("[stitcher] Failed to probe durations, falling back to original behavior: %s", e)

    # If trimming is required, pre-trim the last selected clip to 'last_clip_target_len'
    trimmed_temp: Path | None = None
    if needs_trim and last_clip_target_len > 0.01:
        try:
            last_src = selected_paths[-1]
            trimmed_temp = output_path.parent / "trimmed_last.mp4"
            # Re-encode to ensure clean cut and consistent codec
            # Add a tiny safety margin to avoid rounding-induced early cutoff
            _src_len = get_duration(last_src) or last_clip_target_len
            SAFETY_MARGIN_SEC = 0.05
            _target_len = min(_src_len, last_clip_target_len + SAFETY_MARGIN_SEC)
            trim_cmd = [
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                '-ss', '0', '-t', f"{_target_len:.3f}",
                '-i', str(last_src),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-an',
                str(trimmed_temp),
            ]
            logger.debug("[stitcher] FFmpeg trim last clip cmd: %s", ' '.join(trim_cmd))
            t_res = subprocess.run(trim_cmd, capture_output=True, text=True)
            if t_res.returncode != 0:
                logger.error("[stitcher] ffmpeg trim error rc=%s stderr=%s", t_res.returncode, t_res.stderr)
            if t_res.returncode != 0 or not trimmed_temp.exists() or trimmed_temp.stat().st_size == 0:
                raise RuntimeError(f"Failed to trim last clip: {t_res.stderr}")
            # Replace last path with trimmed temp
            selected_paths = selected_paths[:-1] + [trimmed_temp]
        except Exception as e:
            logger.warning("[stitcher] Trimming failed, falling back to untrimmed list: %s", e)
            trimmed_temp = None
            use_apad = True  # fallback to previous behavior

    # Build concat list based on possibly adjusted selection
    # Write to local temp directory to avoid network filesystem issues
    import tempfile
    temp_dir = Path(tempfile.gettempdir())
    concat_list = temp_dir / f"inputs_{output_path.stem}.txt"
    with open(str(concat_list), "w", encoding="utf-8") as f:
        for p in selected_paths:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")

    # video_too_short defaults to False if duration probing failed above
    if 'video_too_short' not in dir():
        video_too_short = False

    apply_speed = video_speed_factor and video_speed_factor != 1.0
    if apply_speed:
        pts_factor = 1.0 / video_speed_factor
        logger.info(
            "[stitcher] Applying %.2fx video speed (setpts=%.6f*PTS)",
            video_speed_factor, pts_factor,
        )

    def _run_ffmpeg(dst: Path, with_faststart: bool) -> subprocess.CompletedProcess:
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(concat_list),
            '-i', str(voiceover_path),
        ]
        # Build filter_complex: optionally speed up video, loop if video is shorter than audio,
        # always normalise audio.
        audio_filter = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=7[aud]"
        if video_too_short:
            # Video is shorter than audio after speedup. Apply speed if needed, then let
            # ffmpeg run until -t (voiceover duration) — it will hold the last frame
            # automatically. No loop filter needed (avoids massive frame buffering).
            if apply_speed:
                video_filter = f"[0:v]setpts={pts_factor:.6f}*PTS[vid]"
                cmd += ['-filter_complex', f'{video_filter};{audio_filter}', '-map', '[vid]', '-map', '[aud]']
            else:
                cmd += ['-filter_complex', audio_filter, '-map', '0:v:0', '-map', '[aud]']
            cmd += ['-t', f"{vo_dur_val:.3f}"]
        elif apply_speed:
            video_filter = f"[0:v]setpts={pts_factor:.6f}*PTS[vid]"
            cmd += ['-filter_complex', f'{video_filter};{audio_filter}', '-map', '[vid]', '-map', '[aud]']
        else:
            cmd += ['-filter_complex', audio_filter, '-map', '0:v:0', '-map', '[aud]']
        if not video_too_short:
            cmd += ['-shortest']
        cmd += [
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac',
        ]
        if with_faststart:
            cmd += ['-movflags', '+faststart']
        cmd += [str(dst)]
        logger.debug("[stitcher] FFmpeg concat cmd: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("[stitcher] ffmpeg error rc=%s stderr=%s", result.returncode, result.stderr)
        return result

    # Always write to a local temp file first, then move to final location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir=output_path.parent) as tmp:
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


def generate_and_burn_subtitles(input_video: Path, final_path: Path, *, language: str, model_size: str = 'small', position: str = 'bottom', audio_hint: Path | None = None) -> Path:
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
