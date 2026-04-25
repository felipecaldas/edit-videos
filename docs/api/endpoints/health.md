---
title: Health and Admin Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - GET /health
  - POST /refresh-comfyui-client
  - GET /comfyui-client-info
related:
  - integrations/comfyui-api.md
  - integrations/runpod-api.md
  - data-contracts/response-models.md
tags:
  - health
  - admin
  - comfyui
audience:
  - admin
---
# Health and Admin Endpoints

This document describes the health and ComfyUI administration endpoints.

## `GET /health`

Lightweight health probe for the FastAPI service.

### Success Response

HTTP `200`

```json
{
  "status": "healthy"
}
```

## `POST /refresh-comfyui-client`

Refreshes ComfyUI client configuration in memory and can optionally update RunPod instance IDs persisted in the repository `.env` file.

### Request Contract

Request body is optional.

```json
{
  "image_instance_id": "optional-runpod-image-instance-id",
  "video_instance_id": "optional-runpod-video-instance-id"
}
```

### Important Rules

- this endpoint is **stateful** and may modify the repository `.env` file
- when `image_instance_id` is supplied, the service updates `RUNPOD_IMAGE_INSTANCE_ID`
- when `video_instance_id` is supplied, the service updates `RUNPOD_VIDEO_INSTANCE_ID`
- after updating `.env`, the service reloads config and resets both ComfyUI clients
- without a request body, the endpoint only checks whether clients should be refreshed based on current config

### Success Response

HTTP `200`

```json
{
  "refresh_results": {
    "image": true,
    "video": false
  },
  "client_info": {
    "image_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "instance_id": "image-instance-id"
    },
    "video_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "instance_id": "video-instance-id"
    }
  },
  "updated_variables": {
    "image_instance_id": {
      "old": "old-id",
      "new": "new-id"
    }
  },
  "status": "updated_and_refreshed",
  "message": "Updated instance IDs and refreshed clients"
}
```

### Response Notes

- `updated_variables` appears only when the request changes environment values
- `status` may be:
  - `updated_and_refreshed`
  - `refreshed`
  - `unchanged`
- `client_info` may contain an `error` object when client inspection fails

### Error Responses

- `500` refresh or configuration update failed

## `GET /comfyui-client-info`

Returns the currently configured ComfyUI client mode and instance IDs.

### Success Response

HTTP `200`

```json
{
  "status": "success",
  "clients": {
    "image_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "current_instance_id": "image-instance-id",
      "client_instance_id": "image-instance-id"
    },
    "video_client": {
      "type": "RunPodComfyUIClient",
      "base_url": "https://api.runpod.ai",
      "current_instance_id": "video-instance-id",
      "client_instance_id": "video-instance-id"
    }
  }
}
```

### Error Responses

- `500` client inspection failed

### Related Contracts

- `docs/api/integrations/comfyui-api.md`
- `docs/api/integrations/runpod-api.md`
- `docs/api/data-contracts/response-models.md`
