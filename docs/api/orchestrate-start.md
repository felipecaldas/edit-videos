# POST /orchestrate/start

Start the full end-to-end video generation workflow.

## Purpose

Use this endpoint when the backend should generate the complete pipeline from script to final video, including:
- Scene prompt generation (legacy flow) or brief-based scene extraction (V-CaaS flow)
- Image generation for each scene
- Video clip generation from images
- Voiceover generation
- Subtitle generation
- Final video assembly and stitching

## Method & Path

```
POST /orchestrate/start
```

## Request Body

### Legacy Flow (N8N-generated prompts)

```json
{
  "user_id": "user-42",
  "script": "In 1999, a programmer accidentally changed the world. He wrote a simple script that automated his daily tasks. Within weeks, thousands were using it. Today, that script powers half the internet.",
  "caption": "The story of automation",
  "prompts": [
    {
      "image_prompt": "A programmer at a desk in 1999, CRT monitor glowing",
      "video_prompt": "Slow zoom on keyboard, nostalgic lighting"
    },
    {
      "image_prompt": "Lines of code scrolling on a terminal screen",
      "video_prompt": "Gentle upward scroll, green terminal aesthetic"
    }
  ],
  "language": "en",
  "image_style": "default",
  "video_format": "9:16",
  "target_resolution": "720p",
  "run_id": "run-abc123",
  "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM"
}
```

### V-CaaS Brief-Aware Flow

```json
{
  "user_id": "user-42",
  "script": "Every founder has that moment. The moment everything changes. You're at your desk at night, lit by the glow of your laptop. An idea hits. You start building. Days blur together. Then someone uses it. Then ten people. Then a thousand. That's when you know: you've built something that matters.",
  "caption": "The founder's journey",
  "language": "en",
  "image_style": "cinematic",
  "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
  "platform": "LinkedIn",
  "brief": {
    "title": "The Founder's Moment",
    "hook": "Every founder has that moment",
    "narrative_structure": "problem-realization-growth-impact",
    "visual_direction": {
      "mood": "optimistic",
      "color_feel": "warm pastels with dramatic shadows",
      "shot_style": "cinematic handheld",
      "branding_elements": "Tabario wordmark lower-third"
    },
    "platform_briefs": [
      {
        "platform": "LinkedIn",
        "tone": "confident, conversational",
        "aspect_ratio": "1:1",
        "scenes": [
          {
            "scene_number": 1,
            "spoken_line": "Every founder has that moment.",
            "caption_text": "The moment everything changes.",
            "duration_seconds": 2.5,
            "visual_description": "A founder at a desk at night, lit by the glow of a laptop"
          },
          {
            "scene_number": 2,
            "spoken_line": "You're at your desk at night, lit by the glow of your laptop.",
            "caption_text": "Late nights. Big ideas.",
            "duration_seconds": 3.0,
            "visual_description": "Close-up of hands typing on a keyboard, screen reflection in glasses"
          },
          {
            "scene_number": 3,
            "spoken_line": "An idea hits. You start building.",
            "caption_text": "The spark.",
            "duration_seconds": 2.0,
            "visual_description": "Whiteboard filled with diagrams and notes, marker in motion"
          },
          {
            "scene_number": 4,
            "spoken_line": "Days blur together. Then someone uses it.",
            "caption_text": "First user.",
            "duration_seconds": 2.5,
            "visual_description": "Notification popup showing 'New user signed up'"
          },
          {
            "scene_number": 5,
            "spoken_line": "Then ten people. Then a thousand.",
            "caption_text": "Growth.",
            "duration_seconds": 2.5,
            "visual_description": "Analytics dashboard showing exponential growth curve"
          },
          {
            "scene_number": 6,
            "spoken_line": "That's when you know: you've built something that matters.",
            "caption_text": "Impact.",
            "duration_seconds": 3.0,
            "visual_description": "Founder smiling at laptop, warm sunrise light through window"
          }
        ],
        "call_to_action": "What was your moment? Share below."
      }
    ]
  }
}
```

## Request Fields

### Required Fields (Both Flows)

| Field | Type | Description | Example |
|---|---|---|---|
| `user_id` | string | User identifier for correlation and storage ownership | `"user-42"` |
| `script` | string | Narration script for voiceover generation | `"In 1999, a programmer..."` |
| `caption` | string | Caption or descriptive text stored with the video | `"The story of automation"` |

### Optional Fields (Legacy Flow)

