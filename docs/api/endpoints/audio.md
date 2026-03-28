---
title: Audio Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /audio_duration
related:
  - data-contracts/response-models.md
tags:
  - audio
  - utility
audience:
  - public
---
# Audio Endpoints

This document describes audio utility endpoints.

## `POST /audio_duration`

Calculates the duration of an uploaded audio file.

### Request Contract

Multipart form data:

- `audio`: required uploaded file

### Important Rules

- accepted content types must indicate audio, WAV, or MP3
- the file is written to a temporary session directory before duration inspection
- the endpoint returns JSON, not a file download

### Success Response

HTTP `200`

```json
{
  "duration": 12.34
}
```

### Error Responses

- `400` uploaded file is not recognized as MP3 or WAV audio
- `500` media duration could not be determined
- `500` unexpected processing failure

### Related Contracts

- `docs/api/data-contracts/response-models.md`
