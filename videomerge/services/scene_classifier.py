"""Scene classifier for text-heavy detection and image model selection.

This module uses an LLM (Gemini 2.5 Flash via OpenRouter) to analyze scenes
and determine:
- Whether the scene is text-heavy (requires prominent text overlays)
- Which image generation model is best suited (Fal vs Runpod)
- Whether to skip image/video generation entirely (pure typographic scenes)
- Text overlay configuration for Remotion compositor

The classifier makes a single LLM call per brief and returns classifications
for all scenes in the platform brief.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from videomerge.config import (
    FAL_IMAGE_DEFAULT,
    FAL_IMAGE_MODELS,
    OPENROUTER_API_KEY,
    SCENE_CLASSIFIER_ENABLED,
    SCENE_CLASSIFIER_MODEL,
    SCENE_CLASSIFIER_PROVIDER,
)
from videomerge.models import Brief
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class TextOverlay(BaseModel):
    """Text overlay configuration for Remotion compositor."""
    
    component: Literal["kinetic_title", "stagger_title", "caption_bar"]
    text: Optional[str] = None
    props: Dict[str, Any] = Field(default_factory=dict)


class SceneClassification(BaseModel):
    """Classification result for a single scene."""
    
    scene_index: int
    is_text_heavy: bool
    image_provider: Literal["fal", "runpod"]
    image_model: str
    skip_image_generation: bool = False
    prominent_text_overlay: Optional[TextOverlay] = None
    reasoning: str = ""


def classify_scenes(brief: Brief, platform: str) -> List[SceneClassification]:
    """Classify all scenes in a brief for provider routing and text-heavy detection.
    
    Args:
        brief: The top-level Brief object containing platform_briefs and visual_direction
        platform: Platform identifier (e.g., 'LinkedIn', 'Instagram')
    
    Returns:
        List of SceneClassification objects, one per scene in the platform brief
    
    Raises:
        ValueError: If platform not found in brief.platform_briefs or classifier disabled
        RuntimeError: If LLM call fails or returns invalid JSON
    """
    if not SCENE_CLASSIFIER_ENABLED:
        logger.warning("[classifier] Scene classifier is disabled, using fallback")
        return _fallback_classifications(brief, platform)
    
    # Find platform brief
    platform_brief = None
    for pb in brief.platform_briefs:
        if pb.platform.lower() == platform.lower():
            platform_brief = pb
            break
    
    if not platform_brief:
        raise ValueError(f"Platform '{platform}' not found in brief.platform_briefs")
    
    num_scenes = len(platform_brief.scenes)
    logger.info(
        "[classifier] Classifying %d scenes for platform=%s, provider=%s, model=%s",
        num_scenes, platform, SCENE_CLASSIFIER_PROVIDER, SCENE_CLASSIFIER_MODEL
    )
    
    # Build LLM prompt
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(brief, platform, num_scenes)
    
    # Call LLM
    try:
        llm_response = _call_llm(system_prompt, user_prompt)
        classifications = _parse_llm_response(llm_response, num_scenes)
        
        # Validate and enforce allowlist
        _validate_classifications(classifications, num_scenes)
        
        logger.info("[classifier] Successfully classified %d scenes", len(classifications))
        return classifications
        
    except Exception as e:
        logger.error("[classifier] Classification failed: %s", e)
        raise RuntimeError(f"Scene classification failed: {e}") from e


def _build_system_prompt() -> str:
    """Build the system prompt for the LLM."""
    allowed_models = ["z-image-turbo", "z-image-photo"] + FAL_IMAGE_MODELS
    
    return f"""You are a scene classifier for video generation. Analyze each scene and determine:
1. Whether it's text-heavy (requires prominent text overlays like signs, posters, labels)
2. Which image generation model is best suited
3. Whether to skip image/video generation entirely (pure typographic scenes)
4. Text overlay configuration when applicable

Available image models:
- Fal models: {', '.join(FAL_IMAGE_MODELS)}
- Runpod models: z-image-turbo (excellent for people/portraits), z-image-photo

Rules:
- Use z-image-turbo for scenes with people, portraits, faces
- For scenes with ANY legible text (signs, labels, logos, UI elements, product names, captions, headlines): set is_text_heavy=true and skip_image_generation=true — use text overlays instead of image generation for these scenes
- Use Fal models for abstract, landscapes, objects, text-free backgrounds, fantasy, sci-fi
- Set skip_image_generation=true ONLY for pure typographic scenes (no visual content needed)
- When is_text_heavy=true, provide prominent_text_overlay with component + props
- Text overlay components: kinetic_title (animated), stagger_title (word-by-word), caption_bar (subtitle-style)

Output strict JSON array matching this schema:
[
  {{
    "scene_index": 0,
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "reasoning": "Scene shows a person - z-image-turbo excels at portraits"
  }}
]

