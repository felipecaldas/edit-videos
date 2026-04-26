"""Unit tests for videomerge.services.brand_prompt module.

Tests all pure functions for V-CaaS brief-aware prompt building.
"""

import pytest

from videomerge.models import Brief, PlatformBriefModel, SceneBrief, VisualDirection
from videomerge.services.brand_prompt import (
    _DEFAULT_NEGATIVE_TERMS,
    aspect_ratio_to_video_format,
    build_image_prompt,
    build_negative_prompt,
    build_prompt_items,
    build_script_from_brief,
    build_video_prompt,
    resolve_platform_brief,
    sanitize_visual_description,
    scene_length_frames,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scene(
    number: int = 1,
    spoken_line: str = "Test",
    caption: str = "Caption",
    duration: float = 1.0,
    visual: str = "A founder at a desk",
) -> SceneBrief:
    return SceneBrief(
        scene_number=number,
        spoken_line=spoken_line,
        caption_text=caption,
        duration_seconds=duration,
        visual_description=visual,
    )


def _make_pb(tone: str = "confident, conversational", scenes=None) -> PlatformBriefModel:
    return PlatformBriefModel(
        platform="LinkedIn",
        tone=tone,
        scenes=scenes or [],
    )


# ---------------------------------------------------------------------------
# resolve_platform_brief
# ---------------------------------------------------------------------------

class TestResolvePlatformBrief:
    def test_hit_returns_matching_platform(self):
        brief = Brief(
            platform_briefs=[
                PlatformBriefModel(platform="LinkedIn", scenes=[]),
                PlatformBriefModel(platform="Instagram", scenes=[]),
            ]
        )
        result = resolve_platform_brief(brief, "LinkedIn")
        assert result.platform == "LinkedIn"

    def test_miss_raises_value_error(self):
        brief = Brief(platform_briefs=[PlatformBriefModel(platform="LinkedIn", scenes=[])])
        with pytest.raises(ValueError) as exc_info:
            resolve_platform_brief(brief, "TikTok")
        assert "Platform 'TikTok' not found" in str(exc_info.value)
        assert "LinkedIn" in str(exc_info.value)

    def test_case_insensitive_match(self):
        brief = Brief(platform_briefs=[PlatformBriefModel(platform="LinkedIn", scenes=[])])
        assert resolve_platform_brief(brief, "linkedin").platform == "LinkedIn"
        assert resolve_platform_brief(brief, "LINKEDIN").platform == "LinkedIn"


# ---------------------------------------------------------------------------
# build_script_from_brief
# ---------------------------------------------------------------------------

class TestBuildScriptFromBrief:
    def test_concatenates_spoken_lines(self):
        pb = _make_pb(
            scenes=[
                _make_scene(1, spoken_line="First line."),
                _make_scene(2, spoken_line="Second line."),
            ]
        )
        assert build_script_from_brief(pb) == "First line. Second line."

    def test_handles_empty_spoken_lines(self):
        pb = _make_pb(
            scenes=[
                _make_scene(1, spoken_line="First line."),
                _make_scene(2, spoken_line=""),
                _make_scene(3, spoken_line="Third line."),
            ]
        )
        assert build_script_from_brief(pb) == "First line. Third line."

    def test_trims_whitespace(self):
        pb = _make_pb(scenes=[_make_scene(1, spoken_line="  First line.  ")])
        assert build_script_from_brief(pb) == "First line."


# ---------------------------------------------------------------------------
# build_negative_prompt
# ---------------------------------------------------------------------------

class TestBuildNegativePrompt:
    def test_returns_non_empty_string(self):
        result = build_negative_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_all_default_terms(self):
        result = build_negative_prompt()
        for term in _DEFAULT_NEGATIVE_TERMS:
            assert term in result, f"Default term '{term}' missing from negative prompt"

    def test_comma_separated(self):
        result = build_negative_prompt()
        assert ", " in result

    def test_extra_terms_appended(self):
        result = build_negative_prompt(extra_terms=["corporate stock photo", "generic office"])
        assert "corporate stock photo" in result
        assert "generic office" in result

    def test_duplicate_extra_terms_deduplicated(self):
        # "blurry" is already in defaults — should not appear twice
        result = build_negative_prompt(extra_terms=["blurry", "new term"])
        terms = [t.strip() for t in result.split(",")]
        assert terms.count("blurry") == 1

    def test_empty_extra_terms_ignored(self):
        result = build_negative_prompt(extra_terms=["", "  ", None])  # type: ignore[list-item]
        # Should not raise and should not add empty entries
        for term in result.split(", "):
            assert term.strip() != ""

    def test_none_extra_terms_same_as_defaults(self):
        assert build_negative_prompt(None) == build_negative_prompt()


# ---------------------------------------------------------------------------
# sanitize_visual_description
# ---------------------------------------------------------------------------

class TestSanitizeVisualDescription:
    def test_no_brand_name_returns_unchanged(self):
        text = "A founder at a desk at night"
        assert sanitize_visual_description(text) == text

    def test_strips_brand_name_case_insensitive(self):
        result = sanitize_visual_description("A Tabario dashboard UI shot", "Tabario")
        assert "Tabario" not in result
        assert "tabario" not in result.lower() or "Tabario" not in result

    def test_strips_brand_name_mixed_case(self):
        result = sanitize_visual_description("TABARIO logo appears", "Tabario")
        assert "TABARIO" not in result

    def test_normalises_extra_whitespace(self):
        result = sanitize_visual_description("A  Tabario  logo", "Tabario")
        assert "  " not in result

    def test_empty_text_returns_empty(self):
        assert sanitize_visual_description("", "Tabario") == ""

    def test_none_brand_name_no_op(self):
        text = "Tabario dashboard scene"
        assert sanitize_visual_description(text, None) == text

    def test_does_not_strip_partial_word(self):
        # "Tabario" should not strip "Tabarios" or "preTabario" — word boundary
        result = sanitize_visual_description("Tabarios and Tabario tools", "Tabario")
        # "Tabario" (exact word) is removed; "Tabarios" is NOT a whole-word match
        assert "Tabarios" in result


# ---------------------------------------------------------------------------
# build_image_prompt
# ---------------------------------------------------------------------------

class TestBuildImagePrompt:
    def test_includes_all_cinematic_fields(self):
        brief = Brief(
            visual_direction=VisualDirection(
                mood="optimistic",
                color_feel="warm pastels",
                shot_style="cinematic handheld",
            ),
            platform_briefs=[],
        )
        pb = _make_pb(tone="confident, conversational")
        scene = _make_scene(visual="A founder at a desk")
        result = build_image_prompt(scene, pb, brief)
        assert "A founder at a desk" in result
        assert "confident, conversational" in result
        assert "optimistic" in result
        assert "warm pastels" in result
        assert "cinematic handheld" in result

    def test_never_contains_branding_elements(self):
        """branding_elements was removed from VisualDirection — image prompts must never carry it."""
        brief = Brief(platform_briefs=[])
        pb = _make_pb()
        scene = _make_scene()
        result = build_image_prompt(scene, pb, brief)
        assert "Tabario" not in result
        assert "logo" not in result.lower()

    def test_missing_fields_skipped(self):
        brief = Brief(platform_briefs=[])
        pb = PlatformBriefModel(platform="LinkedIn", scenes=[])
        scene = _make_scene(visual="A founder at a desk")
        result = build_image_prompt(scene, pb, brief)
        assert result == "A founder at a desk"

    def test_fields_comma_separated(self):
        brief = Brief(
            visual_direction=VisualDirection(mood="optimistic", color_feel="warm pastels"),
            platform_briefs=[],
        )
        pb = _make_pb(tone="confident")
        scene = _make_scene(visual="A founder at a desk")
        result = build_image_prompt(scene, pb, brief)
        assert ", " in result

    def test_sanitize_applied_to_visual_description(self):
        """sanitize_visual_description is called even when brand_name=None — no-op, no crash."""
        brief = Brief(platform_briefs=[])
        pb = _make_pb()
        scene = _make_scene(visual="A person using a product tool")
        result = build_image_prompt(scene, pb, brief)
        assert "A person using a product tool" in result


# ---------------------------------------------------------------------------
# build_video_prompt
# ---------------------------------------------------------------------------

class TestBuildVideoPrompt:
    def test_motion_based_prompt(self):
        brief = Brief(
            visual_direction=VisualDirection(mood="optimistic", color_feel="warm pastels"),
            platform_briefs=[],
        )
        pb = _make_pb(tone="confident, conversational")
        scene = _make_scene()
        result = build_video_prompt(scene, pb, brief)
        assert "A founder at a desk" in result
        assert "confident, conversational" in result
        assert "optimistic" in result
        assert "warm pastels" in result

    def test_carries_tone_and_mood(self):
        brief = Brief(visual_direction=VisualDirection(mood="urgent"), platform_briefs=[])
        pb = _make_pb(tone="professional")
        scene = _make_scene()
        result = build_video_prompt(scene, pb, brief)
        assert "urgent" in result
        assert "professional" in result


# ---------------------------------------------------------------------------
# build_prompt_items
# ---------------------------------------------------------------------------

class TestBuildPromptItems:
    def test_preserves_scene_order(self):
        brief = Brief(platform_briefs=[])
        pb = _make_pb(
            scenes=[
                _make_scene(1, visual="Scene 1"),
                _make_scene(2, visual="Scene 2"),
                _make_scene(3, visual="Scene 3"),
            ]
        )
        items = build_prompt_items(pb, brief)
        assert len(items) == 3
        assert "Scene 1" in items[0].image_prompt
        assert "Scene 2" in items[1].image_prompt
        assert "Scene 3" in items[2].image_prompt


# ---------------------------------------------------------------------------
# aspect_ratio_to_video_format
# ---------------------------------------------------------------------------

class TestAspectRatioToVideoFormat:
    def test_known_ratio_1_1(self):
        assert aspect_ratio_to_video_format("1:1") == "1:1"

    def test_known_ratio_9_16(self):
        assert aspect_ratio_to_video_format("9:16") == "9:16"

    def test_known_ratio_16_9(self):
        assert aspect_ratio_to_video_format("16:9") == "16:9"

    def test_unknown_ratio_defaults(self):
        assert aspect_ratio_to_video_format("4:3") == "9:16"
        assert aspect_ratio_to_video_format("21:9") == "9:16"
        assert aspect_ratio_to_video_format("invalid") == "9:16"


# ---------------------------------------------------------------------------
# scene_length_frames
# ---------------------------------------------------------------------------

class TestSceneLengthFrames:
    def test_fractional_seconds(self):
        assert scene_length_frames(2.5, frame_rate=24) == 60

    def test_zero_duration_clamped_to_min(self):
        assert scene_length_frames(0, frame_rate=24) == 16

    def test_exceeds_model_max_clamped(self):
        assert scene_length_frames(100, frame_rate=24, model_max=1611) == 1611

    def test_below_min_clamped(self):
        assert scene_length_frames(0.5, frame_rate=24) == 16

    def test_default_parameters(self):
        result = scene_length_frames(10.0)
        assert result == 240
        assert 16 <= result <= 1611
