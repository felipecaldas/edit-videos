# Request Models

This document centralizes the shared request-model contracts used by the API and Temporal workflows.

## `PromptItem`

Used as an optional per-scene override in orchestration requests.

```json
{
  "image_prompt": "Cinematic wide shot of a futuristic city at sunrise",
  "video_prompt": "Slow cinematic push-in, gentle camera drift, atmospheric lighting"
}
```

### Fields

- `image_prompt`: optional string
- `video_prompt`: optional string

## `StitchRequest`

Used by `POST /stitch` and `POST /stitch_with_subtitles`.

```json
{
  "voiceover": "https://example.com/voiceover.mp3",
  "videos": [
    "https://example.com/video-1.mp4",
    "https://example.com/video-2.mp4"
  ]
}
```

### Fields

- `voiceover`: required string URL or accessible file path
- `videos`: required ordered list of URL/path strings

## `FolderStitchRequest`

Used by `POST /stitch` and `POST /stitch_with_subtitles` in folder-discovery mode.

```json
{
  "folder_path": "C:\\shared\\run-abc123"
}
```

### Fields

- `folder_path`: required directory path containing voiceover audio and MP4 clips

## `SubtitlesRequest`

Used by `POST /subtitles`.

```json
{
  "source": "https://example.com/video.mp4",
  "language": "pt",
  "model_size": "small",
  "subtitle_position": "bottom"
}
```

### Fields

- `source`: required URL or container-visible file path
- `language`: optional string, default `pt`
- `model_size`: optional string, default `small`
- `subtitle_position`: optional string, default `bottom`

## `StitchWithSubsRequest`

Extends `StitchRequest` for subtitle generation.

```json
{
  "voiceover": "https://example.com/voiceover.mp3",
  "videos": ["https://example.com/video-1.mp4"],
  "language": "pt",
  "model_size": "small",
  "subtitle_position": "bottom"
}
```

## `FolderStitchWithSubsRequest`

Extends `FolderStitchRequest` for subtitle generation.

```json
{
  "folder_path": "C:\\shared\\run-abc123",
  "language": "pt",
  "model_size": "small",
  "subtitle_position": "bottom"
}
```

## V-CaaS Brief Models

The following models are shared by all three `/orchestrate/*` request bodies and are used to trigger the brief-aware (V-CaaS) flow. They are **all optional** on the request bodies — omitting them produces the legacy behavior.

### `SceneBrief`

A single scene inside a platform brief. One `SceneBrief` corresponds to one generated image-to-video clip.

```json
{
  "scene_number": 1,
  "spoken_line": "Every founder has that moment.",
  "caption_text": "The moment everything changes.",
  "duration_seconds": 2.0,
  "visual_description": "A founder at a desk at night, lit by the glow of a laptop."
}
```

All fields are required when a `SceneBrief` is supplied.

### `VisualDirection`

Shared visual-direction cues applied across all platform briefs. All fields are optional strings.

```json
{
  "mood": "optimistic",
  "color_feel": "warm pastels",
  "shot_style": "clean studio",
  "branding_elements": "Tabario wordmark lower-third"
}
```

### `PlatformBriefModel`

Per-platform execution brief. `scenes` drive per-scene clip length and voiceover concatenation.

```json
{
  "platform": "LinkedIn",
  "hook": "Optional platform-specific opening hook.",
  "tone": "confident, conversational",
  "aspect_ratio": "1:1",
  "scenes": [
    {
      "scene_number": 1,
      "spoken_line": "...",
      "caption_text": "...",
      "duration_seconds": 2.0,
      "visual_description": "..."
    }
  ],
  "call_to_action": "Optional CTA string.",
  "platform_notes": "Optional platform-specific guidance or constraints."
}
```

- `platform` is required; all other fields optional.
- `scenes` defaults to an empty list when omitted.
- `aspect_ratio` supports `1:1`, `9:16`, `16:9`.

### `Brief`

Top-level brief carrying cross-platform narrative plus per-platform execution briefs. All fields optional.

```json
{
  "hook": "Cross-platform narrative hook.",
  "title": "Working title for the video idea.",
  "narrative_structure": "problem-solution-CTA",
  "music_sound_mood": "upbeat acoustic",
  "visual_direction": { "mood": "optimistic", "color_feel": "warm pastels", "shot_style": "clean studio", "branding_elements": "wordmark" },
  "platform_briefs": [
    { "platform": "LinkedIn", "scenes": [] }
  ]
}
```

## `OrchestrateStartRequest`

Used by `POST /orchestrate/start` and `VideoGenerationWorkflow`.

```json
{
  "user_id": "user-42",
  "script": "In 1999, a programmer accidentally changed the world.",
  "caption": "A short story about innovation.",
  "prompts": [
    {
      "image_prompt": "A hacker in a dimly lit room",
      "video_prompt": "Slow zoom toward the monitor"
    }
  ],
  "language": "en",
  "image_style": "default",
  "z_image_style": null,
  "image_width": 360,
  "image_height": 640,
  "video_format": "9:16",
  "target_resolution": "720p",
  "run_id": "run-abc123",
  "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
  "workflow_id": "optional-client-id",
  "enable_image_gen": true,
  "brief": null,
  "platform": null,
  "video_idea_id": null
}
```

### Required Fields

- `user_id`
- `script`
- `caption`

### Optional Fields (with router-derived defaults)

