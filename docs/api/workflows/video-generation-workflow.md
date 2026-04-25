---
title: VideoGenerationWorkflow
category: workflows
kind: workflow_contract
workflows:
  - VideoGenerationWorkflow
routes:
  - POST /orchestrate/start
related:
  - endpoints/orchestrate.md
  - data-contracts/request-models.md
  - data-contracts/webhook-payloads.md
  - workflows/process-scene-workflow.md
tags:
  - temporal
  - video-generation
audience:
  - internal
---
# VideoGenerationWorkflow

This document defines the contract for `VideoGenerationWorkflow`, the main end-to-end Temporal workflow started by `POST /orchestrate/start`.

## Entry Point

- **Workflow name:** `VideoGenerationWorkflow`
- **Started by:** `POST /orchestrate/start`
- **Input model:** `OrchestrateStartRequest`
- **Returns:** local `final_video_path` as a string on success

## Input Contract

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
  "workflow_id": "tabario-user-user-42-run-abc123",
  "enable_image_gen": true
}
```

## Workflow Steps

1. **Setup run directory**
   - activity: `setup_run_directory`
   - writes `manifest.json` under `/data/shared/{run_id}`

2. **Generate voiceover**
   - activity: `generate_voiceover`
   - emits or expects `voiceover.mp3`
   - writes `voiceover_metadata.json`
   - if no explicit path is returned, workflow falls back to `/data/shared/{run_id}/voiceover.mp3`

3. **Generate scene prompts**
   - activity: `generate_scene_prompts`
   - writes `scene_prompts.json`
   - returns a list of scene prompts

4. **Start child scene workflows**
   - child workflow: `ProcessSceneWorkflow`
   - one child per scene prompt
   - child workflows share the same `TabarioRunId` search attribute

5. **Collect clip outputs**
   - child results are flattened into one `video_paths` list
   - if no clips are produced, workflow fails with a non-retryable error

6. **Stitch videos**
   - activity: `stitch_videos`
   - creates an intermediate stitched video in the shared run directory

7. **Burn subtitles**
   - activity: `burn_subtitles_into_video`
   - creates the final video file in the shared run directory

8. **Send completion webhook**
   - activity: `send_completion_webhook`
   - emits the local `final_video_path`

## Key Invariants

- `run_id` identifies the shared working directory `/data/shared/{run_id}`
- all child workflows inherit the same business correlation value through `TabarioRunId`
- output clip order depends on child workflow results as returned by the workflow implementation
- this workflow emits the **local** final video path in the completion webhook
- this workflow does **not** upload the final video to Supabase as part of the current contract

## Files Produced

Typical artifacts under `/data/shared/{run_id}`:

- `manifest.json`
- `voiceover.mp3`
- `voiceover_metadata.json`
- `scene_prompts.json`
- generated clip files
- stitched intermediate video
- final subtitled video

## Success Output

Return value:

```json
"/data/shared/run-abc123/final_video.mp4"
```

Completion webhook payload includes fields like:

```json
{
  "run_id": "run-abc123",
  "status": "completed",
  "workflow_id": "tabario-user-user-42-run-abc123",
  "output_dir": "/data/shared/run-abc123",
  "final_video_path": "/data/shared/run-abc123/final_video.mp4",
  "video_files": ["/data/shared/run-abc123/000_clip.mp4"],
  "image_files": ["Scene image prompt text"],
  "voiceover_path": "/data/shared/run-abc123/voiceover.mp3"
}
```

## Failure Contract

On failure, the workflow:

- sends `send_completion_webhook` with `status = "failed"`
- may include partial `video_files`
- may include partial image-prompt-derived `image_files`
- may include `voiceover_path` if it was already produced
- raises a non-retryable `ApplicationError`

## Related Contracts

- `docs/api/endpoints/orchestrate.md`
- `docs/api/data-contracts/webhook-payloads.md`
- `docs/api/workflows/process-scene-workflow.md`