| Field | Type | Default | Description |
|---|---|---|---|
| `prompts` | array | `null` | Scene prompt overrides. When omitted, prompts are generated via N8N webhook |
| `language` | string | `"en"` | Language code for voiceover and subtitles |
| `image_style` | string | `"default"` | Named image style mapped to internal ComfyUI workflow |
| `z_image_style` | string | `null` | Experimental secondary image style selector |
| `image_width` | integer | `360` | Image width in pixels |
| `image_height` | integer | `640` | Image height in pixels |
| `video_format` | string | `"9:16"` | Aspect ratio: `"9:16"`, `"16:9"`, or `"1:1"` |
| `target_resolution` | string | `"720p"` | Target resolution: `"480p"`, `"720p"`, or `"1080p"` |
| `run_id` | string | auto-generated | Business identifier for the run |
| `elevenlabs_voice_id` | string | env default | Voice ID for voiceover generation |
| `workflow_id` | string | auto-generated | Explicit Temporal workflow ID |
| `enable_image_gen` | boolean | `true` | Whether to run image generation |

### V-CaaS Brief-Aware Fields

| Field | Type | Required When | Description |
|---|---|---|---|
| `brief` | object | V-CaaS flow | Top-level brief object with cross-platform narrative and per-platform execution briefs |
| `platform` | string | V-CaaS flow | Platform identifier selecting one `PlatformBriefModel` from `brief.platform_briefs` (e.g., `"LinkedIn"`, `"Instagram"`) |
| `video_idea_id` | string | V-CaaS flow without `run_id` | Supabase `video_ideas.id`, used to derive `run_id` and echoed in webhooks |
| `client_id` | string | When `handoff_to_compositor` is `true` (or auto-computed `true`) | Supabase `clients.id`. Required for the compositor handoff path. |
| `handoff_to_compositor` | boolean | null | No | Controls whether finished clips are forwarded to `tabario-video-compositor`. When `null` (default), auto-computes to `true` if `brief + platform + client_id` are all present. Explicitly set to `false` to disable handoff even in brief-aware runs. |

### Fal.ai Integration Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `enable_scene_classifier` | boolean | `SCENE_CLASSIFIER_ENABLED` env var | Enable LLM-based scene classification to auto-select image provider (Fal vs Runpod) and detect text-heavy scenes for overlay rendering. When disabled, falls back to legacy behavior (all Runpod z-image-turbo). |
| `video_provider_override` | string | `VIDEO_PROVIDER` env var | Override the video generation provider. Options: `"fal"` (default, uses Fal Seedance 2.0), `"runpod"` (uses Runpod Wan 2.2). Useful for testing or fallback scenarios. |
| `fal_ai_model_id` | string | `FAL_AI_MODEL_ID` env var | Fal.ai model ID for video generation. |
| `fal_ai_api_key` | string | `FAL_AI_API_KEY` env var | Fal.ai API key for authentication. |

### Response Fields (Success)

| Field | Type | Description |
|---|---|---|
| `message` | string | Status message |
| `workflow_id` | string | Temporal workflow identifier |
| `run_id` | string | Business identifier for the run |
| `scene_classifications` | array | (When `enable_scene_classifier` is `true`) Array of scene classifications from the LLM classifier. Each entry includes: `scene_index`, `is_text_heavy`, `image_provider`, `image_model`, `skip_image_generation`, `prominent_text_overlay`, `reasoning`. |
| `video_provider_used` | string | Provider used for video generation: `"fal"` or `"runpod"`. Useful for debugging and webhook correlation. |
| `scene_overlays` | array | (When `enable_scene_classifier` is `true`) Array of text overlays to render in the compositor. Each entry includes: `scene_index`, `component` (e.g., `"kinetic_title"`, `"stagger_title"`, `"caption_bar"`), `text`, and `props` (color, size, position, etc.). |

## Derivation Rules (V-CaaS Flow)

When `brief` and `platform` are both present:

1. **`run_id` derivation**: If `run_id` is omitted, it is derived as `{video_idea_id}-{platform.lower()}`. Example: `"fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"`

2. **`video_format` derivation**: If `video_format` is omitted, it is derived from `platform_brief.aspect_ratio` using the mapping:
   - `"1:1"` → `"1:1"`
   - `"9:16"` → `"9:16"`
   - `"16:9"` → `"16:9"`
   - Unknown values default to `"9:16"`

3. **`image_style` derivation**: If `image_style` is omitted, defaults to `"default"`

