from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple

from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def extract_first_and_last_frames(
    video_path: Path,
    output_dir: Path,
) -> Tuple[Path, Path]:
    """Extract the first and last frames from a video file as PNG images.
    
    Args:
        video_path: Path to the video file (e.g., 000_c04213ad065847ca8097c4f541be3b8e.mp4)
        output_dir: Directory where the PNG frames should be saved
        
    Returns:
        Tuple of (first_frame_path, last_frame_path)
        
    Raises:
        RuntimeError: If ffmpeg fails to extract frames
        ValueError: If video_path does not exist
    """
    if not video_path.exists():
        raise ValueError(f"Video file does not exist: {video_path}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate output filenames based on video filename
    # e.g., 000_c04213ad065847ca8097c4f541be3b8e.mp4 -> 000_c04213ad065847ca8097c4f541be3b8e_first.png
    video_stem = video_path.stem
    first_frame_path = output_dir / f"{video_stem}_first.png"
    last_frame_path = output_dir / f"{video_stem}_last.png"
    
    # Extract first frame (frame 0)
    logger.debug(f"[video_frames] Extracting first frame from {video_path} to {first_frame_path}")
    first_cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(video_path),
        '-vf', 'select=eq(n\\,0)',
        '-vframes', '1',
        str(first_frame_path)
    ]
    
    result = subprocess.run(first_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"[video_frames] Failed to extract first frame: {result.stderr}")
        raise RuntimeError(f"Failed to extract first frame from {video_path}: {result.stderr}")
    
    # Extract last frame
    # Using select='eq(n,0)' with reverse input to get the last frame efficiently
    logger.debug(f"[video_frames] Extracting last frame from {video_path} to {last_frame_path}")
    last_cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-sseof', '-0.1',  # Seek to 0.1 seconds before end
        '-i', str(video_path),
        '-update', '1',
        '-frames:v', '1',
        str(last_frame_path)
    ]
    
    result = subprocess.run(last_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"[video_frames] Failed to extract last frame: {result.stderr}")
        raise RuntimeError(f"Failed to extract last frame from {video_path}: {result.stderr}")
    
    logger.info(f"[video_frames] Extracted frames: {first_frame_path}, {last_frame_path}")
    return first_frame_path, last_frame_path
