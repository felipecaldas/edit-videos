---
title: Merge Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /merge
related:
  - data-contracts/response-models.md
tags:
  - merge
  - media
audience:
  - public
---
# Merge Endpoints

This document describes the audio/video merge endpoint.

## `POST /merge`

Combines a video source with a WAV audio track and returns a merged MP4 file.

### Request Contract

Multipart form data:

- `audio`: required WAV upload
- `video`: optional MP4 upload
- `videoUrl`: optional remote video URL

### Important Rules

- exactly one of `video` or `videoUrl` must be provided
- `audio` must be WAV format
- uploaded `video` must be `.mp4`
- if audio is longer than video, the service speeds up audio using `ffmpeg atempo`
- audio is normalized with `loudnorm` before muxing
- output duration is bounded by the shorter stream because ffmpeg runs with `-shortest`

### Example Request Modes

#### Uploaded video

- `audio`: `voice.wav`
- `video`: `clip.mp4`

#### Remote video

- `audio`: `voice.wav`
- `videoUrl`: `https://example.com/clip.mp4`

### Success Response

HTTP `200` file download

- media type: `video/mp4`
- filename pattern: `merged_{session_id}.mp4`

### Error Responses

- `400` neither `video` nor `videoUrl` was provided
- `400` both `video` and `videoUrl` were provided
- `400` audio is not WAV
- `400` uploaded video is not MP4
- `500` source media durations could not be determined
- `500` audio speed adjustment failed
- `500` ffmpeg merge failed
- `500` output file was not created or is empty
- `500` unexpected processing failure

### Related Contracts

- `docs/api/data-contracts/response-models.md`