- `language` — defaults to `"en"`
- `image_style` — accepts the alias key `"style"` for N8N compatibility; router falls back to `"default"` when both are omitted
- `video_format` — router derives from `brief.platform_briefs[*].aspect_ratio` in the brief-aware flow, or from env default
- `target_resolution` — router falls back to env default
- `run_id` — router derives from `video_idea_id` + `platform` in the brief-aware flow
- `elevenlabs_voice_id` — router falls back to env default
- `prompts`, `workflow_id`, `enable_image_gen`, `z_image_style`, `image_width`, `image_height` — unchanged

### V-CaaS Brief-Aware Fields

- `brief` — optional `Brief` object; when present together with `platform`, the router/workflow skips the N8N prompts webhook and builds prompts directly from `brief.platform_briefs[*].scenes[]`
- `platform` — optional platform identifier that selects one `PlatformBriefModel` from `brief.platform_briefs`
- `video_idea_id` — optional Supabase `video_ideas.id` echoed back in completion webhooks

### Important Rules

- `prompts` is optional; when omitted in the legacy flow, prompts are generated automatically
- `video_format` supports `9:16`, `16:9`, `1:1`
- `target_resolution` supports `480p`, `720p`, `1080p`
- Legacy payloads (no `brief` / `platform`) continue to validate unchanged

## `ImageGenerationStartRequest`

Used by `POST /orchestrate/generate-images` and `ImageGenerationWorkflow`.

```json
{
  "user_id": "user-42",
  "script": "A short narrated story about a futuristic city.",
  "language": "en",
  "image_style": "default",
  "image_width": 360,
  "image_height": 640,
  "run_id": "abc123",
  "workflow_id": "optional-client-id",
  "user_access_token": "eyJhbGciOi...",
  "brief": null,
  "platform": null,
  "video_idea_id": null
}
```

### Required Fields

- `user_id`
- `script`
- `user_access_token`

### Optional Fields

- `language` — defaults to `"en"`
- `image_style` — defaults to `"default"`; accepts the alias key `"style"` for N8N compatibility
- `run_id` — router derives from script + language (legacy) or from `video_idea_id` + `platform` (brief-aware)
- `workflow_id` — backend may generate one
- `brief`, `platform`, `video_idea_id` — V-CaaS brief-aware fields; see `OrchestrateStartRequest` for semantics

### Important Rules

- `user_access_token` is required for Supabase uploads
- Legacy payloads continue to validate unchanged

## `StoryboardVideoGenerationRequest`

Used by `POST /orchestrate/generate-videos` and `StoryBoardVideoGeneration`.

```json
{
  "user_id": "user-42",
  "script": "In 1999, a programmer accidentally changed the world.",
  "language": "en",
  "run_id": "kef99ac7y9e",
  "workflow_id": "optional-client-id",
  "user_access_token": "eyJhbGciOi...",
  "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
  "video_format": "9:16",
  "target_resolution": "720p",
  "brief": null,
  "platform": null,
  "video_idea_id": null
}
```

### Required Fields

- `user_id`
- `script`
- `user_access_token`

### Optional Fields (with router-derived defaults)

- `language` — defaults to `"en"`
- `run_id` — router derives from `video_idea_id` + `platform` in the brief-aware flow
- `workflow_id` — backend may generate one
- `elevenlabs_voice_id` — router falls back to env default when omitted
- `video_format` — router derives from `brief.platform_briefs[*].aspect_ratio` or defaults to `"9:16"`
- `target_resolution` — router defaults to `"720p"`
- `brief`, `platform`, `video_idea_id` — V-CaaS brief-aware fields; see `OrchestrateStartRequest` for semantics

### Important Rules

- In the legacy flow, `run_id` must already reference a shared directory containing storyboard assets
- `user_access_token` is required for final-video upload to Supabase
- Legacy payloads continue to validate unchanged

## `UpscaleStartRequest`

Used by `POST /upscale/start` and `VideoUpscalingWorkflow`.

```json
{
  "run_id": "run-abc123",
  "user_id": "user-42",
  "target_resolution": "1080p",
  "workflow_id": "ignored-by-server",
  "voice_language": "en"
}
```

### Important Rules

- the server overwrites `workflow_id`
- `target_resolution` currently supports `720p` and `1080p` for the upscaling activity path

## `UpscaleChildRequest`

Internal workflow contract used by `VideoUpscalingChildWorkflow`.

```json
{
  "video_path": "/data/shared/run-abc123/001_clip.mp4",
  "video_id": "video-001",
  "run_id": "run-abc123",
  "user_id": "user-42",
  "target_resolution": "1080p",
  "workflow_id": "upscale-user-42-run-abc123"
}
```

## `UpscaleStitchRequest`

Internal workflow contract used by `VideoUpscalingStitchWorkflow`.

```json
{
  "run_id": "run-abc123",
  "user_id": "user-42",
  "workflow_id": "upscale-user-42-run-abc123",
  "voice_language": "en"
}
```

## `TranscriptionRequest`

Used by `POST /transcribe`.

```json
{
  "mp3_path": "/data/shared/run-abc123/voiceover.mp3",
  "language": "en",
  "model_size": "small"
}
```

### Important Rules

- `mp3_path` must point to a file under `/data/shared`
- `language` is optional and enables Whisper auto-detection when omitted

## Related Contracts

- `docs/api/data-contracts/response-models.md`
- `docs/api/endpoints/orchestrate.md`
- `docs/api/endpoints/stitch.md`
- `docs/api/endpoints/subtitles.md`
- `docs/api/endpoints/upscale.md`
