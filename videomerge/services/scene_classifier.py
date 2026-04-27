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
import re
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

# Deterministic pre-filter: scene descriptions containing these keywords always require
# image_prompt_override so the LLM cannot silently skip it.
_UI_KEYWORD_RE = re.compile(
    r"\b(screen|dashboard|UI|software|app|browser|interface|font|logo|statistics|"
    r"percentage|headline|slogan|CTA|monitor|laptop|computer\s+screen|desktop\s+screen)\b",
    re.IGNORECASE,
)

# Forbidden terms that must not appear in the generated image_prompt_override itself.
# If any match, the override is contaminated and must be replaced with the deterministic fallback.
_OVERRIDE_FORBIDDEN_RE = re.compile(
    r"\b(screen|dashboard|UI|software|app|browser|interface|monitor|laptop|"
    r"computer\s+screen|desktop\s+screen|display\s+screen|on\s+a\s+screen|"
    r"on\s+a\s+monitor|on\s+a\s+laptop)\b",
    re.IGNORECASE,
)

# JSON Schema for structured OpenRouter output (scene classification array).
_SCENE_CLASSIFICATION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "scene_classifications",
        "strict": False,
        "schema": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "scene_index", "scene_type", "is_text_heavy", "image_provider",
                    "image_model", "skip_image_generation", "prominent_text_overlay",
                    "image_prompt_override", "reasoning",
                ],
                "properties": {
                    "scene_index": {"type": "integer"},
                    "scene_type": {"type": "string", "enum": ["talking_head", "concept_visual", "brand_card"]},
                    "is_text_heavy": {"type": "boolean"},
                    "image_provider": {"type": "string", "enum": ["fal", "runpod"]},
                    "image_model": {"type": "string"},
                    "skip_image_generation": {"type": "boolean"},
                    "prominent_text_overlay": {},
                    "image_prompt_override": {},
                    "reasoning": {"type": "string"},
                },
            },
        },
    },
}


class TextOverlay(BaseModel):
    """Text overlay configuration for Remotion compositor."""
    
    component: Literal["kinetic_title", "stagger_title", "caption_bar"]
    text: Optional[str] = None
    props: Dict[str, Any] = Field(default_factory=dict)


class SceneClassification(BaseModel):
    """Classification result for a single scene."""

    scene_index: int
    scene_type: Literal["talking_head", "concept_visual", "brand_card"] = "concept_visual"
    is_text_heavy: bool
    image_provider: Literal["fal", "runpod"]
    image_model: str
    skip_image_generation: bool = False
    prominent_text_overlay: Optional[TextOverlay] = None
    reasoning: str = ""
    image_prompt_override: Optional[str] = None


def _ui_pre_filter(descriptions: List[str]) -> set:
    """Return indices of descriptions that contain UI/screen keywords."""
    return {i for i, d in enumerate(descriptions) if _UI_KEYWORD_RE.search(d or "")}


_UI_FALLBACK_OVERRIDE = (
    "Abstract concept visualization conveying digital productivity and workflow, "
    "cinematic overhead perspective, warm natural textures, no screens, no software "
    "interfaces, no UI elements, no text overlays"
)


