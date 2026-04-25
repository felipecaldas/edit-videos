"""Unit tests for scene classifier."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from videomerge.models import Brief, PlatformBriefModel, SceneBrief, VisualDirection
from videomerge.services.scene_classifier import (
    SceneClassification,
    TextOverlay,
    classify_scenes,
    _build_system_prompt,
    _build_user_prompt,
    _call_llm,
    _parse_llm_response,
    _validate_classifications,
    _fallback_classifications,
)


@pytest.fixture
def sample_brief():
    """Create a sample brief for testing."""
    return Brief(
        visual_direction=VisualDirection(
            tone="professional",
            mood="inspiring",
            color_feel="vibrant",
            shot_style="cinematic"
        ),
        platform_briefs=[
            PlatformBriefModel(
                platform="LinkedIn",
                aspect_ratio="9:16",
                scenes=[
                    SceneBrief(
                        scene_number=1,
                        spoken_line="Meet Sarah, a founder struggling with video content.",
                        caption_text="Sarah's Story",
                        duration_seconds=3.0,
                        visual_description="Portrait of a young female founder at her desk"
                    ),
                    SceneBrief(
                        scene_number=2,
                        spoken_line="The problem? Creating videos takes too long.",
                        caption_text="THE PROBLEM",
                        duration_seconds=2.5,
                        visual_description="Large bold text 'PROBLEM' on abstract background"
                    ),
                    SceneBrief(
                        scene_number=3,
                        spoken_line="Until she discovered Tabario.",
                        caption_text="The Solution",
                        duration_seconds=2.0,
                        visual_description="Tabario logo with gradient background"
                    )
                ]
            )
        ]
    )


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    return json.dumps([
        {
            "scene_index": 0,
            "is_text_heavy": False,
            "image_provider": "runpod",
            "image_model": "z-image-turbo",
            "skip_image_generation": False,
            "prominent_text_overlay": None,
            "reasoning": "Scene shows a person - z-image-turbo excels at portraits"
        },
        {
            "scene_index": 1,
            "is_text_heavy": True,
            "image_provider": "fal",
            "image_model": "fal-ai/flux/dev",
            "skip_image_generation": False,
            "prominent_text_overlay": {
                "component": "kinetic_title",
                "text": "THE PROBLEM",
                "props": {"color": "#FF6B6B", "size": 96}
            },
            "reasoning": "Large text overlay required - Flux handles text-heavy backgrounds"
        },
        {
            "scene_index": 2,
            "is_text_heavy": False,
            "image_provider": "fal",
            "image_model": "fal-ai/flux/dev",
            "skip_image_generation": False,
            "prominent_text_overlay": None,
            "reasoning": "Abstract logo scene - Flux for quality"
        }
    ])


def test_build_system_prompt():
    """Test system prompt generation."""
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev", "fal-ai/flux-pro/v1.1"]):
        prompt = _build_system_prompt()
        
        assert "scene classifier" in prompt.lower()
        assert "z-image-turbo" in prompt
        assert "fal-ai/flux/dev" in prompt
        assert "kinetic_title" in prompt
        assert "JSON array" in prompt


def test_build_user_prompt(sample_brief):
    """Test user prompt generation."""
    prompt = _build_user_prompt(sample_brief, "LinkedIn", 3)
    
    assert "LinkedIn" in prompt
    assert "3 scenes" in prompt
    assert "Brief:" in prompt


def test_parse_llm_response_success(mock_llm_response):
    """Test parsing valid LLM response."""
    classifications = _parse_llm_response(mock_llm_response, 3)
    
    assert len(classifications) == 3
    assert classifications[0].scene_index == 0
    assert classifications[0].image_model == "z-image-turbo"
    assert classifications[0].is_text_heavy is False
    
    assert classifications[1].scene_index == 1
    assert classifications[1].is_text_heavy is True
    assert classifications[1].prominent_text_overlay is not None
    assert classifications[1].prominent_text_overlay.component == "kinetic_title"
    assert classifications[1].prominent_text_overlay.text == "THE PROBLEM"


def test_parse_llm_response_with_markdown_fences():
    """Test parsing LLM response with markdown code fences."""
    response = """```json
[
  {
    "scene_index": 0,
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "reasoning": "Test"
  }
]
```"""
    
    classifications = _parse_llm_response(response, 1)
    
    assert len(classifications) == 1
    assert classifications[0].image_model == "z-image-turbo"


def test_parse_llm_response_with_thinking_tags():
    """Test parsing LLM response with thinking tags."""
    response = """<think>Let me analyze these scenes...</think>
