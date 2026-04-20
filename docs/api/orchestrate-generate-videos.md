# POST /orchestrate/generate-videos

Generate a final video from existing storyboard assets.

## Purpose

Use this endpoint when:
- Storyboard images already exist (from a previous `/orchestrate/generate-images` call)
- `scene_prompts.json` already exists in the run directory
- The backend should generate video clips from images, stitch them, burn subtitles, and upload only the final video to Supabase

This is the second step in a two-phase workflow where images have been reviewed and approved.

## Method & Path

```
POST /orchestrate/generate-videos
```

## Prerequisites

The shared run directory **must** already contain:

```
/data/shared/{run_id}/scene_prompts.json
/data/shared/{run_id}/image_001.png
/data/shared/{run_id}/image_002.png
/data/shared/{run_id}/image_003.png
...
```

If these files are missing, the workflow will fail.

## Request Body

### Legacy Flow (Existing scene_prompts.json)

```json
{
  "user_id": "user-42",
  "script": "In 1999, a programmer accidentally changed the world.",
  "language": "en",
  "run_id": "kef99ac7y9e",
  "user_access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
  "video_format": "9:16",
  "target_resolution": "720p"
}
```

### V-CaaS Brief-Aware Flow

```json
{
  "user_id": "user-42",
  "script": "Every founder has that moment. The moment everything changes.",
  "language": "en",
  "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
  "platform": "LinkedIn",
  "user_access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
  "brief": {
    "title": "The Founder's Moment",
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
| `script` | string | Script used to generate the voiceover for the final video | `"In 1999, a programmer..."` |
| `user_access_token` | string | Supabase user JWT access token for authenticated storage uploads (respects RLS policies) | `"eyJhbGciOi..."` |

### Optional Fields (Legacy Flow)

| Field | Type | Default | Description |
|---|---|---|---|
| `language` | string | `"en"` | Language code for voiceover generation and subtitles |
| `run_id` | string | **required in legacy** | Existing run identifier whose shared directory contains `scene_prompts.json` and `image_XXX.png` files |
| `workflow_id` | string | auto-generated | Explicit Temporal workflow ID |
| `elevenlabs_voice_id` | string | env default | Voice ID for voiceover generation |
| `video_format` | string | `"9:16"` | Aspect ratio: `"9:16"`, `"16:9"`, or `"1:1"` |
| `target_resolution` | string | `"720p"` | Target resolution: `"480p"`, `"720p"`, or `"1080p"` |

### V-CaaS Brief-Aware Fields

| Field | Type | Required When | Description |
|---|---|---|---|
| `brief` | object | V-CaaS flow | Top-level brief object with per-platform execution briefs |
| `platform` | string | V-CaaS flow | Platform identifier selecting one `PlatformBriefModel` from `brief.platform_briefs` |
| `video_idea_id` | string | V-CaaS flow without `run_id` | Supabase `video_ideas.id`, used to derive `run_id` and echoed in webhooks |

## Derivation Rules (V-CaaS Flow)

When `brief` and `platform` are both present:

1. **`run_id` derivation**: If `run_id` is omitted, it is derived as `{video_idea_id}-{platform.lower()}`
   - Example: `"fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"`

2. **`video_format` derivation**: If `video_format` is omitted, it is derived from `platform_brief.aspect_ratio`:
   - `"1:1"` → `"1:1"`
   - `"9:16"` → `"9:16"`
   - `"16:9"` → `"16:9"`
   - Unknown values default to `"9:16"`

3. **Voiceover script**: In V-CaaS flow, the voiceover script is built by concatenating `scenes[].spoken_line` values instead of using `req.script` directly

4. **Per-scene clip length**: In V-CaaS flow, each video clip's target length is derived from `scenes[].duration_seconds` instead of using a uniform duration

## Response

### Success (202 Accepted)

```json
{
  "message": "Storyboard video generation workflow started successfully.",
  "workflow_id": "tabario-storyboard-video-user-user-42-kef99ac7y9e",
  "run_id": "kef99ac7y9e",
  "status": "received"
}
```

### Error Responses

| Status | Condition | Response Body |
|---|---|---|
| 400 | Missing `user_access_token` | `{"detail": "user_access_token is required for authenticated storage uploads."}` |
| 400 | V-CaaS flow missing `video_idea_id` when `run_id` omitted | `{"detail": "video_idea_id is required when run_id is not supplied in brief-aware flow."}` |
| 400 | Platform not found in `brief.platform_briefs` | `{"detail": "Platform 'TikTok' not found in brief.platform_briefs. Available platforms: ['LinkedIn', 'Instagram']"}` |
| 409 | Workflow already running | `{"detail": "A storyboard video generation job is already in progress for this user."}` |
| 500 | Supabase not configured | `{"detail": "Final video storage is not configured. SUPABASE_URL and SUPABASE_ANON_KEY must be set."}` |
| 500 | Temporal workflow start failure | `{"detail": "Failed to start storyboard video workflow: <error>"}` |

## Important Invariants

- `user_access_token` is **required** because the final video is uploaded to Supabase
- `SUPABASE_URL` and `SUPABASE_ANON_KEY` must be configured in the environment
- `workflow_id` is constructed as `tabario-storyboard-video-user-{user_id}-{run_id}` by the backend
- The Temporal search attribute `TabarioRunId` is set to `[run_id]` for correlation
- Generated video clips remain in `/data/shared/{run_id}` and are **not** uploaded to Supabase
- Only the final stitched video is uploaded to Supabase
- The completion webhook includes both `final_video_path` (local) and `uploaded_video_object_path` (Supabase)

## Workflow Behavior

1. Validates Supabase configuration is present
2. Derives `run_id`, `video_format` if in V-CaaS flow
3. Constructs `workflow_id` as `tabario-storyboard-video-user-{user_id}-{run_id}`
4. Starts `StoryBoardVideoGeneration` on Temporal task queue `video-generation-task-queue`
5. Sets `id_reuse_policy` to `ALLOW_DUPLICATE_FAILED_ONLY`
6. Returns `202` immediately (workflow runs asynchronously)

## Workflow Steps

1. **Load existing assets**: Reads `scene_prompts.json` and verifies `image_XXX.png` files exist
2. **Generate voiceover**: Creates voiceover from `script` (legacy) or concatenated `spoken_line` values (V-CaaS)
3. **Generate video clips**: Converts each `image_XXX.png` to a video clip using image-to-video model
4. **Stitch clips**: Combines clips in sequence order
5. **Burn subtitles**: Generates and burns subtitles onto the stitched video
6. **Upload final video**: Uploads only the final video to Supabase storage
7. **Send webhook**: Sends completion webhook with both local and Supabase paths

## Output

Final video is uploaded to Supabase storage:

```
{user_id}/{run_id}/final_video.mp4
```

The completion webhook includes:

```json
{
  "run_id": "kef99ac7y9e",
  "status": "completed",
  "workflow_id": "tabario-storyboard-video-user-user-42-kef99ac7y9e",
  "output_dir": "/data/shared/kef99ac7y9e",
  "final_video_path": "/data/shared/kef99ac7y9e/final_video.mp4",
  "video_files": ["/data/shared/kef99ac7y9e/000_clip.mp4", "/data/shared/kef99ac7y9e/001_clip.mp4"],
  "voiceover_path": "/data/shared/kef99ac7y9e/voiceover.mp3",
  "uploaded_video_object_path": "user-42/kef99ac7y9e/final_video.mp4"
}
```

Note: `uploaded_video_object_path` is **only** present in this workflow's completion webhook, not in `/orchestrate/start`.

## Related Documentation

- [Storyboard Video Workflow](workflows/storyboard-video-workflow.md)
- [Webhook Payloads](data-contracts/webhook-payloads.md)
- [Supabase Storage Integration](integrations/supabase-storage.md)
