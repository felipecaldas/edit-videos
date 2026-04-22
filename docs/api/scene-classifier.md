# Scene Classifier API Contract

## Overview

The scene classifier is an internal LLM-based service that analyzes a brief and classifies each scene for:
- **Text-heavy detection**: Whether the scene requires prominent text overlays
- **Image model selection**: Which image generation model (Fal vs Runpod) is best suited
- **Skip image generation**: Whether to skip image/video generation entirely (pure typographic scenes)
- **Text overlay configuration**: Component and props for Remotion text overlays

## Function Signature

```python
def classify_scenes(brief: Brief, platform: str) -> List[SceneClassification]:
    """
    Classify all scenes in a brief for provider routing and text-heavy detection.
    
    Args:
        brief: The top-level Brief object containing platform_briefs and visual_direction
        platform: Platform identifier (e.g., 'LinkedIn', 'Instagram')
    
    Returns:
        List of SceneClassification objects, one per scene in the platform brief
    
    Raises:
        ValueError: If platform not found in brief.platform_briefs
        RuntimeError: If LLM call fails or returns invalid JSON
    """
```

## Input Schema

The classifier receives:
- **Brief**: Full brief object with `visual_direction`, `platform_briefs[]`
- **Platform**: String identifying which platform brief to analyze
- **Scene context**: For each scene in the platform brief:
  - `scene_number` (int)
  - `spoken_line` (str)
  - `caption_text` (str)
  - `duration_seconds` (float)
  - `visual_description` (str)

## Output Schema

```python
class TextOverlay(BaseModel):
    component: Literal["kinetic_title", "stagger_title", "caption_bar"]
    text: str
    props: Dict[str, Any]  # {color?: str, size?: int, position?: str, ...}

class SceneClassification(BaseModel):
    scene_index: int                                    # 0-indexed scene position
    is_text_heavy: bool                                 # True if scene requires prominent text
    image_provider: Literal["fal", "runpod"]            # Derived from image_model
    image_model: str                                    # e.g., "fal-ai/flux/dev", "z-image-turbo"
    skip_image_generation: bool                         # True for pure typographic scenes
    prominent_text_overlay: Optional[TextOverlay]       # Text overlay config when is_text_heavy=True
    reasoning: str                                      # LLM's explanation for the classification
```

## LLM Prompt Contract

The classifier uses a single LLM call per brief with the following structure:

### System Prompt

```
You are a scene classifier for video generation. Analyze each scene and determine:
1. Whether it's text-heavy (requires prominent text overlays like signs, posters, labels)
2. Which image generation model is best suited
3. Whether to skip image/video generation entirely (pure typographic scenes)
4. Text overlay configuration when applicable

Available image models:
- Fal models: {FAL_IMAGE_MODELS from env}
- Runpod models: z-image-turbo (excellent for people/portraits), z-image-photo

Rules:
- Use z-image-turbo for scenes with people, portraits, faces
- Use Fal models for abstract, landscapes, objects, text-heavy backgrounds
- Set skip_image_generation=true ONLY for pure typographic scenes (no visual content needed)
- When is_text_heavy=true, provide prominent_text_overlay with component + props
- Text overlay components: kinetic_title (animated), stagger_title (word-by-word), caption_bar (subtitle-style)

Output strict JSON array matching SceneClassification schema.
```

### User Prompt

```
Brief:
{JSON.stringify(brief)}

Platform: {platform}

Classify all {N} scenes in the {platform} platform brief.
Return a JSON array with one SceneClassification object per scene.
```

### Expected LLM Response

```json
[
  {
    "scene_index": 0,
    "is_text_heavy": false,
    "image_provider": "runpod",
    "image_model": "z-image-turbo",
    "skip_image_generation": false,
    "prominent_text_overlay": null,
    "reasoning": "Scene shows a founder at desk - person-focused, z-image-turbo excels at portraits"
  },
  {
    "scene_index": 1,
    "is_text_heavy": true,
    "image_provider": "fal",
    "image_model": "fal-ai/flux/dev",
    "skip_image_generation": false,
    "prominent_text_overlay": {
      "component": "kinetic_title",
      "text": "PROBLEM",
      "props": {
        "color": "#FF6B6B",
        "size": 96
      }
    },
    "reasoning": "Scene requires large 'PROBLEM' text overlay - Flux handles text-heavy backgrounds better"
  },
  {
    "scene_index": 2,
    "is_text_heavy": true,
    "image_provider": "fal",
    "image_model": "fal-ai/flux/dev",
    "skip_image_generation": true,
    "prominent_text_overlay": {
      "component": "stagger_title",
      "text": "The moment everything changes.",
      "props": {
        "color": "#FFFFFF"
      }
    },
    "reasoning": "Pure typographic scene - no visual content needed, Remotion will render text on brand background"
  }
]
```

## Validation Rules

Post-LLM parsing, the classifier enforces:

1. **Model allowlist**: `image_model` must be one of:
   - `z-image-turbo`
   - `z-image-photo`
   - Any model in `FAL_IMAGE_MODELS` env var (comma-separated)

2. **Provider derivation**: `image_provider` is automatically set based on `image_model`:
   - `z-image-*` → `runpod`
   - `fal-ai/*` → `fal`

3. **Scene count match**: Number of classifications must equal number of scenes in platform brief

4. **Skip logic**: When `skip_image_generation=true`, `prominent_text_overlay` must be present

## Error Handling

| Error | Cause | Behavior |
|---|---|---|
| `ValueError` | Platform not found in brief | Raise immediately |
| `RuntimeError` | LLM timeout / API error | Raise after 3 retries |
| `ValidationError` | Invalid model in allowlist | Raise with list of valid models |
| `ValidationError` | Scene count mismatch | Raise with expected vs actual count |

## Fallback Behavior

When `SCENE_CLASSIFIER_ENABLED=false`:
- All scenes → `image_provider=runpod`, `image_model=z-image-turbo`
- `is_text_heavy=false` for all scenes
- `skip_image_generation=false` for all scenes
- `prominent_text_overlay=null` for all scenes

## Example Usage

```python
from videomerge.services.scene_classifier import classify_scenes
from videomerge.models import Brief

brief = Brief(...)  # From request payload
platform = "LinkedIn"

classifications = classify_scenes(brief, platform)

for cls in classifications:
    print(f"Scene {cls.scene_index}: {cls.image_model} on {cls.image_provider}")
    if cls.is_text_heavy:
        print(f"  Text overlay: {cls.prominent_text_overlay.component}")
    if cls.skip_image_generation:
        print(f"  Skipping image/video generation (typographic)")
```

## Performance

- **Latency**: ~2-5 seconds per brief (single LLM call for all scenes)
- **Cost**: ~$0.001-0.003 per brief (Gemini 2.5 Flash via OpenRouter)
- **Concurrency**: Safe to call in parallel for different briefs
