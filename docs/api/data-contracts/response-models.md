# Response Models

This document centralizes the main JSON response shapes returned by the API.

## Workflow Accepted Response

Used by asynchronous workflow-start endpoints such as:

- `POST /orchestrate/start`
- `POST /orchestrate/generate-images`
- `POST /orchestrate/generate-videos`
- `POST /upscale/start`

### Shape

```json
{
  "message": "Workflow started successfully.",
  "workflow_id": "tabario-user-user-42-run-abc123",
  "run_id": "run-abc123",
  "status": "received"
}
```

### Notes

- `status` is present on orchestration endpoints for accepted async work
- `upscale/start` currently returns `message`, `workflow_id`, and `run_id` without `status`
- message text varies by endpoint

## `TranscriptionResponse`

Returned by `POST /transcribe`.

```json
{
  "text": "Transcribed text goes here.",
  "detected_language": "en",
  "confidence": 0.98
}
```

### Fields

- `text`: required string
- `detected_language`: optional string
- `confidence`: optional float

## Audio Duration Response

Returned by `POST /audio_duration`.

```json
{
  "duration": 12.34
}
```

### Fields

- `duration`: numeric media duration in seconds

## Health Response

Returned by `GET /health`.

```json
{
  "status": "healthy"
}
```

## Refresh ComfyUI Client Response

Returned by `POST /refresh-comfyui-client`.

### Shape

```json
{
  "refresh_results": {
    "image": true,
    "video": false
  },
  "client_info": {
    "image_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "instance_id": "image-instance-id"
    },
    "video_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "instance_id": "video-instance-id"
    }
  },
  "updated_variables": {
    "image_instance_id": {
      "old": "old-id",
      "new": "new-id"
    }
  },
  "status": "updated_and_refreshed",
  "message": "Updated instance IDs and refreshed clients"
}
```

### Important Rules

- `updated_variables` is present only when request input changes environment values
- `status` may be `updated_and_refreshed`, `refreshed`, or `unchanged`
- `client_info` may contain an `error` field if client inspection fails during refresh flow

## ComfyUI Client Info Response

Returned by `GET /comfyui-client-info`.

```json
{
  "status": "success",
  "clients": {
    "image_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "current_instance_id": "image-instance-id",
      "client_instance_id": "image-instance-id"
    },
    "video_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "current_instance_id": "video-instance-id",
      "client_instance_id": "video-instance-id"
    }
  }
}
```

## File Download Responses

Returned by synchronous media-processing endpoints such as:

- `POST /merge`
- `POST /stitch`
- `POST /stitch_with_subtitles`
- `POST /subtitles`
- `POST /subtitles/upload`

### Contract

These endpoints return binary file responses rather than JSON.

Common properties:

- media type: `video/mp4`
- response body: generated MP4 file bytes
- filename: endpoint-specific generated name such as:
  - `merged_{session_id}.mp4`
  - `stitched_{session_id}.mp4`
  - `stitched_subtitled_{session_id}.mp4`
  - `subtitled_{session_id}.mp4`

## Error Response Model

Most endpoints use FastAPI `HTTPException` and therefore return this standard JSON error shape:

```json
{
  "detail": "Human-readable error message"
}
```

### Common Status Codes

- `400` invalid input or unsupported media
- `404` resource not found
- `409` workflow already running
- `500` internal processing or integration failure

## Related Contracts

- `docs/api/data-contracts/request-models.md`
- `docs/api/endpoints/orchestrate.md`
- `docs/api/endpoints/stitch.md`
- `docs/api/endpoints/subtitles.md`
- `docs/api/endpoints/upscale.md`
