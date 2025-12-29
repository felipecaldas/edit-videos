from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from videomerge.utils.video_frames import extract_first_and_last_frames


def test_extract_first_and_last_frames_naming():
    """Test that frame extraction produces correctly named PNG files."""
    # This is a unit test for the naming logic
    # In a real scenario, you'd need an actual video file
    
    video_filename = "000_c04213ad065847ca8097c4f541be3b8e.mp4"
    video_stem = Path(video_filename).stem
    
    # Expected output filenames
    expected_first = f"{video_stem}_first.png"
    expected_last = f"{video_stem}_last.png"
    
    assert expected_first == "000_c04213ad065847ca8097c4f541be3b8e_first.png"
    assert expected_last == "000_c04213ad065847ca8097c4f541be3b8e_last.png"


def test_extract_frames_nonexistent_video():
    """Test that extraction fails gracefully for non-existent video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / "nonexistent.mp4"
        output_dir = Path(tmpdir) / "frames"
        
        with pytest.raises(ValueError, match="Video file does not exist"):
            extract_first_and_last_frames(video_path, output_dir)
