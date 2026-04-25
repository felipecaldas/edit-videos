# Fal.ai Provider API Contract

## Overview

Fal.ai is an external AI inference provider offering multiple image and video generation models. This document describes the request/response contracts we rely on for the Tabario integration.

## Base Configuration

- **API Base URL**: `https://fal.run` (via `fal-client` SDK)
- **Authentication**: API key via `FAL_AI_API_KEY` env var
- **SDK**: `fal-client` Python package

## Image Generation (Text-to-Image)

### Supported Models

Configured via `FAL_IMAGE_MODELS` env var (comma-separated):
- `fal-ai/flux-pro/v1.1` - High quality, slower
- `fal-ai/flux/dev` - Balanced quality/speed (default)
- `fal-ai/ideogram/v2` - Text rendering optimized
- `fal-ai/recraft-v3` - Style control

### Request Schema

```python
# Via fal-client SDK
handler = await fal_client.submit_async(
    model_name,  # e.g., "fal-ai/flux/dev"
    arguments={
        "prompt": str,           # Image generation prompt
        "image_size": {          # Optional, defaults to model's native size
            "width": int,        # Must be multiple of 8
            "height": int        # Must be multiple of 8
        },
        "num_inference_steps": int,  # Optional, default varies by model
        "guidance_scale": float,     # Optional, default 7.5
        "num_images": int,           # Optional, default 1
        "enable_safety_checker": bool,  # Optional, default true
        "seed": int              # Optional, for reproducibility
    }
)
```

### Response Schema

```python
# Polling for completion
result = fal_client.result(model_name, request_id)

# Result structure
{
    "images": [
        {
            "url": str,              # Temporary URL (expires in 24h)
            "width": int,
            "height": int,
            "content_type": str      # e.g., "image/jpeg"
        }
    ],
    "seed": int,                     # Seed used for generation
    "has_nsfw_concepts": [bool],     # Per-image NSFW flags
    "prompt": str                    # Echo of input prompt
}
```

### Error Responses

```python
{
    "error": {
        "message": str,
        "code": str,  # e.g., "INVALID_INPUT", "RATE_LIMIT_EXCEEDED", "MODEL_ERROR"
        "details": dict
    }
}
```

## Video Generation (Image-to-Video)

### Model

- **Model ID**: `bytedance/seedance-2.0/image-to-video`
- **Max duration**: ~5 seconds (configurable via `length` parameter)

### Request Schema

```python
handler = await fal_client.submit_async(
    "bytedance/seedance-2.0/image-to-video",
    arguments={
        "prompt": str,           # Motion/camera movement description
        "image_url": str,        # Input image URL or base64 data URL
        "width": int,            # Optional, default 720
        "height": int,           # Optional, default 1280
        "length": int,           # Optional, number of frames (default 81 = ~3s at 30fps)
        "fps": int,              # Optional, default 30
        "motion_bucket_id": int, # Optional, motion intensity (default 127)
        "cond_aug": float        # Optional, conditioning augmentation (default 0.02)
    }
)
```

### Response Schema

```python
result = fal_client.result("bytedance/seedance-2.0/image-to-video", request_id)

{
    "video": {
        "url": str,              # Temporary URL (expires in 24h)
        "content_type": str,     # "video/mp4"
        "file_name": str,
        "file_size": int         # Bytes
    },
    "seed": int
}
```

## Polling & Status

### Status Endpoint

```python
status = fal_client.status(model_name, request_id, with_logs=True)

{
    "status": str,  # "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED" | "FAILED"
    "logs": [
        {
            "message": str,
            "level": str,  # "info" | "warning" | "error"
            "timestamp": str
        }
    ],
    "queue_position": int  # When status="IN_QUEUE"
}
```

### Polling Strategy

- **Initial delay**: 2 seconds
- **Poll interval**: 3 seconds
- **Timeout**: Configurable per operation (default 600s for images, 600s for video)
- **Exponential backoff**: Not needed (Fal handles rate limiting server-side)

## File Upload (for i2v)

When passing images to Seedance, we need to upload to Fal's file storage first:

```python
# Upload file
file_url = fal_client.upload_file(file_path_or_bytes)

# Returns
{
    "url": str  # e.g., "https://v3.fal.media/files/..."
}
```

Alternatively, pass base64 data URL directly:
```python
"image_url": "data:image/png;base64,iVBORw0KGgo..."
```

## Rate Limits

| Tier | Requests/min | Concurrent |
|---|---|---|
| Free | 10 | 2 |
| Pro | 60 | 10 |
| Enterprise | Custom | Custom |

**Behavior on rate limit**:
- HTTP 429 response
- Retry-After header (seconds)
- Our implementation: 3 retries with exponential backoff

## Error Codes

| Code | Meaning | Retry? |
|---|---|---|
| `INVALID_INPUT` | Bad request parameters | No |
| `RATE_LIMIT_EXCEEDED` | Too many requests | Yes (after delay) |
| `MODEL_ERROR` | Model inference failed | Yes (up to 3x) |
| `TIMEOUT` | Request took too long | Yes (up to 3x) |
| `NSFW_CONTENT_DETECTED` | Safety checker triggered | No |
| `INSUFFICIENT_CREDITS` | Account out of credits | No |

## Output File Handling

Fal returns temporary URLs that expire in 24 hours. Our implementation:

1. **Download immediately** after polling completes
2. **Save to** `/data/shared/{run_id}/` with consistent naming
3. **Delete temp URL reference** after download

### File Naming Convention

- **Images**: `{scene_index:03d}_{uuid}.png`
- **Videos**: `{scene_index:03d}_{uuid}.mp4`

Matches existing Runpod naming for compatibility with downstream stitching.

## Example: Full Image Generation Flow

```python
import asyncio
import fal_client

async def generate_image(prompt: str, width: int, height: int) -> str:
    # Submit
    handler = await fal_client.submit_async(
        "fal-ai/flux/dev",
        arguments={
            "prompt": prompt,
            "image_size": {"width": width, "height": height}
        }
    )
    
    request_id = handler.request_id
    
    # Poll
    result = fal_client.result("fal-ai/flux/dev", request_id)
    
    # Download
    image_url = result["images"][0]["url"]
    # ... download to local storage ...
    
    return local_path
```

## Example: Full Video Generation Flow

```python
async def generate_video(prompt: str, image_path: str, width: int, height: int) -> str:
    # Upload image
    image_url = fal_client.upload_file(image_path)
    
    # Submit
    handler = await fal_client.submit_async(
        "bytedance/seedance-2.0/image-to-video",
        arguments={
            "prompt": prompt,
            "image_url": image_url,
            "width": width,
            "height": height,
            "length": 81  # ~3 seconds at 30fps
        }
    )
    
    request_id = handler.request_id
    
    # Poll
    result = fal_client.result("bytedance/seedance-2.0/image-to-video", request_id)
    
    # Download
    video_url = result["video"]["url"]
    # ... download to local storage ...
    
    return local_path
```

## SDK Reference

- **Docs**: https://fal.ai/docs
- **Python SDK**: https://github.com/fal-ai/fal-client-python
- **Model Gallery**: https://fal.ai/models
