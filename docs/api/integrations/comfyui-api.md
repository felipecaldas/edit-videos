# ComfyUI Integration

This document describes the ComfyUI client contract used by the service in both local and RunPod-backed modes.

## Client Modes

The service creates ComfyUI clients through `get_comfyui_client(client_type, force_refresh=False)`.

### Local Mode

When `RUN_ENV` is not `runpod`:

- image and video operations use `LocalComfyUIClient`
- the client talks directly to `COMFYUI_URL`

### RunPod Mode

When `RUN_ENV=runpod`:

- image operations use a `RunPodComfyUIClient` bound to `RUNPOD_IMAGE_INSTANCE_ID`
- video operations use a `RunPodComfyUIClient` bound to `RUNPOD_VIDEO_INSTANCE_ID`

## Local Text-to-Image Contract

- **Method:** `submit_text_to_image(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/prompt`

### Requirements

- `template_path` is required
- workflow template must contain `{{ POSITIVE_PROMPT }}`
- placeholders for width/height are replaced before submission

### Request Shape

```json
{
  "prompt": {
    "...": "workflow payload"
  },
  "client_id": "uuid"
}
```

### Expected Response Shape

```json
{
  "prompt_id": "comfy-prompt-id"
}
```

## Local Image-to-Video Contract

- **Method:** `submit_image_to_video(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/prompt`

### Requirements

- `template_path` is required
- workflow template must contain:
  - `{{ VIDEO_PROMPT }}`
  - `{{ INPUT_IMAGE }}`
- local mode expects an input image filename, not a base64 data URL

### Expected Response Shape

```json
{
  "prompt_id": "comfy-prompt-id"
}
```

## Local Polling Contract

- **Method:** `poll_until_complete(...)`
- **HTTP endpoints:**
  - `{COMFYUI_URL}/queue`
  - `{COMFYUI_URL}/history`

### Completion Expectation

The history entry for the prompt must eventually contain completed outputs that can be converted into file hints.

## Local Output Download Contract

- **Method:** `download_outputs(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/view`

### Query Parameters

```json
{
  "filename": "output.png",
  "type": "output",
  "subfolder": "optional-subfolder"
}
```

## Local Input Upload Contract

- **Method:** `upload_image_to_input(...)`
- **HTTP endpoint:** `{COMFYUI_URL}/upload/image`

### Purpose

Uploads a generated image into the local ComfyUI input area so it can be referenced by filename for image-to-video generation.

## Shared Contract Concepts

### Image Generation Activities

The service expects ComfyUI clients to support:

- text-to-image submission
- polling until outputs are ready
- downloading or fetching output bytes

### Video Generation Activities

The service expects ComfyUI clients to support:

- image-to-video submission
- polling until outputs are ready
- downloading video outputs

### Output Hints

Clients return output references as either:

- filename/subfolder hints
- base64 data URLs

The activity layer is responsible for converting those into persisted local files.

## Error Handling Expectations

The integration fails when:

- workflow templates are missing required placeholders
- ComfyUI returns non-2xx responses
- response payloads omit `prompt_id`
- polling times out before outputs appear
- local mode receives base64 image data for image-to-video input where a filename is expected

## Related Contracts

- `docs/api/integrations/runpod-api.md`
- `docs/api/workflows/image-generation-workflow.md`
- `docs/api/workflows/video-generation-workflow.md`
- `docs/api/workflows/process-scene-workflow.md`