[
  {
    "scene_index": 0,
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "reasoning": "Test"
  }
]"""
    
    classifications = _parse_llm_response(response, 1)
    
    assert len(classifications) == 1
    assert classifications[0].image_model == "z-image-turbo"


def test_parse_llm_response_count_mismatch():
    """Test parsing fails when scene count doesn't match."""
    response = json.dumps([
        {
            "scene_index": 0,
            "is_text_heavy": False,
            "image_provider": "runpod",
            "image_model": "z-image-turbo",
            "skip_image_generation": False,
            "prominent_text_overlay": None,
            "reasoning": "Test"
        }
    ])
    
    with pytest.raises(RuntimeError, match="Scene count mismatch"):
        _parse_llm_response(response, 3)


def test_parse_llm_response_invalid_json():
    """Test parsing fails with invalid JSON."""
    with pytest.raises(RuntimeError, match="Failed to parse LLM response"):
        _parse_llm_response("not valid json", 1)


def test_parse_llm_response_invalid_schema():
    """Test parsing fails with invalid schema."""
    response = json.dumps([
        {
            "scene_index": 0,
            "is_text_heavy": "not a boolean",  # Invalid type
            "image_provider": "runpod",
            "image_model": "z-image-turbo"
        }
    ])
    
    with pytest.raises(RuntimeError, match="Invalid classification schema"):
        _parse_llm_response(response, 1)


def test_validate_classifications_success():
    """Test validation passes with valid classifications."""
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        classifications = [
            SceneClassification(
                scene_index=0,
                is_text_heavy=False,
                image_provider="runpod",
                image_model="z-image-turbo",
                reasoning="Test"
            ),
            SceneClassification(
                scene_index=1,
                is_text_heavy=True,
                image_provider="fal",
                image_model="fal-ai/flux/dev",
                prominent_text_overlay=TextOverlay(
                    component="kinetic_title",
                    text="TEST",
                    props={}
                ),
                reasoning="Test"
            )
        ]
        
        _validate_classifications(classifications, 2)


def test_validate_classifications_invalid_model():
    """Test validation fails with invalid model."""
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        classifications = [
            SceneClassification(
                scene_index=0,
                is_text_heavy=False,
                image_provider="fal",
                image_model="invalid-model",
                reasoning="Test"
            )
        ]
        
        with pytest.raises(RuntimeError, match="Invalid image_model"):
            _validate_classifications(classifications, 1)


def test_validate_classifications_corrects_provider():
    """Test validation corrects mismatched provider."""
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        classifications = [
            SceneClassification(
                scene_index=0,
                is_text_heavy=False,
                image_provider="fal",  # Wrong provider for z-image-turbo
                image_model="z-image-turbo",
                reasoning="Test"
            )
        ]
        
        _validate_classifications(classifications, 1)
        
        assert classifications[0].image_provider == "runpod"


def test_validate_classifications_skip_without_overlay():
    """Test validation fails when skip_image_generation=true without overlay."""
    with patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]):
        classifications = [
            SceneClassification(
                scene_index=0,
                is_text_heavy=True,
                image_provider="fal",
                image_model="fal-ai/flux/dev",
                skip_image_generation=True,
                prominent_text_overlay=None,  # Missing overlay
                reasoning="Test"
            )
        ]
        
        with pytest.raises(RuntimeError, match="requires prominent_text_overlay"):
            _validate_classifications(classifications, 1)


