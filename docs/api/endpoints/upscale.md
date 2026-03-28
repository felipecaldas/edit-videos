---
title: Upscale Endpoints
category: endpoints
kind: endpoint_contract
routes:
  - POST /upscale/start
related:
  - workflows/upscaling-workflows.md
tags:
  - upscale
  - temporal
audience:
  - public
---
# Upscale Endpoints

This document describes the contract for the upscaling API.

## `POST /upscale/start`

Starts the Temporal workflow chain that upscales generated clips, stitches them together, burns subtitles, and sends an upscale completion webhook.

### Request Contract

```json
{
  "run_id": "run-abc123",
  "user_id": "user-42",
  "target_resolution": "1080p",
  "workflow_id": "optional-client-supplied-id",
  "voice_language": "en"
}
```

### Important Rules

- the server rewrites `workflow_id` to `upscale-{user_id}-{run_id}` before starting the workflow
- source clips must already exist in `/data/shared/{run_id}`
- the workflow uses Temporal search attribute `TabarioRunId`
- output is asynchronous; this endpoint only enqueues the workflow

### Success Response

HTTP `202`

```json
{
  "message": "Upscaling workflow started successfully.",
  "workflow_id": "upscale-user-42-run-abc123",
  "run_id": "run-abc123"
}
```

### Error Responses

- `409` an upscaling workflow with the same workflow id is already running
- `500` failed to start the Temporal workflow

### Related Contracts

- `docs/api/workflows/upscaling-workflows.md`
