# API Prerequisites

This guide summarizes the authentication, environment, filesystem, and service prerequisites required to call the API successfully.

## Shared Runtime Assumptions

The service assumes:

- a writable shared filesystem rooted at `/data/shared`
- ffmpeg and ffprobe available to the API/worker processes
- access to a Temporal server
- access to configured external integrations such as N8N, Supabase, ComfyUI, and RunPod when the relevant flows are used

## Shared Filesystem Prerequisites

Many flows depend on deterministic paths under:

```text
/data/shared/{run_id}
```

### Common Expectations

- orchestration workflows create or reuse a run directory
- storyboard video generation expects existing storyboard assets in the run directory
- transcription requires an MP3 path under `/data/shared`
- stitch and subtitle endpoints may read container-visible local paths when URLs are not used

## Environment Variable Prerequisites

## Core Service Configuration

Required for normal orchestration/runtime behavior:

- `TEMPORAL_SERVER_URL`
- `DATA_SHARED_BASE`
- `TMP_BASE`
- `SUBTITLE_CONFIG_PATH`

## Voiceover and Prompt Generation

Required for workflows that generate voiceover or prompts:

- `VOICEOVER_SERVICE_URL`
- `N8N_VOICEOVER_WEBHOOK_URL` when webhook-driven voiceover flow is used
- `N8N_PROMPTS_WEBHOOK_URL`
- `VOICEOVER_API_KEY` when required by the downstream voiceover provider

## Supabase Storage

Required for image upload and final video upload flows:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_STORAGE_BUCKET`

### Important Rules

- image generation and storyboard final-video upload depend on Supabase being configured
- user-scoped uploads require a valid user JWT in the request payload

## Completion and Image Webhooks

Required when the workflow sends completion notifications:

- `VIDEO_COMPLETED_N8N_WEBHOOK_URL`
- `IMAGE_GENERATION_N8N_WEBHOOK_URL`

## ComfyUI and RunPod

Required for image/video generation flows:

- `COMFYUI_URL`
- `RUN_ENV`

When `RUN_ENV=runpod`, also required:

- `RUNPOD_API_KEY`
- `RUNPOD_IMAGE_INSTANCE_ID`
- `RUNPOD_VIDEO_INSTANCE_ID`
- `COMFY_ORG_API_KEY`

## Request-Level Authentication Prerequisites

## Supabase User JWT

These routes require a user JWT in the request body:

- `POST /orchestrate/generate-images`
- `POST /orchestrate/generate-videos`

### Why

The JWT is used as the `Authorization` bearer token for Supabase Storage uploads and allows uploads to respect RLS policies.

## TikTok Bearer Token

This route requires a TikTok bearer token in the request body:

- `POST /tiktok/upload`

### Why

The token is forwarded to `TikTokService.upload_video(...)` for TikTok API access.

## Input-Asset Prerequisites by Endpoint Group

## Orchestration

### `POST /orchestrate/start`

Requires:

- valid `run_id`
- valid `image_style`
- valid voiceover settings such as `elevenlabs_voice_id`
- reachable Temporal worker and downstream integrations

### `POST /orchestrate/generate-images`

Requires:

- valid `user_access_token`
- Supabase configuration
- valid `image_style`

### `POST /orchestrate/generate-videos`

Requires:

- existing `/data/shared/{run_id}` directory
- existing `scene_prompts.json`
- existing ordered `image_XXX.png` files
- valid `user_access_token`
- Supabase configuration

## Media Processing

### `POST /merge`

Requires:

- WAV audio upload
- exactly one video source: uploaded `video` or `videoUrl`
- ffmpeg installed

### `POST /stitch`

Requires either:

- `voiceover` plus ordered `videos`

or:

- `folder_path` containing one voiceover file and MP4 clips

### `POST /subtitles`

Requires:

- a reachable source URL or local path
- a source file with a video stream
- subtitle/Whisper runtime dependencies

### `POST /transcribe`

Requires:

- `.mp3` file under `/data/shared`

## Admin Endpoints

### `POST /refresh-comfyui-client`

Requires:

- permission for the service process to update `.env`
- valid RunPod instance ids if new ids are provided

### Warning

This endpoint mutates runtime configuration and should not be treated as a read-only health check.

## Common Failure Causes

- missing environment variables
- invalid `image_style`
- invalid or missing Supabase JWT
- inaccessible local file paths
- missing required files in `/data/shared/{run_id}`
- external service timeouts or non-2xx responses
- ffmpeg/ffprobe not installed or not reachable

## Related Documents

- `docs/api/README.md`
- `docs/api/integrations/n8n-webhooks.md`
- `docs/api/integrations/supabase-storage.md`
- `docs/api/integrations/runpod-api.md`
- `docs/api/integrations/comfyui-api.md`
