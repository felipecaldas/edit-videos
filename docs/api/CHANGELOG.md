# API Contract Changelog

This changelog records meaningful contract documentation changes under `docs/api`.

## Entry Format

Each entry should include:

- **Date**
- **Scope**
- **Compatibility**
- **Summary**
- **Affected Docs**
- **Migration Notes** when relevant

## Compatibility Labels

- `backward-compatible`
- `potentially-breaking`
- `documentation-only`

## 2026-03-28

### API documentation baseline established

- **Date**: 2026-03-28
- **Scope**: Endpoint contracts
- **Compatibility**: documentation-only
- **Summary**: Added endpoint contract documentation for orchestration, upscale, stitch, subtitles, health, audio, merge, test-runs, and TikTok routes.
- **Affected Docs**:
  - `docs/api/endpoints/orchestrate.md`
  - `docs/api/endpoints/upscale.md`
  - `docs/api/endpoints/stitch.md`
  - `docs/api/endpoints/subtitles.md`
  - `docs/api/endpoints/health.md`
  - `docs/api/endpoints/audio.md`
  - `docs/api/endpoints/merge.md`
  - `docs/api/endpoints/test-runs.md`
  - `docs/api/endpoints/tiktok.md`
- **Migration Notes**: None. These entries document existing behavior.

### Workflow and integration contracts documented

- **Date**: 2026-03-28
- **Scope**: Workflow contracts and external integrations
- **Compatibility**: documentation-only
- **Summary**: Added workflow docs for orchestration and upscaling flows, plus integration docs for webhook payloads, N8N, Supabase, RunPod, and ComfyUI.
- **Affected Docs**:
  - `docs/api/workflows/video-generation-workflow.md`
  - `docs/api/workflows/image-generation-workflow.md`
  - `docs/api/workflows/storyboard-video-workflow.md`
  - `docs/api/workflows/process-scene-workflow.md`
  - `docs/api/workflows/upscaling-workflows.md`
  - `docs/api/data-contracts/webhook-payloads.md`
  - `docs/api/integrations/n8n-webhooks.md`
  - `docs/api/integrations/supabase-storage.md`
  - `docs/api/integrations/runpod-api.md`
  - `docs/api/integrations/comfyui-api.md`
- **Migration Notes**: None. These entries document existing behavior.

### Shared references and governance guides added

- **Date**: 2026-03-28
- **Scope**: Shared references and meta documentation
- **Compatibility**: documentation-only
- **Summary**: Added centralized request/response model references, prerequisites guide, versioning guide, and top-level documentation index updates.
- **Affected Docs**:
  - `docs/api/data-contracts/request-models.md`
  - `docs/api/data-contracts/response-models.md`
  - `docs/api/prerequisites.md`
  - `docs/api/versioning.md`
  - `docs/api/README.md`
- **Migration Notes**: None. These entries document existing behavior.

## How to Use This File

Add a new entry whenever a task changes:

- request or response payloads
- status/error semantics
- workflow inputs/outputs
- webhook payloads
- integration payloads
- auth or prerequisite expectations

For breaking changes, explicitly describe the old behavior, the new behavior, and any client migration required.