4. **Scene prompts**: Scene prompts are built from `brief.platform_briefs[].scenes[]` instead of calling the N8N prompts webhook

## Response

### Success (202 Accepted)

```json
{
  "message": "Workflow started successfully.",
  "workflow_id": "tabario-user-user-42-run-abc123",
  "run_id": "run-abc123"
}
```

### Error Responses

| Status | Condition | Response Body |
|---|---|---|
| 400 | Unknown `image_style` | `{"detail": "Unknown image_style 'xyz'. Supported styles: ['default', 'cinematic', ...]"}` |
| 400 | V-CaaS flow missing `video_idea_id` when `run_id` omitted | `{"detail": "video_idea_id is required when run_id is not supplied in brief-aware flow."}` |
| 400 | Platform not found in `brief.platform_briefs` | `{"detail": "Platform 'TikTok' not found in brief.platform_briefs. Available platforms: ['LinkedIn', 'Instagram']"}` |
| 400 | Handoff enabled but `client_id` missing | `{"detail": "client_id is required when handoff_to_compositor is enabled."}` |
| 409 | Workflow already running | `{"detail": "A video generation job is already in progress for this user."}` |
| 500 | Temporal workflow start failure | `{"detail": "Failed to start workflow: <error>"}` |

## Important Invariants

- `image_style` must map to a known workflow name in `IMAGE_STYLE_TO_WORKFLOW_MAPPING` before the workflow is enqueued
- `workflow_id` is always constructed as `tabario-user-{user_id}-{run_id}` by the backend
- The Temporal search attribute `TabarioRunId` is set to `[run_id]` for correlation
- This flow sends the completion webhook with the **local** `final_video_path` only (no Supabase upload)
- `user_access_token` is **not required** for this endpoint (legacy flow does not upload to Supabase)
- `client_id` is **required** whenever `handoff_to_compositor` resolves to `true` (explicit or auto-computed)
- `handoff_to_compositor` auto-computes to `true` when `brief + platform + client_id` are all present; pass `false` explicitly to opt out

## Completion Webhook Ownership

Who emits the final completion webhook depends on the run path:

| Path | Condition | Webhook emitter | Webhook `status` |
|---|---|---|---|
| **Legacy success** | `handoff_to_compositor` is `false` / unset, no brief | `edit-videos` (`send_completion_webhook`) | `"completed"` |
| **Brief-aware success** | `handoff_to_compositor` resolves to `true` | `tabario-video-compositor` (after compositing) | `"completed"` |
| **Brief-aware failure** (handoff fails after retries) | `handoff_to_compositor` is `true` but activity raises | `edit-videos` (`send_completion_webhook`) | `"failed"` |
| **Any workflow failure** (pre-handoff) | Exception before or during clip generation | `edit-videos` (`send_completion_webhook`) | `"failed"` |

> **Key invariant:** `edit-videos` never emits a `"completed"` webhook for a brief-aware run. The compositor is the sole success-path webhook emitter for those runs. `edit-videos` always emits `"failed"` webhooks so callers are never left hanging.

## Workflow Behavior

1. Validates `image_style` against known workflows
2. Derives `run_id`, `video_format`, `image_style` if in V-CaaS flow
3. Constructs `workflow_id` as `tabario-user-{user_id}-{run_id}`
4. Starts `VideoGenerationWorkflow` on Temporal task queue `video-generation-task-queue`
5. Sets `id_reuse_policy` to `ALLOW_DUPLICATE_FAILED_ONLY`
6. Returns `202` immediately (workflow runs asynchronously)

### Tail branching (after clip generation)

**Handoff path** (`handoff_to_compositor` = `true`):
- Calls `handoff_to_compositor` activity with a `HandoffPayload` (clips + voiceover + brief metadata)
- Returns the `compose_job_id` from the compositor
- Does **not** call `stitch_videos`, `burn_subtitles_into_video`, or `send_completion_webhook`
- If handoff fails: emits `send_completion_webhook` with `status="failed"` then raises `ApplicationError`

**Legacy path** (`handoff_to_compositor` = `false` or unset):
- Calls `stitch_videos` → `burn_subtitles_into_video` → `send_completion_webhook(status="completed")`
- No Supabase upload (this endpoint does not carry `user_access_token`)

## Related Documentation

- [Video Generation Workflow](workflows/video-generation-workflow.md)
- [Webhook Payloads](data-contracts/webhook-payloads.md)
- [Request Models](data-contracts/request-models.md)
