---
title: ProcessSceneWorkflow
category: workflows
kind: workflow_contract
workflows:
  - ProcessSceneWorkflow
related:
  - workflows/video-generation-workflow.md
  - endpoints/orchestrate.md
  - data-contracts/request-models.md
tags:
  - temporal
  - child-workflow
  - scene-processing
audience:
  - internal
---
# ProcessSceneWorkflow

This document defines the contract for `ProcessSceneWorkflow`, the child Temporal workflow used by `VideoGenerationWorkflow` to process a single scene.

## Entry Point

- **Workflow name:** `ProcessSceneWorkflow`
- **Started by:** `VideoGenerationWorkflow`
- **Input shape:** positional workflow arguments
- **Returns:** `list[str]` of generated local video clip paths

## Input Contract

The workflow receives these ordered arguments:

```json
[
  "run-abc123",
  {
    "image_prompt": "Cinematic wide shot of a futuristic city at sunrise",
    "video_prompt": "Slow cinematic push-in, gentle camera drift, atmospheric lighting"
  },
  "/app/workflows/default.json",
  0,
  360,
  640,
  720,
  1280,
  "default-workflow-name",
  null
]
```

### Argument Meaning

- `run_id`: business identifier for the shared run directory
- `prompt`: `PromptItem` containing `image_prompt` and optional `video_prompt`
- `workflow_path`: ComfyUI workflow file path used for image generation
- `index`: scene index
- `image_width`, `image_height`: image-generation dimensions
- `video_width`, `video_height`: video-generation dimensions
- `comfyui_workflow_name`: optional mapped internal workflow name
- `image_style`: optional style override passed through for supported workflows

## Workflow Steps

1. **Generate image**
   - activity: `start_image_generation`
   - activity: `poll_image_generation`

2. **Upload image for video generation**
   - activity: `upload_image_for_video_generation`

3. **Generate video clip**
   - activity: `start_video_generation`
   - activity: `poll_video_generation`

## Key Invariants

- if `prompt.image_prompt` is missing or yields no image, the workflow returns an empty list
- `upload_image_for_video_generation` runs only after an image is successfully generated
- video generation runs only when `prompt.video_prompt` is present
- permanent scene failures are raised as non-retryable `ApplicationError`
- this workflow does not send its own webhook
- correlation to the parent workflow is preserved through the parent-child workflow relationship and memo/search attributes set by the parent

## Success Output

Typical return value:

```json
[
  "/data/shared/run-abc123/000_clip.mp4"
]
```

The workflow may also return multiple clip paths if the underlying video generation activity saves multiple outputs for a scene.

## Skip Behavior

If no image is generated, the workflow returns:

```json
[]
```

This is treated by the parent as a scene with no generated clips.

## Failure Contract

On failure, the workflow:

- raises a non-retryable `ApplicationError`
- includes scene-specific context in the error message
- does not emit a webhook directly

## Related Contracts

- `docs/api/workflows/video-generation-workflow.md`
- `docs/api/endpoints/orchestrate.md`