def _enforce_ui_overrides(
    classifications: List[SceneClassification],
    ui_matched_indices: set,
) -> None:
    """Force is_text_heavy and ensure image_prompt_override for UI-keyword scenes.

    Applies the deterministic fallback when the LLM omitted the override entirely,
    and also when the LLM-generated override itself leaks forbidden screen/monitor
    keywords (contaminated override).
    """
    for cls in classifications:
        if cls.scene_index not in ui_matched_indices:
            continue
        cls.is_text_heavy = True
        if not cls.image_prompt_override:
            logger.warning(
                "[classifier] FALLBACK OVERRIDE applied — scene %d: UI keyword matched but "
                "LLM emitted no image_prompt_override. Forcing deterministic fallback.",
                cls.scene_index,
            )
            cls.image_prompt_override = _UI_FALLBACK_OVERRIDE
        elif _OVERRIDE_FORBIDDEN_RE.search(cls.image_prompt_override):
            logger.warning(
                "[classifier] CONTAMINATED OVERRIDE replaced — scene %d: image_prompt_override "
                "contains forbidden screen/monitor keyword. Original: %r. Forcing deterministic fallback.",
                cls.scene_index,
                cls.image_prompt_override,
            )
            cls.image_prompt_override = _UI_FALLBACK_OVERRIDE


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

    # Deterministic pre-filter: find scenes requiring image_prompt_override
    scene_descriptions = [s.visual_description or "" for s in platform_brief.scenes]
    ui_matched = _ui_pre_filter(scene_descriptions)
    if ui_matched:
        logger.info("[classifier] UI pre-filter matched scene indices: %s", sorted(ui_matched))

    # Build LLM prompt
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(brief, platform, num_scenes)

    # Call LLM
    try:
        llm_response = _call_llm(system_prompt, user_prompt)
        classifications = _parse_llm_response(llm_response, num_scenes)

        # Validate and enforce allowlist
        _validate_classifications(classifications, num_scenes)

        # Post-validate: enforce overrides for UI-keyword scenes
        _enforce_ui_overrides(classifications, ui_matched)

        logger.info("[classifier] Successfully classified %d scenes", len(classifications))
        return classifications

    except Exception as e:
        logger.error("[classifier] Classification failed: %s", e)
        raise RuntimeError(f"Scene classification failed: {e}") from e