CRITICAL: Output ONLY the JSON array. No markdown, no explanation, no code fences."""


def _build_user_prompt(brief: Brief, platform: str, num_scenes: int) -> str:
    """Build the user prompt with brief context."""
    brief_json = brief.model_dump_json(indent=2)
    
    return f"""Brief:
{brief_json}

Platform: {platform}

Classify all {num_scenes} scenes in the {platform} platform brief.
Return a JSON array with one SceneClassification object per scene."""


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call the LLM via OpenRouter API.
    
    Args:
        system_prompt: System prompt
        user_prompt: User prompt with brief context
    
    Returns:
        Raw LLM response text
    
    Raises:
        RuntimeError: If API call fails
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is required for scene classifier")
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": SCENE_CLASSIFIER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 4000,
    }
    
    logger.debug("[classifier] Calling OpenRouter with model=%s", SCENE_CLASSIFIER_MODEL)
    
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            logger.debug("[classifier] LLM response length: %d chars", len(content))
            return content
            
    except httpx.HTTPStatusError as e:
        logger.error("[classifier] OpenRouter API error: %s", e.response.text)
        raise RuntimeError(f"OpenRouter API error: {e.response.status_code}") from e
    except (KeyError, IndexError) as e:
        logger.error("[classifier] Unexpected OpenRouter response format: %s", e)
        raise RuntimeError("Unexpected OpenRouter response format") from e
    except Exception as e:
        logger.error("[classifier] LLM call failed: %s", e)
        raise RuntimeError(f"LLM call failed: {e}") from e


def _parse_llm_response(response: str, expected_count: int) -> List[SceneClassification]:
    """Parse LLM response into SceneClassification objects.
    
    Args:
        response: Raw LLM response text
        expected_count: Expected number of classifications
    
    Returns:
        List of SceneClassification objects
    
    Raises:
        RuntimeError: If parsing fails or count mismatch
    """
    # Strip thinking tags if present (some models emit <think>...</think>)
    cleaned = response
    if "<think>" in cleaned:
        cleaned = cleaned.split("</think>")[-1].strip()
    
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    
    cleaned = cleaned.strip()
    
    try:
        data = json.loads(cleaned)
        
        if not isinstance(data, list):
            raise RuntimeError(f"Expected JSON array, got {type(data).__name__}")
        
        classifications = [SceneClassification(**item) for item in data]
        
        if len(classifications) != expected_count:
            raise RuntimeError(
                f"Scene count mismatch: expected {expected_count}, got {len(classifications)}"
            )
        
        return classifications
        
    except json.JSONDecodeError as e:
        logger.error("[classifier] JSON parse error: %s\nResponse: %s", e, cleaned[:500])
        raise RuntimeError(f"Failed to parse LLM response as JSON: {e}") from e
    except ValidationError as e:
        logger.error("[classifier] Pydantic validation error: %s", e)
        raise RuntimeError(f"Invalid classification schema: {e}") from e


def _validate_classifications(classifications: List[SceneClassification], expected_count: int) -> None:
    """Validate classifications and enforce model allowlist.
    
    Args:
        classifications: List of classifications to validate
        expected_count: Expected number of classifications
    
    Raises:
        RuntimeError: If validation fails
    """
    allowed_models = {"z-image-turbo", "z-image-photo"} | set(FAL_IMAGE_MODELS)
    
    for cls in classifications:
        # Validate model allowlist
        if cls.image_model not in allowed_models:
            raise RuntimeError(
                f"Invalid image_model '{cls.image_model}' in scene {cls.scene_index}. "
                f"Allowed: {sorted(allowed_models)}"
            )
        
        # Validate provider matches model
        expected_provider = "runpod" if cls.image_model.startswith("z-image-") else "fal"
        if cls.image_provider != expected_provider:
            logger.warning(
                "[classifier] Correcting provider for scene %d: %s -> %s (model=%s)",
                cls.scene_index, cls.image_provider, expected_provider, cls.image_model
            )
            cls.image_provider = expected_provider
        
        # Validate skip logic
        if cls.skip_image_generation and not cls.prominent_text_overlay:
            raise RuntimeError(
                f"Scene {cls.scene_index}: skip_image_generation=true requires prominent_text_overlay"
            )


def _fallback_classifications(brief: Brief, platform: str) -> List[SceneClassification]:
    """Generate fallback classifications when classifier is disabled.

    Args:
        brief: Brief object
        platform: Platform identifier

    Returns:
        List of fallback classifications (all scenes use z-image-turbo)
    """
    platform_brief = None
    for pb in brief.platform_briefs:
        if pb.platform.lower() == platform.lower():
            platform_brief = pb
            break

    if not platform_brief:
        raise ValueError(f"Platform '{platform}' not found in brief.platform_briefs")

    classifications = []
    for idx in range(len(platform_brief.scenes)):
        classifications.append(
            SceneClassification(
                scene_index=idx,
                is_text_heavy=False,
                image_provider="runpod",
                image_model="z-image-turbo",
                skip_image_generation=False,
                prominent_text_overlay=None,
                reasoning="Fallback: classifier disabled"
            )
        )

    logger.info("[classifier] Generated %d fallback classifications", len(classifications))
    return classifications


def classify_scenes_from_script(
    script: str,
    scenes: List[Dict[str, Any]]
) -> List[SceneClassification]:
    """Classify scenes based on script and scene prompts from N8N.

    This function is used by the /orchestrate/start endpoint when SCENE_CLASSIFIER_ENABLED=true.
    It takes the voiceover script and scene prompts (generated by N8N) and determines
    which image generation model to use for each scene.

    Args:
        script: The voiceover/narration script
        scenes: List of scene dicts from N8N prompts webhook.
                Each dict should have at least 'image_prompt' and/or 'video_prompt' keys.

    Returns:
        List of SceneClassification objects, one per scene

    Raises:
        RuntimeError: If LLM call fails or returns invalid JSON
    """
    if not SCENE_CLASSIFIER_ENABLED:
        logger.warning("[classifier] Scene classifier is disabled, using fallback")
        return _fallback_classifications_from_script(scenes)

    num_scenes = len(scenes)
    logger.info(
        "[classifier] Classifying %d scenes from script, provider=%s, model=%s",
        num_scenes, SCENE_CLASSIFIER_PROVIDER, SCENE_CLASSIFIER_MODEL
    )

    # Early return for empty scenes
    if num_scenes == 0:
        return []

    # Build LLM prompt for script+scenes classification
    system_prompt = _build_system_prompt_script_based()
    user_prompt = _build_user_prompt_script_based(script, scenes)

    # Call LLM
    try:
        llm_response = _call_llm(system_prompt, user_prompt)
        classifications = _parse_llm_response(llm_response, num_scenes)

        # Validate and enforce allowlist
        _validate_classifications(classifications, num_scenes)

        logger.info("[classifier] Successfully classified %d scenes from script", len(classifications))
        return classifications

    except Exception as e:
        logger.error("[classifier] Script-based classification failed: %s", e)
        raise RuntimeError(f"Scene classification from script failed: {e}") from e


def _build_system_prompt_script_based() -> str:
    """Build the system prompt for script+scenes based classification."""
    return f"""You are a scene classifier for video generation. Analyze each scene description and determine which image generation model is best suited.

