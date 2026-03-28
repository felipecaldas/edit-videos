# Webhook Payloads

This document describes outbound webhook payloads sent by the video generation service.

## Completion Webhook

Configured by `VIDEO_COMPLETED_N8N_WEBHOOK_URL`.

### Base Payload

```json
{
  "run_id": "run-abc123",
  "status": "completed"
}
```

### Common Optional Fields

```json
{
  "workflow_id": "tabario-user-user-42-run-abc123",
  "output_dir": "/data/shared/run-abc123",
  "final_video_path": "/data/shared/run-abc123/final_video.mp4",
  "video_files": ["/data/shared/run-abc123/000_clip.mp4"],
  "image_files": ["image_001.png"],
  "voiceover_path": "/data/shared/run-abc123/voiceover.mp3"
}
```

## Workflow-Specific Contract Differences

### `VideoGenerationWorkflow` started by `POST /orchestrate/start`

On success, the completion webhook includes the local final path only.

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

### `StoryBoardVideoGeneration` started by `POST /orchestrate/generate-videos`

On success, the completion webhook includes both the local final path and the Supabase object path.

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