def _build_system_prompt() -> str:
    """Build the system prompt for the LLM."""
    allowed_models = ["z-image-turbo", "z-image-photo"] + FAL_IMAGE_MODELS
    
    return f"""You are a scene classifier for video generation. Analyze each scene and determine:
1. The scene_type (talking_head | concept_visual | brand_card)
2. Whether it's text-heavy (requires prominent text overlays)
3. Which image generation model is best suited
4. Whether to skip image/video generation entirely
5. Text overlay configuration when applicable

Available image models:
- Fal models: {', '.join(FAL_IMAGE_MODELS)}
- Runpod models: z-image-turbo (excellent for people/portraits), z-image-photo

Scene type detection (set scene_type accordingly):
- "talking_head": scene describes a person directly addressing the camera, a presenter,
  a testimonial, a spokesperson, a talking head, someone speaking to the viewer.
  → always use image_provider "fal", skip_image_generation=false (portrait image still needed),
    never use Wan2.2 (echomimic-v3 handles video generation instead).

- "brand_card": scene is purely a logo, CTA text, end screen, URL display, or brand sign-off
  with no meaningful visual background.
  → set skip_image_generation=true, set is_text_heavy=true.

- "concept_visual": all other scenes including abstract visuals, environments, product metaphors,
  and — importantly — any scene that previously described a screen recording, UI, or software
  dashboard. For those, reinterpret the scene as an abstract metaphorical visual that conveys
  the same concept without showing actual software UI. Generate an evocative concept image.
  → MANDATORY: set image_prompt_override to a fully rewritten abstract visual prompt that
    contains NO references to screens, software, UI, dashboards, apps, browsers, or any
    digital interface. Describe a real-world metaphor, environment, or concept instead.

image_prompt_override rules (CRITICAL):
- Set image_prompt_override whenever the original scene description mentions: screen recording,
  dashboard, UI, software, app, browser, interface, workflow tool, SaaS, window, tab, cursor,
  Slack, Notion, or any digital product UI.
- The override MUST be a complete, standalone image generation prompt (no references to "the
  original scene" or "as described"). Write it as a direct prompt to an image model.
- For talking_head scenes: set image_prompt_override to a natural portrait prompt, e.g.
  "Professional portrait photo of a confident businesswoman, clean studio background, soft
  natural lighting, looking directly into camera, shallow depth of field."
- Leave image_prompt_override null for scenes that are already abstract/environmental with
  no UI contamination.

Model selection rules:
- Use z-image-turbo for talking_head scenes (portrait quality needed for lipsync)
- For concept_visual scenes with ANY legible text as a foreground element (signs, labels, logos,
  UI elements, product names, captions, headlines, statistics, slogans, CTA text): set
  is_text_heavy=true and skip_image_generation=true — Remotion renders the text
- Use Fal models for abstract, landscapes, objects, text-free backgrounds, fantasy, sci-fi
- When is_text_heavy=true and skip_image_generation=true for a concept scene, provide
  prominent_text_overlay with component + props
- Text overlay components: kinetic_title (animated), stagger_title (word-by-word), caption_bar (subtitle-style)

Text-heavy rule (aggressive):
- If the scene description mentions brand names to display, statistics, data figures, headlines,
  slogans, or call-to-action text as foreground elements → is_text_heavy=true,
  skip_image_generation=true. Remotion will render that text.

Output strict JSON array matching this schema:
[
  {{
    "scene_index": 0,
    "scene_type": "concept_visual",
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "image_prompt_override": null,
    "reasoning": "Scene shows a person - z-image-turbo excels at portraits"
  }}
]

Few-shot examples of the exact failure modes to avoid:

Scene: "Screencast of a project management dashboard with colourful Kanban columns"
✗ WRONG — image_prompt_override: null  (silent skip — never do this)
✓ CORRECT — image_prompt_override: "Birds-eye view of a wooden desk covered in colour-coded sticky notes
  arranged in columns, warm morning light, analogue productivity, no screens"

Scene: "Split-screen showing two people on a video call with workflow tool panels visible"
✗ WRONG — scene_type: "talking_head"  (misclassified because two people are present)
✓ CORRECT — scene_type: "concept_visual", image_prompt_override: "Two professionals collaborating
  side-by-side at a shared table in a bright modern office, pointing at documents, engaged discussion"

Scene: "UI mockup of the app home screen displaying different fonts and colors"
✗ WRONG — image_prompt_override: null, is_text_heavy: false
✓ CORRECT — is_text_heavy: true, image_prompt_override: "Abstract arrangement of colourful geometric
  shapes on a clean white surface, typography-inspired design, studio lighting, no screens or UI"

Scene: "Close-up of a browser tab with the app's analytics page, showing statistics and a headline"
✗ WRONG — image_prompt_override: null
✓ CORRECT — is_text_heavy: true, image_prompt_override: "Macro shot of a sleek desk with a printed
  chart and a pen, shallow depth of field, professional office environment, no screens"

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
        "response_format": _SCENE_CLASSIFICATION_RESPONSE_FORMAT,
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

        # LLM legitimately returns null for some fields. Provide harmless
        # defaults so Pydantic validation doesn't reject them.
        for item in data:
            if not item.get("image_provider"):
                item["image_provider"] = "fal"
            if not item.get("image_model"):
                item["image_model"] = FAL_IMAGE_DEFAULT
            if not item.get("scene_type"):
                item["scene_type"] = "concept_visual"
            # Some LLMs double-encode nested objects as JSON strings. Unwrap them.
            # Others return a plain string (e.g. "Tabario.com") — null those out.
            for field in ("prominent_text_overlay", "image_prompt_override"):
                val = item.get(field)
                if isinstance(val, str):
                    if val.strip().startswith("{"):
                        try:
                            item[field] = json.loads(val)
                        except json.JSONDecodeError:
                            logger.warning(
                                "[classifier] Field %r in scene %s is a non-parseable JSON string — setting to None",
                                field, item.get("scene_index"),
                            )
                            item[field] = None
                    else:
                        logger.warning(
                            "[classifier] Field %r in scene %s is a plain string %r — setting to None",
                            field, item.get("scene_index"), val,
                        )
                        item[field] = None

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
        
        # brand_card scenes skip image gen entirely — no text overlay required
        if cls.skip_image_generation and cls.scene_type != "brand_card" and not cls.prominent_text_overlay:
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

    # Deterministic pre-filter: find scenes requiring image_prompt_override
    scene_descriptions = [
        s.get("image_prompt") or s.get("video_prompt") or "" for s in scenes
    ]
    ui_matched = _ui_pre_filter(scene_descriptions)
    if ui_matched:
        logger.info("[classifier] UI pre-filter matched scene indices: %s", sorted(ui_matched))

    # Build LLM prompt for script+scenes classification
    system_prompt = _build_system_prompt_script_based()
    user_prompt = _build_user_prompt_script_based(script, scenes)

    # Call LLM
    try:
        llm_response = _call_llm(system_prompt, user_prompt)
        classifications = _parse_llm_response(llm_response, num_scenes)

        # Validate and enforce allowlist
        _validate_classifications(classifications, num_scenes)

        # Post-validate: enforce overrides for UI-keyword scenes
        _enforce_ui_overrides(classifications, ui_matched)

        logger.info("[classifier] Successfully classified %d scenes from script", len(classifications))
        return classifications

    except Exception as e:
        logger.error("[classifier] Script-based classification failed: %s", e)
        raise RuntimeError(f"Scene classification from script failed: {e}") from e


def _build_system_prompt_script_based() -> str:
    """Build the system prompt for script+scenes based classification."""
    return f"""You are a scene classifier for video generation. Analyze each scene description and determine:
1. The scene_type (talking_head | concept_visual | brand_card)
2. Which image generation model is best suited
3. Whether to skip image/video generation entirely

Available image models:
- Fal models: {', '.join(FAL_IMAGE_MODELS)}
- Runpod models: z-image-turbo (excellent for people/portraits), z-image-photo

Scene type detection:
- "talking_head": person directly addressing camera, presenter, spokesperson, testimonial
  → image_provider "fal", skip_image_generation=false (portrait still needed for echomimic-v3)
- "brand_card": logo/CTA/end-screen with no meaningful visual background
  → skip_image_generation=true, is_text_heavy=true
- "concept_visual": everything else, including what used to be screen recordings or UI demos
  (reinterpret as abstract metaphorical visual, not literal software UI)
  → MANDATORY: set image_prompt_override to a fully rewritten abstract visual prompt whenever
    the original description mentions screens, dashboards, UI, software, apps, or any digital
    interface. No references to software UI allowed in the override — describe a real-world
    metaphor or environment instead.

image_prompt_override rules (CRITICAL):
- Set image_prompt_override whenever the scene mentions: screen recording, dashboard, UI,
  software, app, browser, interface, workflow tool, SaaS, window, tab, Slack, Notion, cursor,
  or any digital product interface.
- The override must be a complete standalone image generation prompt with NO UI references.
- For talking_head scenes: set image_prompt_override to a natural portrait prompt.
- Leave null for purely abstract/environmental scenes with no UI contamination.

Model rules:
- Use z-image-turbo for talking_head scenes
- Use z-image-photo for realistic photography-style concept scenes
- Use Fal models for abstract, landscapes, objects, text-free backgrounds, fantasy, sci-fi
- Text-heavy rule: if scene has brand names, statistics, headlines, slogans, CTA text as
  foreground elements → is_text_heavy=true, skip_image_generation=true

Output strict JSON array matching this schema:
[
  {{
    "scene_index": 0,
    "scene_type": "concept_visual",
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "image_prompt_override": null,
    "reasoning": "Scene shows a person - z-image-turbo excels at portraits"
  }}
]

Few-shot examples of the exact failure modes to avoid:

Scene: "Screencast of a project management dashboard with colourful Kanban columns"
✗ WRONG — image_prompt_override: null  (silent skip — never do this)
✓ CORRECT — image_prompt_override: "Birds-eye view of a wooden desk covered in colour-coded sticky notes
  arranged in columns, warm morning light, analogue productivity, no screens"

Scene: "Split-screen showing two people on a video call with workflow tool panels visible"
✗ WRONG — scene_type: "talking_head"  (misclassified because two people are present)
✓ CORRECT — scene_type: "concept_visual", image_prompt_override: "Two professionals collaborating
  side-by-side at a shared table in a bright modern office, pointing at documents, engaged discussion"

Scene: "UI mockup of the app home screen displaying different fonts and colors"
✗ WRONG — image_prompt_override: null, is_text_heavy: false
✓ CORRECT — is_text_heavy: true, image_prompt_override: "Abstract arrangement of colourful geometric
  shapes on a clean white surface, typography-inspired design, studio lighting, no screens or UI"

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
