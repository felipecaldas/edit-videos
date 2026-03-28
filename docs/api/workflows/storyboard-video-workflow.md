---
title: StoryBoardVideoGeneration
category: workflows
kind: workflow_contract
workflows:
  - StoryBoardVideoGeneration
routes:
  - POST /orchestrate/generate-videos
related:
  - endpoints/orchestrate.md
  - workflows/image-generation-workflow.md
  - data-contracts/request-models.md
  - data-contracts/webhook-payloads.md
  - integrations/supabase-storage.md
tags:
  - temporal
  - storyboard
  - video-generation
audience:
  - internal
---
# StoryBoardVideoGeneration

This document defines the contract for `StoryBoardVideoGeneration`, the Temporal workflow started by `POST /orchestrate/generate-videos`.

## Entry Point

- **Workflow name:** `StoryBoardVideoGeneration`
- **Started by:** `POST /orchestrate/generate-videos`
- **Input model:** `StoryboardVideoGenerationRequest`
- **Returns:** local `final_video_path` as a string on success

## Purpose

Generate a final video from pre-existing storyboard assets instead of regenerating images.

## Required Prerequisites

The shared run directory must already contain:

- `/data/shared/{run_id}/scene_prompts.json`
- `/data/shared/{run_id}/image_001.png`
- `/data/shared/{run_id}/image_002.png`
- additional ordered `image_XXX.png` files matching the number of prompts

## Input Contract

```json
{
  "user_id": "user-42",
  "script": "Narration text for the final video.",
  "language": "en",
  "run_id": "kef99ac7y9e",
  "workflow_id": "tabario-storyboard-video-user-user-42-kef99ac7y9e",
  "user_access_token": "supabase-user-jwt",
  "elevenlabs_voice_id": "voice-id",
  "video_format": "9:16",
  "target_resolution": "720p"
}
```

## Workflow Steps

1. **Setup run directory**
   - activity: `setup_run_directory`

2. **Generate voiceover**
   - activity: `generate_voiceover`

3. **Load storyboard scene inputs**
   - activity: `load_storyboard_scene_inputs`
   - validates `scene_prompts.json`
   - validates matching `image_XXX.png` files
   - returns ordered `[{index, image_path, video_prompt}]`

4. **Start video generation jobs in parallel**
   - activity: `start_video_generation`
   - one job per ordered storyboard scene

5. **Poll video completion in parallel**
   - activity: `poll_video_generation`

6. **Build ordered clip list**
   - the workflow keeps the first returned video from each ordered scene result

7. **Stitch videos**
   - activity: `stitch_videos`

8. **Burn subtitles**
   - activity: `burn_subtitles_into_video`

9. **Upload final video to Supabase**
   - activity: `upload_final_video_output`
   - requires `user_access_token`

10. **Send completion webhook**
   - activity: `send_completion_webhook`
   - emits both local and Supabase object-path information on success

## Key Invariants

- image-to-video mapping is sequence-based: scene 1 -> `image_001.png`, scene 2 -> `image_002.png`
- generated intermediate clips remain in `/data/shared/{run_id}`
- only the final video is uploaded to Supabase
- this workflow returns the **local** final path, not the Supabase object path
- success webhook includes `uploaded_video_object_path`
- failure webhook currently does **not** include `uploaded_video_object_path`

## Files Produced

Typical artifacts under `/data/shared/{run_id}`:

- `manifest.json`
- `voiceover.mp3`
- generated video clip files
- stitched intermediate video
- final subtitled video

## Success Output

Return value:

```json
"/data/shared/kef99ac7y9e/final_video.mp4"
```

Completion webhook payload includes:

```json
{
  "run_id": "kef99ac7y9e",
  "status": "completed",
  "workflow_id": "tabario-storyboard-video-user-user-42-kef99ac7y9e",
  "output_dir": "/data/shared/kef99ac7y9e",
  "final_video_path": "/data/shared/kef99ac7y9e/final_video.mp4",
  "video_files": ["/data/shared/kef99ac7y9e/000_clip.mp4"],
  "voiceover_path": "/data/shared/kef99ac7y9e/voiceover.mp3",
  "uploaded_video_object_path": "user-42/kef99ac7y9e/final_video.mp4"
}
```

## Failure Contract

On failure, the workflow:

- sends `send_completion_webhook` with `status = "failed"`
- may include partial `video_files`
- may include `voiceover_path` if already produced
- does not include `uploaded_video_object_path` when upload never completed
- raises a non-retryable `ApplicationError`

## Related Contracts

- `docs/api/endpoints/orchestrate.md`
- `docs/api/data-contracts/webhook-payloads.md`
- `docs/api/workflows/image-generation-workflow.md`
