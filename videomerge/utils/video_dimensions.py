"""Video dimension calculation utilities."""

from typing import Tuple


def calculate_video_dimensions(video_format: str, target_resolution: str) -> Tuple[int, int]:
    """
    Calculate video width and height based on format and resolution.
    
    Args:
        video_format: Video aspect ratio ("9:16", "16:9", or "1:1")
        target_resolution: Target resolution ("480p", "720p", or "1080p")
    
    Returns:
        Tuple of (width, height) in pixels
        
    Raises:
        ValueError: If video_format or target_resolution is not supported
        
    Examples:
        >>> calculate_video_dimensions("9:16", "480p")
        (360, 640)  # vertical video
        >>> calculate_video_dimensions("16:9", "480p") 
        (854, 480)  # horizontal video
        >>> calculate_video_dimensions("1:1", "480p")
        (480, 480)  # square video
    """
    # Validate inputs
    supported_formats = {"9:16", "16:9", "1:1"}
    supported_resolutions = {"480p", "720p", "1080p"}
    
    if video_format not in supported_formats:
        raise ValueError(f"Unsupported video_format '{video_format}'. Supported formats: {sorted(supported_formats)}")
    
    if target_resolution not in supported_resolutions:
        raise ValueError(f"Unsupported target_resolution '{target_resolution}'. Supported resolutions: {sorted(supported_resolutions)}")
    
    # Base dimensions for each resolution
    resolution_bases = {
        "480p": {"16:9": (854, 480), "9:16": (360, 640), "1:1": (480, 480)},
        "720p": {"16:9": (1280, 720), "9:16": (405, 720), "1:1": (720, 720)},
        "1080p": {"16:9": (1920, 1080), "9:16": (607, 1080), "1:1": (1080, 1080)},
    }
    
    return resolution_bases[target_resolution][video_format]
