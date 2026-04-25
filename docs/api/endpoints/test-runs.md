---
title: Test Run Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /tests/run
related:
  - integrations/comfyui-api.md
  - integrations/runpod-api.md
  - data-contracts/response-models.md
tags:
  - test
  - generation
audience:
  - test
---
# Test Run Endpoints

This document describes the lightweight test-generation endpoint.

## `POST /tests/run`

Runs a lightweight generation flow intended for validation and experimentation.

### Purpose

This endpoint creates a test output directory under `/data/shared/tests/{guid}` and performs:

- scene prompt generation
- one image generation attempt per scene
- one video generation attempt per scene

It does **not** generate voiceovers, stitch clips, or burn subtitles.

### Request Contract

```json
{
  "script": "A short narrated story about a futuristic city.",
  "language": "en",
  "image_style": "cinematic",
  "image_width": 360,
  "image_height": 640
}
```

### Fields

- `script`: required non-empty string
- `language`: required non-empty string
- `image_style`: optional string
- `image_width`: optional integer, minimum `64`
- `image_height`: optional integer, minimum `64`

### Important Rules

- output is written under `/data/shared/tests/{guid}`
- if `image_style` is omitted, the endpoint defaults to `cinematic`
- the endpoint writes a synthetic `voiceover_metadata.json` using estimated duration so it can reuse prompt-generation logic
- scenes missing `image_prompt` or `video_prompt` are skipped
- returned file paths are local filesystem paths, not uploaded storage URLs

### Success Response

HTTP `200`

```json
{
  "guid": "2d7d0d6d-f4ad-41d9-a91f-0f1263e0f9f0",
  "output_dir": "/data/shared/tests/2d7d0d6d-f4ad-41d9-a91f-0f1263e0f9f0",
  "scene_prompts": [
    {
      "image_prompt": "Cinematic skyline at dawn",
      "video_prompt": "Slow drifting camera move"
    }
  ],
  "image_files": [
    "/data/shared/tests/2d7d0d6d-f4ad-41d9-a91f-0f1263e0f9f0/scene_000_image_x.png"
  ],
  "video_files": [
    "/data/shared/tests/2d7d0d6d-f4ad-41d9-a91f-0f1263e0f9f0/scene_000_clip_00_x.mp4"
  ]
}
```

### Error Responses

- `500` failed to create the test output directory
- `500` prompt generation, image generation, or video generation failed

### Related Contracts

- `docs/api/integrations/comfyui-api.md`
- `docs/api/integrations/runpod-api.md`
- `docs/api/data-contracts/response-models.md`
