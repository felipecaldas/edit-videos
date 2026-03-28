---
title: Stitch Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /stitch
  - POST /stitch_with_subtitles
related:
  - endpoints/subtitles.md
  - data-contracts/request-models.md
  - data-contracts/response-models.md
tags:
  - stitching
  - media
audience:
  - public
---
# Stitch Endpoints

This document describes the synchronous stitching endpoints.

## `POST /stitch`

Stitches multiple MP4 clips together and overlays a single voiceover audio track.

### Accepted Request Shapes

#### Shape A: explicit sources

```json
{
  "voiceover": "https://example.com/voiceover.mp3",
  "videos": [
    "https://example.com/video-1.mp4",
    "https://example.com/video-2.mp4"
  ]
}
```

#### Shape B: folder-based discovery

```json
{
  "folder_path": "C:\\shared\\run-abc123"
}
```

### Folder-Based Rules

When `folder_path` is used:

- the folder must exist and be a directory
- the first `.mp3` file is preferred as voiceover
- if no `.mp3` exists, the first `.wav` is used
- all `.mp4` files in the folder are stitched in sorted filename order

### Explicit Source Rules

When `voiceover` + `videos` are used:

- `voiceover` is required
- `videos` must contain at least one item
- each source may be a URL or a locally accessible path

### Success Response

HTTP `200` file download

- media type: `video/mp4`
- filename pattern: `stitched_{session_id}.mp4`

### Error Responses

- `400` missing or empty voiceover
- `400` missing video list or empty video source
- `400` invalid `folder_path`
- `400` no usable audio or video files discovered in folder mode
- `500` concat or unexpected processing failure

## `POST /stitch_with_subtitles`

Stitches videos, overlays voiceover, generates subtitles with Whisper, and returns the subtitled final video.

### Accepted Request Shapes

#### Shape A: explicit sources

```json
{
  "voiceover": "https://example.com/voiceover.mp3",
  "videos": [
    "https://example.com/video-1.mp4",
    "https://example.com/video-2.mp4"
  ],
  "language": "pt",
  "model_size": "small",
  "subtitle_position": "bottom"
}
```

#### Shape B: folder-based discovery

```json
{
  "folder_path": "C:\\shared\\run-abc123",
  "language": "pt",
  "model_size": "small",
  "subtitle_position": "bottom"
}
```

### Important Rules

- stitching happens before subtitle generation
- subtitle generation uses Whisper on the stitched output
- in folder mode, a copy of the final output is also saved to `folder_path\\stitched_subtitled.mp4`
- failure to save the copy back to the folder does not fail the request

### Success Response

HTTP `200` file download

- media type: `video/mp4`
- filename pattern: `stitched_subtitled_{session_id}.mp4`

### Error Responses

- same input-validation errors as `/stitch`
- `500` subtitle generation failure
- `500` concat failure
- `500` unexpected processing failure

### Related Contracts

- `docs/api/endpoints/subtitles.md`
