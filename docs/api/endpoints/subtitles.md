---
title: Subtitle Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /subtitles
  - POST /subtitles/upload
  - POST /transcribe
related:
  - endpoints/stitch.md
  - data-contracts/request-models.md
  - data-contracts/response-models.md
tags:
  - subtitles
  - transcription
  - media
audience:
  - public
---
# Subtitle Endpoints

This document describes the subtitle-generation and transcription endpoints.

## `POST /subtitles`

Generates subtitles for a source video and burns them into the returned output file.

### Request Contract

```json
{
  "source": "https://example.com/video.mp4",
  "language": "pt",
  "model_size": "small",
  "subtitle_position": "bottom"
}
```

### Important Rules

- `source` may be a URL or a locally accessible path
- the obtained media must contain a video stream
- subtitle generation uses Whisper word segments and SRT chunking
- subtitle chunks are currently generated with up to 4 words and a minimum duration of 0.6 seconds

### Success Response

HTTP `200` file download

- media type: `video/mp4`
- filename pattern: `subtitled_{session_id}.mp4`

### Error Responses

- `400` media could not be obtained or is empty
- `400` input does not contain a video stream
- `500` burned output not created or empty
- `500` unexpected processing failure

## `POST /subtitles/upload`

Same contract as `/subtitles`, but accepts an uploaded file via multipart form data.

### Multipart Form Contract

- `file` required upload
- `language` optional, default `pt`
- `model_size` optional, default `small`
- `subtitle_position` optional, default `bottom`

### Important Rules

- the uploaded file must not be empty
- the uploaded media must contain a video stream

### Success Response

HTTP `200` file download

- media type: `video/mp4`
- filename pattern: `subtitled_{session_id}.mp4`

### Error Responses

- `400` uploaded file is empty
- `400` input does not contain a video stream
- `500` burned output not created or empty
- `500` unexpected processing failure

## `POST /transcribe`

Transcribes an MP3 file already present under `/data/shared`.

### Request Contract

```json
{
  "mp3_path": "/data/shared/run-abc123/voiceover.mp3",
  "language": "en",
  "model_size": "small"
}
```

### Important Rules

- `mp3_path` must start with `/data/shared/`
- the path must exist and be a file
- the file must have `.mp3` extension
- if `language` is omitted, Whisper auto-detects the language

### Success Response

HTTP `200`

```json
{
  "text": "Transcribed text goes here.",
  "detected_language": "en",
  "confidence": 0.98
}
```

### Error Responses

- `400` MP3 path is outside `/data/shared`
- `400` path is not a file
- `400` file extension is not `.mp3`
- `400` file is empty
- `404` file does not exist
- `500` transcription failure

### Related Contracts

- `docs/api/endpoints/stitch.md`
