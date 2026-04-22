# Webhook Payloads

This document describes outbound webhook payloads sent by the video generation service.

## Completion Webhook

Configured by `VIDEO_COMPLETED_N8N_WEBHOOK_URL`.

### Always-Present Fields

These fields are **always** present in every completion webhook:

| Field | Type | Description | Example |
|---|---|---|---|
| `run_id` | string | Business identifier for the run | `"run-abc123"` |
| `status` | string | Workflow completion status: `"completed"` or `"failed"` | `"completed"` |

### Conditionally-Present Fields

These fields are present **depending on the workflow and execution context**:

| Field | Type | Present When | Description |
|---|---|---|---|
| `workflow_id` | string | Always (success or failure) | Temporal workflow identifier | 
| `output_dir` | string | Always (success or failure) | Shared working directory path |
| `final_video_path` | string | Video generation succeeded | Local path to final stitched video |
| `video_files` | array | Video generation succeeded | List of local paths to individual clip files |
| `image_files` | array | Image generation succeeded | List of image filenames (not full paths) |
| `voiceover_path` | string | Voiceover generation succeeded | Local path to voiceover audio file |
| `uploaded_video_object_path` | string | **Only** `StoryBoardVideoGeneration` workflow | Supabase storage object path for uploaded final video |
| `video_idea_id` | string | V-CaaS brief-aware flow | Supabase `video_ideas.id` echoed from request |
| `platform` | string | V-CaaS brief-aware flow | Platform identifier echoed from request (e.g., `"LinkedIn"`) |
| `scene_classifications` | array | Scene classifier enabled (`SCENE_CLASSIFIER_ENABLED=true`) | Array of `SceneClassification` objects (see `scene-classifier.md`) |
| `video_provider_used` | string | Always (when video generation ran) | Provider used for video generation: `"fal"` or `"runpod"` |

## Workflow-Specific Contract Differences

### `VideoGenerationWorkflow` started by `POST /orchestrate/start`

On success, the completion webhook includes the local final path only (no Supabase upload).

**Legacy flow example:**

```json
{
  "run_id": "run-abc123",
  "status": "completed",
  "workflow_id": "tabario-user-user-42-run-abc123",
  "output_dir": "/data/shared/run-abc123",
  "final_video_path": "/data/shared/run-abc123/final_video.mp4",
  "video_files": ["/data/shared/run-abc123/000_clip.mp4"],
  "image_files": ["image_001.png"],
  "voiceover_path": "/data/shared/run-abc123/voiceover.mp3"
}
```

**V-CaaS brief-aware flow example:**

```json
{
  "run_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "status": "completed",
  "workflow_id": "tabario-user-user-42-fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "output_dir": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "final_video_path": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/final_video.mp4",
  "video_files": ["/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/000_clip.mp4"],
  "image_files": ["image_001.png"],
  "voiceover_path": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/voiceover.mp3",
  "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
  "platform": "LinkedIn"
}
```

### `ImageGenerationWorkflow` started by `POST /orchestrate/generate-images`

On success, the completion webhook includes image files uploaded to Supabase.

**Legacy flow example:**

```json
{
  "run_id": "abc123",
  "status": "completed",
  "workflow_id": "tabario-image-user-user-42-abc123",
  "output_dir": "/data/shared/abc123",
  "image_files": ["image_001.png", "image_002.png", "image_003.png"]
}
```

**V-CaaS brief-aware flow example:**

```json
{
  "run_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "status": "completed",
  "workflow_id": "tabario-image-user-user-42-fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "output_dir": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "image_files": ["image_001.png", "image_002.png", "image_003.png"],
  "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
  "platform": "LinkedIn"
}
```

### `StoryBoardVideoGeneration` started by `POST /orchestrate/generate-videos`

On success, the completion webhook includes both the local final path and the Supabase object path.

**Legacy flow example:**

```json
{
  "run_id": "kef99ac7y9e",
  "status": "completed",
  "workflow_id": "tabario-storyboard-video-user-user-42-kef99ac7y9e",
  "output_dir": "/data/shared/kef99ac7y9e",
  "final_video_path": "/data/shared/kef99ac7y9e/final_video.mp4",
  "video_files": ["/data/shared/kef99ac7y9e/000_clip.mp4"],
  "voiceover_path": "/data/shared/kef99ac7y9e/voiceover.mp3",
  "uploaded_video_object_path": "user-42/kef99ac7y9e/final_video.mp4"
}
```

**V-CaaS brief-aware flow example:**

```json
{
  "run_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "status": "completed",
  "workflow_id": "tabario-storyboard-video-user-user-42-fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "output_dir": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin",
  "final_video_path": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/final_video.mp4",
  "video_files": ["/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/000_clip.mp4"],
  "voiceover_path": "/data/shared/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/voiceover.mp3",
  "uploaded_video_object_path": "user-42/fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin/final_video.mp4",
  "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
  "platform": "LinkedIn"
}
```

## Failure Payloads

Failure payloads always include at least:

```json
{
  "run_id": "run-abc123",
  "status": "failed"
}
```

Depending on where the failure happened, the payload may also include:

- `workflow_id`
- `output_dir`
- partial `video_files`
- partial `image_files`
- `voiceover_path`

## Event Type

The backend wraps the payload in an event envelope when sending through the webhook manager:

```json
{
  "event": "job_completed",
  "timestamp": 123456.789,
  "data": {
    "run_id": "run-abc123",
    "status": "completed"
  }
}
```

For failures, `event` becomes `job_failed`.
