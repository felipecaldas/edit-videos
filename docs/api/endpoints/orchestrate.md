---
title: Orchestration Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /orchestrate/start
  - POST /orchestrate/generate-images
  - POST /orchestrate/generate-videos
related:
  - workflows/video-generation-workflow.md
  - workflows/image-generation-workflow.md
  - workflows/storyboard-video-workflow.md
  - data-contracts/request-models.md
  - data-contracts/response-models.md
  - data-contracts/webhook-payloads.md
tags:
  - orchestration
  - temporal
audience:
  - public
---
# Orchestration Endpoints

This document describes the contracts for the orchestration endpoints that start Temporal workflows.

## Common Response Shape

Successful workflow-start requests return HTTP `202` with:

```json
{
  "message": "Workflow started successfully.",
  "workflow_id": "tabario-user-user-42-run-abc123",
  "run_id": "run-abc123"
}
```

Some newer endpoints also include:

```json
{
  "status": "received"
}
```

## `POST /orchestrate/start`

Starts the main end-to-end video generation workflow.

### Purpose

Use this endpoint when the backend should generate the full pipeline from script to final video, including scene prompts, images, clips, subtitles, and final assembly.

### Request Contract

```json
{
  "user_id": "user-42",
  "script": "Narration text for the video.",
  "caption": "Caption shown or stored with the video.",
  "prompts": [
    {
      "image_prompt": "Optional override image prompt.",
      "video_prompt": "Optional override video prompt."
    }
  ],
  "language": "en",
  "image_style": "default",
  "z_image_style": null,
  "image_width": 360,
  "image_height": 640,
  "video_format": "9:16",
  "target_resolution": "720p",
  "run_id": "run-abc123",
  "elevenlabs_voice_id": "voice-id",
  "workflow_id": null,
  "enable_image_gen": true
}
```

### Important Rules

- `image_style` must map to a known internal workflow name
- `run_id` must be unique for a new run unless retrying a failed Temporal workflow
- this flow sends the completion webhook with the **local** `final_video_path`
- this flow does not require `user_access_token`

### Success Response

```json
{
  "message": "Workflow started successfully.",
  "workflow_id": "tabario-user-user-42-run-abc123",
  "run_id": "run-abc123"
}
```

### Error Responses

- `400` unknown `image_style`
- `409` workflow already running for the same workflow id
- `500` failure starting Temporal workflow

## `POST /orchestrate/generate-images`

Starts the image-only storyboard generation workflow.

### Purpose

Use this endpoint when the backend should generate scene images and upload them to Supabase, without generating the final video yet.

### Request Contract

```json
{
  "user_id": "user-42",
  "script": "Narration text for the storyboard.",
  "language": "en",
  "image_style": "default",
  "z_image_style": null,
  "image_width": 360,
  "image_height": 640,
  "run_id": "optional-run-id",
  "workflow_id": null,
  "user_access_token": "supabase-user-jwt"
}
```

### Important Rules

- if `run_id` is omitted, the backend derives one deterministically from `script` and `language`
- `user_access_token` is required because generated images are uploaded to Supabase
- `SUPABASE_URL` and `SUPABASE_ANON_KEY` must be configured
- `image_style` must map to a known internal workflow name

### Success Response

```json
{
  "message": "Image generation workflow started successfully.",
  "workflow_id": "tabario-image-user-user-42-abc123",
  "run_id": "abc123",
  "status": "received"
}
```

### Error Responses

- `400` missing `user_access_token`
- `400` unknown `image_style`
- `409` workflow already running
- `500` Supabase not configured or Temporal start failure

## `POST /orchestrate/generate-videos`

Starts the storyboard-to-video workflow using pre-generated prompts and images.

### Purpose

Use this endpoint when `scene_prompts.json` and ordered storyboard images already exist and the backend should generate clips, stitch them, burn subtitles, and upload only the final video.

### Prerequisites

The shared run directory must already contain:

- `/data/shared/{run_id}/scene_prompts.json`
- `/data/shared/{run_id}/image_001.png`
- `/data/shared/{run_id}/image_002.png`
- additional ordered `image_XXX.png` files matching the prompt count

### Request Contract

```json
{
  "user_id": "user-42",
  "script": "Narration text for the final video.",
  "language": "en",
  "run_id": "kef99ac7y9e",
  "workflow_id": null,
  "user_access_token": "supabase-user-jwt",
  "elevenlabs_voice_id": "voice-id",
  "video_format": "9:16",
  "target_resolution": "720p"
}
```

### Important Rules

- clips are generated from `image_XXX.png` in sequence order
- generated clips remain in `/data/shared/{run_id}`
- only the final video is uploaded to Supabase
- `user_access_token` is required for final video upload
- this flow sends the completion webhook with:
  - `final_video_path` as the local shared path
  - `uploaded_video_object_path` as the Supabase object path

### Success Response

```json
{
  "message": "Storyboard video generation workflow started successfully.",
  "workflow_id": "tabario-storyboard-video-user-user-42-kef99ac7y9e",
  "run_id": "kef99ac7y9e",
  "status": "received"
}
```

### Error Responses

- `400` missing `user_access_token`
- `409` workflow already running
- `500` Supabase not configured or Temporal start failure

## Correlation Rules

All orchestration endpoints set the Temporal search attribute:

```json
{
  "TabarioRunId": ["run-abc123"]
}
```

This allows parent and child workflows to be correlated by `run_id`.