def test_fallback_classifications(sample_brief):
    """Test fallback classifications when classifier is disabled."""
    classifications = _fallback_classifications(sample_brief, "LinkedIn")
    
    assert len(classifications) == 3
    for cls in classifications:
        assert cls.image_provider == "runpod"
        assert cls.image_model == "z-image-turbo"
        assert cls.is_text_heavy is False
        assert cls.skip_image_generation is False
        assert cls.prominent_text_overlay is None
        assert "Fallback" in cls.reasoning


def test_fallback_classifications_invalid_platform(sample_brief):
    """Test fallback raises error for invalid platform."""
    with pytest.raises(ValueError, match="Platform 'Invalid' not found"):
        _fallback_classifications(sample_brief, "Invalid")


def test_call_llm_success(mock_llm_response):
    """Test successful LLM API call."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {"message": {"content": mock_llm_response}}
        ]
    }
    
    with patch("videomerge.services.scene_classifier.OPENROUTER_API_KEY", "test-key"), \
         patch("httpx.Client") as mock_client_class:
        
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        result = _call_llm("system prompt", "user prompt")
        
        assert result == mock_llm_response
        mock_client.post.assert_called_once()


def test_call_llm_missing_api_key():
    """Test LLM call fails without API key."""
    with patch("videomerge.services.scene_classifier.OPENROUTER_API_KEY", None):
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is required"):
            _call_llm("system", "user")


def test_classify_scenes_success(sample_brief, mock_llm_response):
    """Test full classification flow."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {"message": {"content": mock_llm_response}}
        ]
    }
    
    with patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True), \
         patch("videomerge.services.scene_classifier.OPENROUTER_API_KEY", "test-key"), \
         patch("videomerge.services.scene_classifier.FAL_IMAGE_MODELS", ["fal-ai/flux/dev"]), \
         patch("httpx.Client") as mock_client_class:
        
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        classifications = classify_scenes(sample_brief, "LinkedIn")
        
        assert len(classifications) == 3
        assert classifications[0].image_model == "z-image-turbo"
        assert classifications[1].is_text_heavy is True
        assert classifications[1].prominent_text_overlay.text == "THE PROBLEM"


def test_classify_scenes_disabled(sample_brief):
    """Test classification uses fallback when disabled."""
    with patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", False):
        classifications = classify_scenes(sample_brief, "LinkedIn")
        
        assert len(classifications) == 3
        for cls in classifications:
            assert cls.image_model == "z-image-turbo"
            assert "Fallback" in cls.reasoning


def test_classify_scenes_invalid_platform(sample_brief):
    """Test classification fails with invalid platform."""
    with patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True):
        with pytest.raises(ValueError, match="Platform 'Invalid' not found"):
            classify_scenes(sample_brief, "Invalid")


def test_text_overlay_model():
    """Test TextOverlay model validation."""
    overlay = TextOverlay(
        component="kinetic_title",
        text="TEST",
        props={"color": "#FF0000", "size": 96}
    )
    
    assert overlay.component == "kinetic_title"
    assert overlay.text == "TEST"
    assert overlay.props["color"] == "#FF0000"


def test_scene_classification_model():
    """Test SceneClassification model validation."""
    cls = SceneClassification(
        scene_index=0,
        is_text_heavy=True,
        image_provider="fal",
        image_model="fal-ai/flux/dev",
        skip_image_generation=False,
        prominent_text_overlay=TextOverlay(
            component="stagger_title",
            text="HELLO",
            props={}
        ),
        reasoning="Test scene"
    )

    assert cls.scene_index == 0
    assert cls.is_text_heavy is True
    assert cls.image_provider == "fal"
    assert cls.prominent_text_overlay.component == "stagger_title"


