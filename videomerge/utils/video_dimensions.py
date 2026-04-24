"""Video dimension calculation utilities."""

from typing import Tuple

_RESOLUTION_DIMS = {
    "480p": {"16:9": (854, 480), "9:16": (480, 854), "1:1": (480, 480)},
    "720p": {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)},
    "1080p": {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)},
}

_MAX_IMAGE_RESOLUTION = "720p"


def calculate_image_dimensions(video_format: str | None, target_resolution: str | None) -> Tuple[int, int]:
    """Return image generation dimensions capped at 720p, preserving orientation.

    Regardless of the requested target_resolution, image generation never
    exceeds 720p so that API costs and generation time stay bounded.
    The aspect ratio (orientation) is always preserved.

    Args:
        video_format: Aspect ratio ("9:16", "16:9", "1:1"). Defaults to "9:16".
        target_resolution: Requested resolution ("480p", "720p", "1080p"). Defaults to "720p".

    Returns:
        Tuple of (width, height) in pixels, at most 720p.
    """
    fmt = video_format if video_format in _RESOLUTION_DIMS["720p"] else "9:16"
    res = target_resolution if target_resolution in _RESOLUTION_DIMS else "720p"
    # Cap: anything above 720p falls back to 720p
    capped = res if res in ("480p", "720p") else _MAX_IMAGE_RESOLUTION
    return _RESOLUTION_DIMS[capped][fmt]


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
        (480, 854)  # vertical video
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
    
    return _RESOLUTION_DIMS[target_resolution][video_format]
