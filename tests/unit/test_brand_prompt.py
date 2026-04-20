"""Unit tests for videomerge.services.brand_prompt module.

Tests all pure functions for V-CaaS brief-aware prompt building.
"""

import pytest

from videomerge.models import Brief, PlatformBriefModel, SceneBrief, VisualDirection
from videomerge.services.brand_prompt import (
    aspect_ratio_to_video_format,
    build_image_prompt,
    build_prompt_items,
    build_script_from_brief,
    build_video_prompt,
    resolve_platform_brief,
    scene_length_frames,
)


class TestResolvePlatformBrief:
    """Tests for resolve_platform_brief function."""

    def test_hit_returns_matching_platform(self):
        """Returns the matching platform brief when found."""
        brief = Brief(
            platform_briefs=[
                PlatformBriefModel(platform="LinkedIn", scenes=[]),
                PlatformBriefModel(platform="Instagram", scenes=[]),
            ]
        )
        result = resolve_platform_brief(brief, "LinkedIn")
        assert result.platform == "LinkedIn"

    def test_miss_raises_value_error(self):
        """Raises ValueError when platform not found."""
        brief = Brief(
            platform_briefs=[
                PlatformBriefModel(platform="LinkedIn", scenes=[]),
            ]
        )
        with pytest.raises(ValueError) as exc_info:
            resolve_platform_brief(brief, "TikTok")
        assert "Platform 'TikTok' not found" in str(exc_info.value)
        assert "LinkedIn" in str(exc_info.value)

    def test_case_insensitive_match(self):
        """Matches platform case-insensitively."""
        brief = Brief(
            platform_briefs=[
                PlatformBriefModel(platform="LinkedIn", scenes=[]),
            ]
        )
        result = resolve_platform_brief(brief, "linkedin")
        assert result.platform == "LinkedIn"

        result = resolve_platform_brief(brief, "LINKEDIN")
        assert result.platform == "LinkedIn"


class TestBuildScriptFromBrief:
    """Tests for build_script_from_brief function."""

    def test_concatenates_spoken_lines(self):
        """Joins all spoken lines with spaces."""
        pb = PlatformBriefModel(
            platform="LinkedIn",
            scenes=[
                SceneBrief(
                    scene_number=1,
                    spoken_line="First line.",
                    caption_text="Caption 1",
                    duration_seconds=1.0,
                    visual_description="Visual 1",
                ),
                SceneBrief(
                    scene_number=2,
                    spoken_line="Second line.",
                    caption_text="Caption 2",
                    duration_seconds=1.0,
                    visual_description="Visual 2",
                ),
            ],
        )
        result = build_script_from_brief(pb)
        assert result == "First line. Second line."

    def test_handles_empty_spoken_lines(self):
        """Skips empty spoken_line values."""
        pb = PlatformBriefModel(
            platform="LinkedIn",
            scenes=[
                SceneBrief(
                    scene_number=1,
                    spoken_line="First line.",
                    caption_text="Caption 1",
                    duration_seconds=1.0,
                    visual_description="Visual 1",
                ),
                SceneBrief(
                    scene_number=2,
                    spoken_line="",
                    caption_text="Caption 2",
                    duration_seconds=1.0,
                    visual_description="Visual 2",
                ),
                SceneBrief(
                    scene_number=3,
                    spoken_line="Third line.",
                    caption_text="Caption 3",
                    duration_seconds=1.0,
                    visual_description="Visual 3",
                ),
            ],
        )
        result = build_script_from_brief(pb)
        assert result == "First line. Third line."

    def test_trims_whitespace(self):
        """Trims leading and trailing whitespace."""
        pb = PlatformBriefModel(
            platform="LinkedIn",
            scenes=[
                SceneBrief(
                    scene_number=1,
                    spoken_line="  First line.  ",
                    caption_text="Caption 1",
                    duration_seconds=1.0,
                    visual_description="Visual 1",
                ),
            ],
        )
        result = build_script_from_brief(pb)
        assert result == "First line."


class TestBuildImagePrompt:
    """Tests for build_image_prompt function."""

    def test_all_fields_included(self):
        """Includes all visual fields when present."""
        brief = Brief(
            visual_direction=VisualDirection(
                mood="optimistic",
                color_feel="warm pastels",
                shot_style="cinematic handheld",
                branding_elements="Tabario wordmark",
            ),
            platform_briefs=[],
        )
        pb = PlatformBriefModel(
            platform="LinkedIn",
            tone="confident, conversational",
            scenes=[],
        )
        scene = SceneBrief(
            scene_number=1,
            spoken_line="Test",
            caption_text="Test",
            duration_seconds=1.0,
            visual_description="A founder at a desk",
        )
        result = build_image_prompt(scene, pb, brief)
        assert "A founder at a desk" in result
        assert "confident, conversational" in result
        assert "optimistic" in result
        assert "warm pastels" in result
        assert "cinematic handheld" in result
        assert "Tabario wordmark" in result

    def test_missing_fields_skipped(self):
        """Skips falsy fields in the output."""
        brief = Brief(platform_briefs=[])
        pb = PlatformBriefModel(platform="LinkedIn", scenes=[])
        scene = SceneBrief(
            scene_number=1,
            spoken_line="Test",
            caption_text="Test",
            duration_seconds=1.0,
            visual_description="A founder at a desk",
        )
        result = build_image_prompt(scene, pb, brief)
        assert result == "A founder at a desk"

    def test_all_fields_combined_with_commas(self):
        """Combines all visual fields with comma separation."""
        brief = Brief(
            visual_direction=VisualDirection(
                mood="optimistic",
                color_feel="warm pastels",
                shot_style="cinematic",
                branding_elements="Tabario wordmark",
            ),
            platform_briefs=[],
        )
        pb = PlatformBriefModel(
            platform="LinkedIn",
            tone="confident",
            scenes=[],
        )
        scene = SceneBrief(
            scene_number=1,
            spoken_line="Test",
            caption_text="Test",
            duration_seconds=1.0,
            visual_description="A founder at a desk",
        )
        result = build_image_prompt(scene, pb, brief)
        # All fields should be present, comma-separated
        assert "A founder at a desk" in result
        assert "confident" in result
        assert "optimistic" in result
        assert "warm pastels" in result
        assert "cinematic" in result
        assert "Tabario wordmark" in result
        # Should be comma-separated
        assert ", " in result


