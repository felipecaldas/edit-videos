"""Pure-function helper module for V-CaaS brief-aware prompt building.

This module provides utilities to resolve platform briefs, build scripts,
and compose enriched image/video prompts from the Brief data structure.
Safe to call from Temporal workflow code (no I/O).
"""

from typing import List

from videomerge.models import (
    Brief,
    PlatformBriefModel,
    PromptItem,
    SceneBrief,
    VisualDirection,
)


def resolve_platform_brief(brief: Brief, platform: str) -> PlatformBriefModel:
    """Resolve the platform brief for a given platform name.

    Performs a case-insensitive match on the platform name.

    Args:
        brief: The top-level Brief object containing platform_briefs.
        platform: Platform identifier (e.g., 'LinkedIn', 'instagram').

    Returns:
        The matching PlatformBriefModel.

    Raises:
        ValueError: If no matching platform is found.
    """
    platform_lower = platform.lower()
    for pb in brief.platform_briefs:
        if pb.platform.lower() == platform_lower:
            return pb
    available = [pb.platform for pb in brief.platform_briefs]
    raise ValueError(
        f"Platform '{platform}' not found in brief.platform_briefs. "
        f"Available platforms: {available}"
    )


def build_script_from_brief(pb: PlatformBriefModel) -> str:
    """Build the TTS script by concatenating spoken lines.

    Joins non-empty spoken_line values with spaces and trims whitespace.

    Args:
        pb: The PlatformBriefModel containing scenes.

    Returns:
        The concatenated script string.
    """
    segments = [scene.spoken_line for scene in pb.scenes if scene.spoken_line]
    return " ".join(segments).strip()


def build_image_prompt(
    scene: SceneBrief, pb: PlatformBriefModel, brief: Brief
) -> str:
    """Build an enriched image-generation prompt for a scene.

    Combines visual_description with tone, mood, color_feel, shot_style,
    and branding_elements, skipping any falsy segments.

    Args:
        scene: The SceneBrief for this scene.
        pb: The PlatformBriefModel containing platform-specific settings.
        brief: The top-level Brief for cross-platform settings.

    Returns:
        The enriched image prompt string.
    """
    segments = []

    if scene.visual_description:
        segments.append(scene.visual_description)

    if pb.tone:
        segments.append(pb.tone)

    if brief.visual_direction:
        vd: VisualDirection = brief.visual_direction
        if vd.mood:
            segments.append(vd.mood)
        if vd.color_feel:
            segments.append(vd.color_feel)
        if vd.shot_style:
            segments.append(vd.shot_style)
        if vd.branding_elements:
            segments.append(vd.branding_elements)

    return ", ".join(segments)


def build_video_prompt(
    scene: SceneBrief, pb: PlatformBriefModel, brief: Brief
) -> str:
    """Build an enriched image-to-video prompt for a scene.

    Creates a motion-biased prompt that carries tone and mood context.

    Args:
        scene: The SceneBrief for this scene.
        pb: The PlatformBriefModel containing platform-specific settings.
        brief: The top-level Brief for cross-platform settings.

    Returns:
        The enriched video prompt string.
    """
    segments = []

    if scene.visual_description:
        segments.append(scene.visual_description)

    if pb.tone:
        segments.append(pb.tone)

    if brief.visual_direction:
        vd: VisualDirection = brief.visual_direction
        if vd.mood:
            segments.append(vd.mood)
        if vd.color_feel:
            segments.append(vd.color_feel)

    return ", ".join(segments)


def build_prompt_items(pb: PlatformBriefModel, brief: Brief) -> List[PromptItem]:
    """Build a list of PromptItem objects, one per scene.

    Preserves scene order from the platform_brief.

    Args:
        pb: The PlatformBriefModel containing scenes.
        brief: The top-level Brief for cross-platform settings.

    Returns:
        List of PromptItem objects in scene order.
    """
    items: List[PromptItem] = []
    for scene in pb.scenes:
        image_prompt = build_image_prompt(scene, pb, brief)
        video_prompt = build_video_prompt(scene, pb, brief)
        items.append(
            PromptItem(
                image_prompt=image_prompt if image_prompt else None,
                video_prompt=video_prompt if video_prompt else None,
            )
        )
    return items


def aspect_ratio_to_video_format(aspect: str) -> str:
    """Convert aspect ratio string to video format.

    Args:
        aspect: Aspect ratio string (e.g., '1:1', '9:16', '16:9').

    Returns:
        Video format string. Unknown ratios default to '9:16'.
    """
    valid_ratios = {"1:1", "9:16", "16:9"}
    if aspect in valid_ratios:
        return aspect
    return "9:16"


def scene_length_frames(
    duration_seconds: float, frame_rate: int = 24, model_max: int = 1611
) -> int:
    """Calculate the number of frames for a scene based on duration.

    Clamps the result to be at least 16 frames and at most model_max.

    Args:
        duration_seconds: Target duration in seconds.
        frame_rate: Frames per second (default 24).
        model_max: Maximum frames allowed (default 1611).

    Returns:
        The calculated frame count, clamped to [16, model_max].
    """
    frames = int(duration_seconds * frame_rate)
    return max(16, min(frames, model_max))
