"""Unit tests for TAB-164: scene classifier hardening (pre-filter + post-validator)."""

import json
from unittest.mock import patch

import pytest

from videomerge.services.scene_classifier import (
    SceneClassification,
    _enforce_ui_overrides,
    _ui_pre_filter,
    classify_scenes_from_script,
)


# ---------------------------------------------------------------------------
# Pre-filter unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description,expected_match", [
    ("Screencast of a dashboard with analytics", True),
    ("UI mockup showing different fonts and colors", True),
    ("Split-screen workflow tool with browser tabs open", True),
    ("Statistics overlay on a bar chart with a CTA button", True),
    ("Percentage growth graph with headline text", True),
    ("Professional portrait of a founder at her desk", False),
    ("Abstract landscape with mountains and fog", False),
    ("A person walks through a forest at golden hour", False),
])
def test_ui_pre_filter_keywords(description, expected_match):
    """Pre-filter correctly identifies descriptions with UI/screen keywords."""
    matched = _ui_pre_filter([description])
    assert bool(matched) == expected_match, (
        f"Expected match={expected_match} for: {description!r}"
    )


def test_ui_pre_filter_returns_correct_indices():
    """Pre-filter returns the indices of matched descriptions, not all."""
    descriptions = [
        "A founder talking to camera",          # 0 — no match
        "Dashboard view of the app interface",  # 1 — match (dashboard, interface)
        "Abstract geometric shapes",            # 2 — no match
        "Browser showing statistics and CTA",   # 3 — match (browser, statistics, CTA)
        "Cinematic skyline at dawn",             # 4 — no match
    ]
    matched = _ui_pre_filter(descriptions)
    assert matched == {1, 3}


# ---------------------------------------------------------------------------
# Post-validator (_enforce_ui_overrides) unit tests
# ---------------------------------------------------------------------------

def _make_cls(scene_index: int, override: str | None = None, is_text_heavy: bool = False) -> SceneClassification:
    return SceneClassification(
        scene_index=scene_index,
        is_text_heavy=is_text_heavy,
        image_provider="fal",
        image_model="fal-ai/flux/dev",
        skip_image_generation=False,
        image_prompt_override=override,
        reasoning="test",
    )


def test_enforce_ui_overrides_forces_is_text_heavy():
    """Matched scenes always get is_text_heavy=True after enforcement."""
    cls = _make_cls(0, override=None, is_text_heavy=False)
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        _enforce_ui_overrides([cls], ui_matched_indices={0})
    assert cls.is_text_heavy is True


def test_enforce_ui_overrides_applies_fallback_when_no_override():
    """Matched scene without LLM override gets deterministic fallback applied."""
    cls = _make_cls(0, override=None)
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        _enforce_ui_overrides([cls], ui_matched_indices={0})
    assert cls.image_prompt_override is not None
    assert len(cls.image_prompt_override) > 10


def test_enforce_ui_overrides_preserves_existing_override():
    """Matched scene that already has an LLM override keeps its override unchanged."""
    original_override = "Aerial view of a forest, no UI, no screens"
    cls = _make_cls(0, override=original_override)
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        _enforce_ui_overrides([cls], ui_matched_indices={0})
    assert cls.image_prompt_override == original_override


def test_enforce_ui_overrides_leaves_unmatched_scenes_alone():
    """Scenes not in ui_matched_indices are not touched."""
    cls = _make_cls(1, override=None, is_text_heavy=False)
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        _enforce_ui_overrides([cls], ui_matched_indices={0})  # index 0 matched, not 1
    assert cls.image_prompt_override is None
    assert cls.is_text_heavy is False


# ---------------------------------------------------------------------------
# End-to-end: classify_scenes_from_script with UI scenes 0, 1, 4
# ---------------------------------------------------------------------------

_EXAMPLE_SCENES_WITH_UI = [
    {"image_prompt": "Screencast of the app dashboard with user statistics"},   # 0 — UI
    {"image_prompt": "UI mockup showing fonts and color palette of the brand"}, # 1 — UI
    {"image_prompt": "Founder speaking directly into camera, clean background"},# 2 — no UI
    {"image_prompt": "Abstract forest environment, misty morning"},             # 3 — no UI
    {"image_prompt": "Browser tab open on the analytics interface with CTA"},   # 4 — UI
]