# Tests for classify_scenes_from_script
from videomerge.services.scene_classifier import (
    classify_scenes_from_script,
    _build_system_prompt_script_based,
    _build_user_prompt_script_based,
    _fallback_classifications_from_script,
)


def test_build_system_prompt_script_based():
    """Test system prompt generation for script-based classification."""
    prompt = _build_system_prompt_script_based()
    assert "scene classifier" in prompt.lower()
    assert "z-image-turbo" in prompt
    assert "Fal models" in prompt


def test_build_user_prompt_script_based():
    """Test user prompt generation for script-based classification."""
    script = "This is a test voiceover script."
    scenes = [
        {"image_prompt": "A person walking", "video_prompt": "Person walking forward"},
        {"image_prompt": "A city skyline", "video_prompt": "City at night"},
    ]
    prompt = _build_user_prompt_script_based(script, scenes)
    assert script in prompt
    assert "A person walking" in prompt
    assert "A city skyline" in prompt
    assert "2 scenes" in prompt


def test_fallback_classifications_from_script():
    """Test fallback classifications when classifier is disabled."""
    scenes = [
        {"image_prompt": "Scene 1"},
        {"image_prompt": "Scene 2"},
        {"image_prompt": "Scene 3"},
    ]
    with patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", False):
        result = _fallback_classifications_from_script(scenes)

    assert len(result) == 3
    assert all(cls.image_provider == "fal" for cls in result)
    assert all(cls.skip_image_generation is False for cls in result)


@patch("videomerge.services.scene_classifier._call_llm")
@patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True)
def test_classify_scenes_from_script_success(mock_call_llm):
    """Test successful script-based scene classification."""
    mock_call_llm.return_value = json.dumps([
        {
            "scene_index": 0,
            "is_text_heavy": False,
            "image_provider": "runpod",
            "image_model": "z-image-turbo",
            "skip_image_generation": False,
            "prominent_text_overlay": None,
            "reasoning": "Scene shows a person"
        },
        {
            "scene_index": 1,
            "is_text_heavy": False,
            "image_provider": "fal",
            "image_model": "fal-ai/flux-2-pro",
            "skip_image_generation": False,
            "prominent_text_overlay": None,
            "reasoning": "Abstract scene"
        }
    ])

    script = "Welcome to our product demo."
    scenes = [
        {"image_prompt": "A person presenting", "video_prompt": "Person at podium"},
        {"image_prompt": "Abstract geometric shapes", "video_prompt": "Shapes morphing"},
    ]

    result = classify_scenes_from_script(script, scenes)

    assert len(result) == 2
    assert result[0].image_provider == "runpod"
    assert result[0].image_model == "z-image-turbo"
    assert result[1].image_provider == "fal"
    assert result[1].image_model == "fal-ai/flux-2-pro"
    mock_call_llm.assert_called_once()


@patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True)
def test_classify_scenes_from_script_empty_scenes():
    """Test script-based classification with empty scenes list."""
    script = "Test script"
    scenes = []

    result = classify_scenes_from_script(script, scenes)

    assert len(result) == 0


@patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", False)
def test_classify_scenes_from_script_disabled():
    """Test script-based classification when disabled."""
    script = "Test script"
    scenes = [
        {"image_prompt": "Scene 1"},
        {"image_prompt": "Scene 2"},
    ]

    result = classify_scenes_from_script(script, scenes)

    assert len(result) == 2
    # Should use fallback with Fal default
    assert all(cls.image_provider == "fal" for cls in result)


@patch("videomerge.services.scene_classifier._call_llm")
@patch("videomerge.services.scene_classifier.SCENE_CLASSIFIER_ENABLED", True)
def test_classify_scenes_from_script_invalid_json(mock_call_llm):
    """Test script-based classification with invalid LLM response."""
    mock_call_llm.return_value = "not valid json"

    script = "Test script"
    scenes = [{"image_prompt": "Scene 1"}]

    with pytest.raises(RuntimeError, match="Failed to parse LLM response"):
        classify_scenes_from_script(script, scenes)
