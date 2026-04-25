# N8N Webhook Integrations

This document describes the N8N-facing webhook contracts used by the service.

## Configuration

Environment variables:

- `VIDEO_COMPLETED_N8N_WEBHOOK_URL`
- `IMAGE_GENERATION_N8N_WEBHOOK_URL`
- `N8N_PROMPTS_WEBHOOK_URL`
- `N8N_VOICEOVER_WEBHOOK_URL`
- `WEBHOOK_SECRET` (configured, but not currently applied by `WebhookManager`)

## Outbound Event Envelope

All outbound completion-style webhooks sent through `WebhookManager` use this envelope:

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

## Outbound: Video Completion Webhook

- **Target:** `VIDEO_COMPLETED_N8N_WEBHOOK_URL`
- **Emitter:** `send_completion_webhook`

### Base Data Payload

```json
{
  "run_id": "run-abc123",
  "status": "completed"
}
```

### Optional Data Fields

- `workflow_id`
- `output_dir`
- `final_video_path`
- `video_files`
- `image_files`
- `voiceover_path`
- `uploaded_video_object_path`

### Workflow-Specific Differences

#### `VideoGenerationWorkflow`

Success payload includes local output details only.

#### `StoryBoardVideoGeneration`

Success payload may additionally include:

```json
{
  "uploaded_video_object_path": "user-42/kef99ac7y9e/final_video.mp4"
}
```

## Outbound: Image Generation Webhook

- **Target:** `IMAGE_GENERATION_N8N_WEBHOOK_URL`
- **Emitter:** `send_image_generation_webhook`

### Data Payload

```json
{
  "run_id": "abc123",
  "workflow_id": "tabario-image-user-user-42-abc123",
  "status": "completed",
  "image_files": ["image_001.png", "image_002.png"],
  "image_prompts": ["Prompt 1", "Prompt 2"],
  "output_dir": "/data/shared/abc123"
}
```

### Important Rules

- `workflow_id` is required for image-generation webhooks
- on failure, `status` becomes `failed`
- failure payloads may include partial `image_files` and `image_prompts`

## Inbound: Voiceover Generation Webhook Dependency

The backend calls an external voiceover service/webhook during voiceover generation.

### Required Conceptual Request Fields

Based on workflow usage, the voiceover generation request depends on:

```json
{
  "script": "Narration text",
  "runId": "run-abc123",
  "language": "en",
  "elevenlabs_voice_id": "voice-id"
}
```

### Expected Side Effects

The downstream integration is expected to make the following available in `/data/shared/{run_id}`:

- `voiceover.mp3`
- voiceover metadata usable by the backend

## Inbound: Scene Prompt Generation Webhook Dependency

Scene generation activities depend on an external prompt-generation webhook.

### Image Scene Prompt Request Concept

```json
{
  "run_id": "abc123",
  "script": "Narration text",
  "language": "en",
  "image_style": "default"
}
```

### Video Scene Prompt Request Concept

```json
{
  "run_id": "run-abc123",
  "script": "Narration text",
  "image_style": "default"
}
```

### Expected Response Shape

The response must include:

```json
{
  "prompts": [
    {
      "image_prompt": "Prompt text",
      "video_prompt": "Prompt text"
    }
  ]
}
```

### Important Rules

- the backend requires `prompts` to be a list
- storyboard video generation later requires every storyboard scene entry to have `video_prompt`
- image generation requires each scene prompt to have `image_prompt`

## Error Handling Expectations

- non-2xx webhook responses are treated as runtime failures
- HTTP/network failures are surfaced as runtime failures
- outbound requests use JSON payloads with `Content-Type: application/json`

## Related Contracts

- `docs/api/data-contracts/webhook-payloads.md`
- `docs/api/workflows/video-generation-workflow.md`
- `docs/api/workflows/image-generation-workflow.md`
- `docs/api/workflows/storyboard-video-workflow.md`
