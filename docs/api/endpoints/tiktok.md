---
title: TikTok Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /tiktok/upload
tags:
  - tiktok
  - integration
audience:
  - public
---
# TikTok Endpoints

This document describes the TikTok upload endpoint.

## `POST /tiktok/upload`

Uploads a local video file to TikTok through the service's TikTok integration.

### Request Contract

```json
{
  "tiktok_bearer_token": "tiktok-user-access-token",
  "file_path": "/data/shared/run-abc123/final_video.mp4",
  "privacy_level": "SELF_ONLY"
}
```

### Fields

- `tiktok_bearer_token`: required string bearer token for TikTok API access
- `file_path`: required local filesystem path to the video to upload
- `privacy_level`: required TikTok privacy setting string

### Important Rules

- this endpoint delegates to `TikTokService.upload_video(...)`
- the backend does not validate `privacy_level` values before delegation
- the request depends on the local file being accessible to the API process
- the response shape is determined by the TikTok service integration result

### Success Response

HTTP `200`

The endpoint returns the raw result produced by `TikTokService.upload_video(...)`.

Example shape:

```json
{
  "status": "success",
  "publish_id": "example-publish-id"
}
```

### Error Responses

- `500` upload failed or TikTok service returned an exception

### Contract Caveat

Because this endpoint returns the integration result directly, its exact success payload should be treated as **integration-defined** unless `TikTokService` is further documented or wrapped in a stable response model.
