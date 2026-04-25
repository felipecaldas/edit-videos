# RunPod API Integration

This document describes the RunPod-facing contract used when `RUN_ENV=runpod`.

## Configuration

Environment variables:

- `RUN_ENV=runpod`
- `COMFYUI_URL`
- `RUNPOD_API_KEY`
- `RUNPOD_IMAGE_INSTANCE_ID`
- `RUNPOD_VIDEO_INSTANCE_ID`
- `RUNPOD_BASE_URL`
- `COMFY_ORG_API_KEY`

## Client Selection

When `RUN_ENV=runpod`, `get_comfyui_client(...)` creates `RunPodComfyUIClient` instances.

- image client uses `RUNPOD_IMAGE_INSTANCE_ID`
- video client uses `RUNPOD_VIDEO_INSTANCE_ID`

## Text-to-Image Submission Contract

- **Client method:** `submit_text_to_image(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/v2/{instance_id}/run`
- **Method:** `POST`

### Request Payload Shape

```json
{
  "input": {
    "prompt": "Prompt text",
    "width": 720,
    "height": 1024,
    "comfyui_workflow_name": "workflow-name",
    "comfy_org_api_key": "api-key",
    "image_style": "optional-style-override"
  }
}
```

### Important Rules

- `comfyui_workflow_name` is required for RunPod text-to-image generation
- image dimensions default when not provided
- missing `RUNPOD_API_KEY` prevents client construction

### Expected Response Shape

```json
{
  "id": "runpod-job-id"
}
```

## Image-to-Video Submission Contract

- **Client method:** `submit_image_to_video(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/v2/{instance_id}/run`
- **Method:** `POST`

### Request Payload Shape

```json
{
  "input": {
    "prompt": "Video prompt text",
    "image": "data:image/png;base64,...",
    "width": 720,
    "height": 1280,
    "length": 81,
    "output_resolution": 1280,
    "comfyui_workflow_name": "video_wan2_2_14B_i2v",
    "comfy_org_api_key": "api-key"
  }
}
```

### Important Rules

- local file paths are converted into base64 data URLs before submission
- output resolution is derived from the larger of width and height
- the current fixed generated length is `81`

### Expected Response Shape

```json
{
  "id": "runpod-job-id"
}
```

## Job Status Polling Contract

- **Client method:** `poll_until_complete(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/v2/{instance_id}/status/{prompt_id}`
- **Method:** `GET`

### Expected Status Values

- `COMPLETED`
- `FAILED`
- `ERROR`
- `IN_QUEUE`
- `RUNNING`
- `IN_PROGRESS`

### Completion Response Expectation

The payload is expected to contain an `output` section that can be converted into a list of file hints or base64 data URLs.

### Failure Behavior

- `FAILED` and `ERROR` are treated as non-retryable job failures
- repeated polling/network issues eventually produce a timeout error

## Output Download Contract

- **Client method:** `download_outputs(...)`

### Supported Output Forms

- base64 `data:` URLs
- output hints extractable from RunPod response payloads

### Side Effects

- decoded files are written to the destination run directory
- when a saved output is a video, first/last frame extraction may also run into `/data/shared/{run_id}/first_last/`

## Upscaling Contract

Upscaling uses a separate activity path but still depends on RunPod-facing job submission and polling semantics.

### Resolution Mapping

- `720p` -> `1280`
- `1080p` -> `1920`

Any unsupported target resolution causes a runtime failure.

## Error Handling Expectations

The integration fails when:

- required RunPod environment variables are missing
- RunPod returns non-2xx responses
- RunPod response body omits the expected `id`
- status polling returns terminal failure states
- polling exceeds the configured timeout

## Related Contracts

- `docs/api/integrations/comfyui-api.md`
- `docs/api/workflows/video-generation-workflow.md`
- `docs/api/workflows/process-scene-workflow.md`
- `docs/api/workflows/upscaling-workflows.md`