_LLM_RESPONSE_MISSING_OVERRIDES = json.dumps([
    {
        "scene_index": 0,
        "scene_type": "concept_visual",
        "is_text_heavy": False,
        "image_provider": "fal",
        "image_model": "fal-ai/flux/dev",
        "skip_image_generation": False,
        "prominent_text_overlay": None,
        "image_prompt_override": None,  # LLM silently skipped — should be caught by post-validator
        "reasoning": "Dashboard scene",
    },
    {
        "scene_index": 1,
        "scene_type": "concept_visual",
        "is_text_heavy": False,
        "image_provider": "fal",
        "image_model": "fal-ai/flux/dev",
        "skip_image_generation": False,
        "prominent_text_overlay": None,
        "image_prompt_override": None,  # LLM silently skipped
        "reasoning": "UI mockup scene",
    },
    {
        "scene_index": 2,
        "scene_type": "talking_head",
        "is_text_heavy": False,
        "image_provider": "fal",
        "image_model": "fal-ai/flux/dev",
        "skip_image_generation": False,
        "prominent_text_overlay": None,
        "image_prompt_override": "Portrait of a confident founder, studio lighting",
        "reasoning": "Talking head",
    },
    {
        "scene_index": 3,
        "scene_type": "concept_visual",
        "is_text_heavy": False,
        "image_provider": "fal",
        "image_model": "fal-ai/flux/dev",
        "skip_image_generation": False,
        "prominent_text_overlay": None,
        "image_prompt_override": None,
        "reasoning": "Abstract scene — no override needed",
    },
    {
        "scene_index": 4,
        "scene_type": "concept_visual",
        "is_text_heavy": False,
        "image_provider": "fal",
        "image_model": "fal-ai/flux/dev",
        "skip_image_generation": False,
        "prominent_text_overlay": None,
        "image_prompt_override": None,  # LLM silently skipped
        "reasoning": "Browser/analytics scene",
    },
])


@patch("videomerge.services.scene_classifier._call_llm", return_value=_LLM_RESPONSE_MISSING_OVERRIDES)
@patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True)
@patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"])
def test_pre_filter_forces_override_on_scenes_0_1_4(_mock_llm):
    """Pre-filter + post-validator ensure scenes 0, 1, 4 (UI keywords) get image_prompt_override
    even when the LLM silently returned null for those fields."""
    result = classify_scenes_from_script("A product demo script.", _EXAMPLE_SCENES_WITH_UI)

    assert len(result) == 5

    # Scenes 0, 1, 4 had UI keywords — must have non-null overrides and is_text_heavy=True
    for idx in (0, 1, 4):
        cls = result[idx]
        assert cls.image_prompt_override is not None, (
            f"Scene {idx} should have image_prompt_override set (UI keyword matched)"
        )
        assert cls.is_text_heavy is True, (
            f"Scene {idx} should have is_text_heavy=True (UI keyword matched)"
        )

    # Scenes 2, 3 had no UI keywords — should be unchanged
    assert result[2].image_prompt_override == "Portrait of a confident founder, studio lighting"
    assert result[3].image_prompt_override is None


@patch("videomerge.services.scene_classifier._call_llm", return_value=_LLM_RESPONSE_MISSING_OVERRIDES)
@patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True)
@patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"])
def test_llm_silent_skip_gets_non_null_override_for_ui_scenes(_mock_llm):
    """Any scene with UI keywords in its description always ends up with non-null
    image_prompt_override, even when the LLM emitted null."""
    result = classify_scenes_from_script("Product demo.", _EXAMPLE_SCENES_WITH_UI)
    for cls in result:
        desc = _EXAMPLE_SCENES_WITH_UI[cls.scene_index].get("image_prompt", "")
        from videomerge.services.scene_classifier import _UI_KEYWORD_RE
        if _UI_KEYWORD_RE.search(desc):
            assert cls.image_prompt_override is not None, (
                f"Scene {cls.scene_index} has UI keyword but image_prompt_override is null"
            )