class TestBuildVideoPrompt:
    """Tests for build_video_prompt function."""

    def test_motion_based_prompt(self):
        """Creates motion-biased prompt with tone and mood."""
        brief = Brief(
            visual_direction=VisualDirection(
                mood="optimistic",
                color_feel="warm pastels",
            ),
            platform_briefs=[],
        )
        pb = PlatformBriefModel(
            platform="LinkedIn",
            tone="confident, conversational",
            scenes=[],
        )
        scene = SceneBrief(
            scene_number=1,
            spoken_line="Test",
            caption_text="Test",
            duration_seconds=1.0,
            visual_description="A founder at a desk",
        )
        result = build_video_prompt(scene, pb, brief)
        assert "A founder at a desk" in result
        assert "confident, conversational" in result
        assert "optimistic" in result
        assert "warm pastels" in result

    def test_carries_tone_and_mood(self):
        """Includes tone and mood in video prompts."""
        brief = Brief(
            visual_direction=VisualDirection(mood="urgent"),
            platform_briefs=[],
        )
        pb = PlatformBriefModel(platform="LinkedIn", tone="professional", scenes=[])
        scene = SceneBrief(
            scene_number=1,
            spoken_line="Test",
            caption_text="Test",
            duration_seconds=1.0,
            visual_description="Test scene",
        )
        result = build_video_prompt(scene, pb, brief)
        assert "urgent" in result
        assert "professional" in result


class TestBuildPromptItems:
    """Tests for build_prompt_items function."""

    def test_preserves_scene_order(self):
        """Returns PromptItems in the same order as scenes."""
        brief = Brief(platform_briefs=[])
        pb = PlatformBriefModel(
            platform="LinkedIn",
            scenes=[
                SceneBrief(
                    scene_number=1,
                    spoken_line="First",
                    caption_text="Caption 1",
                    duration_seconds=1.0,
                    visual_description="Scene 1",
                ),
                SceneBrief(
                    scene_number=2,
                    spoken_line="Second",
                    caption_text="Caption 2",
                    duration_seconds=1.0,
                    visual_description="Scene 2",
                ),
                SceneBrief(
                    scene_number=3,
                    spoken_line="Third",
                    caption_text="Caption 3",
                    duration_seconds=1.0,
                    visual_description="Scene 3",
                ),
            ],
        )
        items = build_prompt_items(pb, brief)
        assert len(items) == 3
        assert "Scene 1" in items[0].image_prompt
        assert "Scene 2" in items[1].image_prompt
        assert "Scene 3" in items[2].image_prompt


class TestAspectRatioToVideoFormat:
    """Tests for aspect_ratio_to_video_format function."""

    def test_known_ratio_1_1(self):
        """Maps 1:1 to 1:1."""
        assert aspect_ratio_to_video_format("1:1") == "1:1"

    def test_known_ratio_9_16(self):
        """Maps 9:16 to 9:16."""
        assert aspect_ratio_to_video_format("9:16") == "9:16"

    def test_known_ratio_16_9(self):
        """Maps 16:9 to 16:9."""
        assert aspect_ratio_to_video_format("16:9") == "16:9"

    def test_unknown_ratio_defaults(self):
        """Unknown ratios default to 9:16."""
        assert aspect_ratio_to_video_format("4:3") == "9:16"
        assert aspect_ratio_to_video_format("21:9") == "9:16"
        assert aspect_ratio_to_video_format("invalid") == "9:16"


class TestSceneLengthFrames:
    """Tests for scene_length_frames function."""

    def test_fractional_seconds(self):
        """Handles fractional seconds correctly."""
        result = scene_length_frames(2.5, frame_rate=24)
        assert result == 60

    def test_zero_duration_clamped_to_min(self):
        """Zero duration clamps to minimum of 16 frames."""
        result = scene_length_frames(0, frame_rate=24)
        assert result == 16

    def test_exceeds_model_max_clamped(self):
        """Duration exceeding model_max is clamped."""
        result = scene_length_frames(100, frame_rate=24, model_max=1611)
        assert result == 1611

    def test_below_min_clamped(self):
        """Duration below minimum is clamped to 16."""
        result = scene_length_frames(0.5, frame_rate=24)
        assert result == 16

    def test_default_parameters(self):
        """Works with default parameters."""
        result = scene_length_frames(10.0)
        assert result == 240
        assert result <= 1611
        assert result >= 16