Available image models:
- Fal models: {', '.join(FAL_IMAGE_MODELS)}
- Runpod models: z-image-turbo (excellent for people/portraits), z-image-photo

Rules:
- Use z-image-turbo for scenes with people, portraits, faces, characters
- Use z-image-photo for realistic photography-style scenes
- For scenes with ANY legible text (signs, labels, logos, UI elements, product names, captions, headlines): set is_text_heavy=true and skip_image_generation=true — use text overlays instead of image generation for these scenes
- Use Fal models for abstract, landscapes, objects, text-free backgrounds, fantasy, sci-fi
- Set skip_image_generation=true ONLY for pure typographic scenes (no visual content needed)

Output strict JSON array matching this schema:
[
  {{
    "scene_index": 0,
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "reasoning": "Scene shows a person - z-image-turbo excels at portraits"
  }}
]

CRITICAL: Output ONLY the JSON array. No markdown, no explanation, no code fences."""


def _build_user_prompt_script_based(script: str, scenes: List[Dict[str, Any]]) -> str:
    """Build the user prompt with script and scenes context."""
    scenes_json = json.dumps(scenes, indent=2)

    return f"""Voiceover Script:
{script}

Scene Prompts:
{scenes_json}

Classify all {len(scenes)} scenes. Return a JSON array with one SceneClassification object per scene."""


def _fallback_classifications_from_script(scenes: List[Dict[str, Any]]) -> List[SceneClassification]:
    """Generate fallback classifications when classifier is disabled.

    Args:
        scenes: List of scene dicts

    Returns:
        List of fallback classifications (all scenes use FAL_IMAGE_DEFAULT)
    """
    classifications = []
    for idx in range(len(scenes)):
        classifications.append(
            SceneClassification(
                scene_index=idx,
                is_text_heavy=False,
                image_provider="fal",
                image_model=FAL_IMAGE_DEFAULT,
                skip_image_generation=False,
                prominent_text_overlay=None,
                reasoning="Fallback: classifier disabled, using Fal default"
            )
        )

    logger.info("[classifier] Generated %d fallback classifications from script", len(classifications))
    return classifications
