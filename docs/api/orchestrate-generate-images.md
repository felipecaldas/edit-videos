# POST /orchestrate/generate-images

Generate storyboard images only and upload them to Supabase.

## Purpose

Use this endpoint when the backend should:
- Generate scene prompts (legacy flow) or extract scenes from brief (V-CaaS flow)
- Generate ordered storyboard images
- Upload images to Supabase storage
- **Not** generate the final video yet

This is the first step in a two-phase workflow where images are reviewed before video generation.

## Method & Path

```
POST /orchestrate/generate-images
```

## Request Body

### Legacy Flow (N8N-generated prompts)

```json
{
  "user_id": "user-42",
  "script": "A short narrated story about a futuristic city where AI and humans collaborate to solve climate change.",
  "language": "en",
  "image_style": "default",
  "image_width": 360,
  "image_height": 640,
  "run_id": "abc123",
  "user_access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### V-CaaS Brief-Aware Flow

```json
{
  "user_id": "user-42",
  "script": "Every founder has that moment. The moment everything changes.",
  "language": "en",
  "image_style": "cinematic",
  "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
  "platform": "LinkedIn",
  "user_access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "brief": {
    "title": "The Founder's Moment",
    "visual_direction": {
      "mood": "optimistic",
      "color_feel": "warm pastels with dramatic shadows"
    },
    "platform_briefs": [
      {
        "platform": "LinkedIn",
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
          }
        ]
      }
    ]
  }
}
```

## Request Fields

### Required Fields (Both Flows)

| Field | Type | Description | Example |
|---|---|---|---|
| `user_id` | string | User identifier for ownership and Supabase storage paths | `"user-42"` |
| `script` | string | Script used to generate storyboard scene prompts and images | `"A short narrated story..."` |
| `user_access_token` | string | Supabase user JWT access token for authenticated storage uploads (respects RLS policies) | `"eyJhbGciOi..."` |

### Optional Fields (Legacy Flow)

| Field | Type | Default | Description |
|---|---|---|---|
| `language` | string | `"en"` | Language code used when generating scene prompts |
| `image_style` | string | `"default"` | Named image style mapped to internal ComfyUI workflow |
| `z_image_style` | string | `null` | Experimental secondary image style selector |
| `image_width` | integer | `360` | Image width in pixels |
| `image_height` | integer | `640` | Image height in pixels |
| `run_id` | string | auto-derived | Run identifier. If omitted, derived deterministically from `script` and `language` (legacy) or from `video_idea_id` + `platform` (V-CaaS) |
| `workflow_id` | string | auto-generated | Explicit Temporal workflow ID |

### V-CaaS Brief-Aware Fields

| Field | Type | Required When | Description |
|---|---|---|---|
| `brief` | object | V-CaaS flow | Top-level brief object with per-platform execution briefs |
| `platform` | string | V-CaaS flow | Platform identifier selecting one `PlatformBriefModel` from `brief.platform_briefs` |
| `video_idea_id` | string | V-CaaS flow without `run_id` | Supabase `video_ideas.id`, used to derive `run_id` and echoed in webhooks |

## Derivation Rules

### Legacy Flow

If `run_id` is omitted and `brief` is **not** present:
- `run_id` is derived as the first 6 characters of `SHA256({language}:{script})`
- Example: `"abc123"` for a specific script/language combination

### V-CaaS Flow

When `brief` and `platform` are both present:

1. **`run_id` derivation**: If `run_id` is omitted, it is derived as `{video_idea_id}-{platform.lower()}`
   - Example: `"fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"`

2. **Scene prompts**: Image prompts are built from `brief.platform_briefs[].scenes[].visual_description` instead of calling the N8N prompts webhook

## Response

### Success (202 Accepted)

```json
{
  "message": "Image generation workflow started successfully.",
  "workflow_id": "tabario-image-user-user-42-abc123",
  "run_id": "abc123",
  "status": "received"
}
```

### Error Responses

| Status | Condition | Response Body |
|---|---|---|
| 400 | Missing `user_access_token` | `{"detail": "user_access_token is required for authenticated storage uploads."}` |
| 400 | Unknown `image_style` | `{"detail": "Unknown image_style 'xyz'. Supported styles: ['default', 'cinematic', ...]"}` |
| 400 | V-CaaS flow missing `video_idea_id` when `run_id` omitted | `{"detail": "video_idea_id is required when run_id is not supplied in brief-aware flow."}` |
| 400 | Platform not found in `brief.platform_briefs` | `{"detail": "Platform 'TikTok' not found in brief.platform_briefs. Available platforms: ['LinkedIn', 'Instagram']"}` |
| 409 | Workflow already running | `{"detail": "An image generation job is already in progress for this user."}` |
| 500 | Supabase not configured | `{"detail": "Image generation storage is not configured. SUPABASE_URL and SUPABASE_ANON_KEY must be set."}` |
| 500 | Temporal workflow start failure | `{"detail": "Failed to start image workflow: <error>"}` |

## Important Invariants

- `user_access_token` is **required** because generated images are uploaded to Supabase
- `SUPABASE_URL` and `SUPABASE_ANON_KEY` must be configured in the environment
- `image_style` must map to a known workflow name in `IMAGE_STYLE_TO_WORKFLOW_MAPPING`
- `workflow_id` is constructed as `tabario-image-user-{user_id}-{run_id}` by the backend
- The Temporal search attribute `TabarioRunId` is set to `[run_id]` for correlation
- Generated images are uploaded to Supabase storage at `{user_id}/{run_id}/image_XXX.png`
- The completion webhook includes `image_files` array with uploaded image names

## Workflow Behavior

1. Validates `image_style` against known workflows
2. Validates Supabase configuration is present
3. Derives `run_id` if omitted (legacy: hash-based, V-CaaS: `{video_idea_id}-{platform}`)
4. Constructs `workflow_id` as `tabario-image-user-{user_id}-{run_id}`
5. Starts `ImageGenerationWorkflow` on Temporal task queue `video-generation-task-queue`
6. Sets `id_reuse_policy` to `ALLOW_DUPLICATE_FAILED_ONLY`
7. Returns `202` immediately (workflow runs asynchronously)

## Output

Generated images are uploaded to Supabase storage:

```
{user_id}/{run_id}/image_001.png
{user_id}/{run_id}/image_002.png
{user_id}/{run_id}/image_003.png
...
```

The completion webhook includes:

```json
{
  "run_id": "abc123",
  "status": "completed",
  "workflow_id": "tabario-image-user-user-42-abc123",
  "image_files": ["image_001.png", "image_002.png", "image_003.png"],
  "output_dir": "/data/shared/abc123"
}
```

## Related Documentation

- [Image Generation Workflow](workflows/image-generation-workflow.md)
- [Webhook Payloads](data-contracts/webhook-payloads.md)
- [Supabase Storage Integration](integrations/supabase-storage.md)
