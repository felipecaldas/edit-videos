# API Contracts

This folder contains MCP-friendly API and data contract documentation for the Tabario video generation backend.

## Purpose

Use these documents as the source of truth for:
- request and response payloads
- workflow start contracts
- webhook payloads
- important prerequisites and invariants

## Primary Audience

- developers working on Tabario services
- AI agents operating across Tabario projects
- automation flows that integrate with this backend

## Conventions

- `run_id` is the business identifier for a generation run
- `workflow_id` is the Temporal workflow identifier used for correlation
- `/data/shared/{run_id}` is the shared working directory for generated assets
- Supabase uploads require a valid user JWT when the operation is user-scoped

## First Documents

- `endpoints/orchestrate.md`
- `endpoints/upscale.md`
- `endpoints/stitch.md`
- `endpoints/subtitles.md`
- `endpoints/health.md`
- `endpoints/audio.md`
- `endpoints/merge.md`
- `endpoints/test-runs.md`
- `endpoints/tiktok.md`
- `data-contracts/webhook-payloads.md`

## Workflow Contracts

- `workflows/video-generation-workflow.md`
- `workflows/image-generation-workflow.md`
- `workflows/storyboard-video-workflow.md`
- `workflows/process-scene-workflow.md`
- `workflows/upscaling-workflows.md`

## Integration Contracts

- `integrations/n8n-webhooks.md`
- `integrations/supabase-storage.md`
- `integrations/runpod-api.md`
- `integrations/comfyui-api.md`

## Shared Model References

- `data-contracts/request-models.md`
- `data-contracts/response-models.md`

## Meta Guides

- `prerequisites.md`
- `versioning.md`
- `CHANGELOG.md`

## Next Recommended Additions

- endpoint grouping or audience labels (public, admin, test, integration)
