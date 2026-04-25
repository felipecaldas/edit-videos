---
title: ImageGenerationWorkflow
category: workflows
kind: workflow_contract
workflows:
  - ImageGenerationWorkflow
routes:
  - POST /orchestrate/generate-images
related:
  - endpoints/orchestrate.md
  - workflows/storyboard-video-workflow.md
  - data-contracts/request-models.md
  - data-contracts/webhook-payloads.md
  - integrations/supabase-storage.md
tags:
  - temporal
  - image-generation
audience:
  - internal
---
# ImageGenerationWorkflow

This document defines the contract for `ImageGenerationWorkflow`, the Temporal workflow started by `POST /orchestrate/generate-images`.

## Entry Point

- **Workflow name:** `ImageGenerationWorkflow`
- **Started by:** `POST /orchestrate/generate-images`
- **Input model:** `ImageGenerationStartRequest`
- **Returns:** ordered saved image filenames as `list[str]`

## Input Contract

```json
{
  "user_id": "user-42",
  "script": "Narration text for storyboard generation.",
  "language": "en",
  "image_style": "default",
  "z_image_style": null,
  "image_width": 360,
  "image_height": 640,
  "run_id": "abc123",
  "workflow_id": "tabario-image-user-user-42-abc123",
  "user_access_token": "supabase-user-jwt"
}
```

## Workflow Steps

1. **Setup run directory**
   - activity: `setup_run_directory`

2. **Generate scene prompts for images**
   - activity: `generate_image_scene_prompts`
   - writes `scenes_response.json`
   - expects each scene to contain an `image_prompt`

3. **Resolve workflow settings**
   - maps `image_style` to an internal workflow file and optional style override

4. **Start image generation jobs in parallel**
   - activity: `start_image_generation`

5. **Poll image completion in parallel**
   - activity: `poll_image_generation`

6. **Persist images in parallel**
   - activity: `persist_image_output`
   - writes local `image_001.png`, `image_002.png`, etc.
   - uploads the same files to Supabase using `user_access_token`

7. **Send completion webhook**
   - activity: `send_image_generation_webhook`

## Key Invariants

- every generated scene must provide an `image_prompt`
- output file naming is deterministic: `image_{sequence:03d}.png`
- the returned `saved_images` list preserves sequence order
- the workflow uploads generated images to Supabase as part of the core contract
- `user_access_token` is required because uploads are authenticated

## Files Produced

Typical artifacts under `/data/shared/{run_id}`:

- `manifest.json`
- `scenes_response.json`
- `image_001.png`, `image_002.png`, ...

## Success Output

Return value:

```json
[
  "image_001.png",
  "image_002.png",
  "image_003.png"
]
```

Completion webhook payload includes:

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

## Failure Contract

On failure, the workflow:

- sends `send_image_generation_webhook` with `status = "failed"`
- may include partially persisted `image_files`
- may include partial `image_prompts`
- raises a non-retryable `ApplicationError`

## Related Contracts

- `docs/api/endpoints/orchestrate.md`
- `docs/api/workflows/storyboard-video-workflow.md`
