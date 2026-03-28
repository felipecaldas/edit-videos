---
title: Upscaling Workflows
category: workflows
kind: workflow_contract
workflows:
  - VideoUpscalingWorkflow
  - VideoUpscalingChildWorkflow
  - VideoUpscalingStitchWorkflow
routes:
  - POST /upscale/start
related:
  - endpoints/upscale.md
  - workflows/video-generation-workflow.md
  - data-contracts/request-models.md
  - data-contracts/webhook-payloads.md
tags:
  - temporal
  - upscale
audience:
  - internal
---
# Upscaling Workflows

This document defines the contracts for the upscaling workflow chain:

- `VideoUpscalingWorkflow`
- `VideoUpscalingChildWorkflow`
- `VideoUpscalingStitchWorkflow`

## Parent Workflow: `VideoUpscalingWorkflow`

### Entry Point

- **Started by:** `POST /upscale/start`
- **Input model:** `UpscaleStartRequest`
- **Returns:** the string `"completed"` on success

### Input Contract

```json
{
  "run_id": "run-abc123",
  "user_id": "user-42",
  "target_resolution": "1080p",
  "workflow_id": "upscale-user-42-run-abc123",
  "voice_language": "en"
}
```

### Workflow Steps

1. **List source videos for upscale**
   - activity: `list_run_videos_for_upscale`
   - discovers clip files in `/data/shared/{run_id}`

2. **Start child upscaling workflows**
   - child workflow: `VideoUpscalingChildWorkflow`
   - one child per discovered input clip

3. **Wait for all children to finish**
   - all child workflows must complete successfully before stitching begins

4. **Start stitch child workflow**
   - child workflow: `VideoUpscalingStitchWorkflow`

5. **Send completion webhook**
   - activity: `send_upscale_completion_webhook`

### Key Invariants

- the parent workflow does not directly upscale files; it delegates to child workflows
- stitching begins only after all child upscale workflows finish successfully
- success webhook includes the final stitched path
- failure webhook uses an empty final path

### Success Output

```json
"completed"
```

### Failure Contract

On failure, the parent workflow:

- sends `send_upscale_completion_webhook` with `status = "failed"`
- includes `error_message` when available
- raises a non-retryable `ApplicationError`

## Child Workflow: `VideoUpscalingChildWorkflow`

### Input Model

`UpscaleChildRequest`

```json
{
  "video_path": "/data/shared/run-abc123/000_clip.mp4",
  "video_id": "000_clip",
  "run_id": "run-abc123",
  "user_id": "user-42",
  "target_resolution": "1080p",
  "workflow_id": "upscale-user-42-run-abc123"
}
```

### Workflow Steps

1. **Setup run directory**
   - activity: `setup_run_directory`

2. **Start RunPod upscale job**
   - activity: `start_video_upscaling`

3. **Poll upscale completion**
   - activity: `poll_upscale_status`
   - returns the saved local upscaled file path

### Key Invariants

- polling is retried more aggressively than job submission
- permanent RunPod failures are treated as non-retryable
- the child workflow returns the saved local path for the upscaled clip
- the child workflow does not emit a webhook directly

### Success Output

```json
"/data/shared/run-abc123/upscaled_000_clip.mp4"
```

## Stitch Workflow: `VideoUpscalingStitchWorkflow`

### Input Model

`UpscaleStitchRequest`

```json
{
  "run_id": "run-abc123",
  "user_id": "user-42",
  "workflow_id": "upscale-user-42-run-abc123",
  "voice_language": "en"
}
```

### Workflow Steps

1. **List upscaled videos**
   - activity: `list_upscaled_videos`

2. **Resolve existing shared assets**
   - voiceover path: `/data/shared/{run_id}/voiceover.mp3`
   - subtitle path reference: `/data/shared/{run_id}/generated.srt`

3. **Stitch upscaled clips**
   - activity: `stitch_videos`

4. **Burn subtitles**
   - activity: `burn_subtitles_into_video`

### Key Invariants

- the workflow expects upscaled clip files to already exist in the shared run directory
- the workflow expects `voiceover.mp3` to already exist in the shared run directory
- the final output path is local to `/data/shared/{run_id}`
- this workflow does not emit a webhook directly

### Success Output

```json
"/data/shared/run-abc123/final_video.mp4"
```

## Upscale Completion Webhook Contract

The parent workflow emits the final upscale webhook.

### Success Example

```json
{
  "run_id": "run-abc123",
  "status": "completed",
  "workflow_id": "upscale-user-42-run-abc123",
  "user_id": "user-42",
  "final_video_path": "/data/shared/run-abc123/final_video.mp4"
}
```

### Failure Example

```json
{
  "run_id": "run-abc123",
  "status": "failed",
  "workflow_id": "upscale-user-42-run-abc123",
  "user_id": "user-42",
  "final_video_path": "",
  "error_message": "Upscaling workflow failed"
}
```

## Related Contracts

- `docs/api/endpoints/upscale.md`
- `docs/api/workflows/video-generation-workflow.md`
