import subprocess
from pathlib import Path
from typing import Optional, List
from fastapi import HTTPException


def run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"FFmpeg error: {result.stderr}")


def run_ffprobe(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def speed_up_video(input_path: Path, output_path: Path, speed_factor: float) -> Path:
    """Speed up a video clip by the given factor using ffmpeg.

    Uses the setpts filter for video and atempo for audio (if present).
    The output replaces the visual tempo without re-encoding audio when there
    is no audio stream.

    Args:
        input_path: Path to the source video file.
        output_path: Path where the sped-up video will be written.
        speed_factor: Multiplier for playback speed (e.g. 1.2 = 20 % faster).

    Returns:
        The output_path on success.

    Raises:
        RuntimeError: If ffmpeg exits with a non-zero return code.
    """
    pts_factor = 1.0 / speed_factor
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        "-filter:v", f"setpts={pts_factor:.6f}*PTS",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg speed-up error: {result.stderr}")
    return output_path


def get_duration(file_path: Path) -> Optional[float]:
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
        return None
    except Exception:
        return None
