"""Sample-accurate audio utilities using ffmpeg.

MP3 frames are ~26ms each; cutting MP3 with -c copy drifts by up to 26ms at
every scene boundary. We convert to PCM WAV once per run so all per-scene cuts
are frame-boundary-free.
"""

from __future__ import annotations

import subprocess


def convert_to_wav(source_path: str, output_path: str) -> None:
    """Convert any audio file to PCM WAV for sample-accurate cutting.

    Args:
        source_path: Path to source audio (MP3, AAC, etc.)
        output_path: Destination WAV path (will be overwritten if it exists)
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", source_path,
            "-acodec", "pcm_s16le",
            output_path,
        ],
        check=True,
        capture_output=True,
    )


def cut_audio_segment(
    source_wav_path: str,
    output_path: str,
    start_seconds: float,
    duration_seconds: float,
) -> None:
    """Cut a sample-accurate time slice from a WAV file using ffmpeg.

    Args:
        source_wav_path: Path to a PCM WAV file (use convert_to_wav first).
        output_path: Destination file path for the cut segment.
        start_seconds: Start offset in seconds.
        duration_seconds: Length of the segment in seconds.
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", source_wav_path,
            "-ss", str(start_seconds),
            "-t", str(duration_seconds),
            output_path,
        ],
        check=True,
        capture_output=True,
    )
