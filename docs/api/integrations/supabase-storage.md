# Supabase Storage Integration

This document describes the Supabase Storage contract used for authenticated image and final-video uploads.

## Configuration

Environment variables:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_STORAGE_BUCKET`

## Authentication Model

`SupabaseStorageClient` uses two credentials in different header positions:

- `apikey`: always the Supabase anon key
- `Authorization: Bearer ...`: user JWT if provided, otherwise anon key

### Important Rule

Uploads used by orchestration require a **user JWT** so that storage access respects RLS policies.

## Object Path Contract

Uploaded objects use this deterministic path pattern:

```text
{user_id}/{run_id}/{file_name}
```

Examples:

- `user-42/abc123/image_001.png`
- `user-42/kef99ac7y9e/final_video.mp4`

## Image Upload Contract

- **Emitter:** `persist_image_output`
- **Used by:** `ImageGenerationWorkflow`
- **Content type:** `image/png`

### Local File Contract

The activity writes the local file first:

```text
/data/shared/{run_id}/image_{sequence:03d}.png
```

Then uploads the same bytes to Supabase.

### Returned Value

The activity returns the local filename, not the Supabase object path:

```json
"image_001.png"
```

## Final Video Upload Contract

- **Emitter:** `upload_final_video_output`
- **Used by:** `StoryBoardVideoGeneration`
- **Content type:** `video/mp4`

### Preconditions

- local final video file must exist
- local final video file must be non-empty
- `user_access_token` must be present

### Returned Value

Returns the uploaded Supabase object path:

```json
"user-42/kef99ac7y9e/final_video.mp4"
```

This value is then forwarded to the completion webhook as `uploaded_video_object_path`.

## Storage API Boundary

### Upload Endpoint Shape

The client posts to:

```text
{SUPABASE_URL}/storage/v1/object/{bucket}/{object_path}
```

With:

- multipart file upload
- `x-upsert: true`

### List Endpoint Shape

The client lists files via:

```text
{SUPABASE_URL}/storage/v1/object/list/{bucket}
```

With JSON body:

```json
{
  "prefix": "user-42/abc123"
}
```

## Error Handling Expectations

The integration fails when:

- `SUPABASE_URL` is missing
- `SUPABASE_ANON_KEY` is missing
- user JWT is missing for upload flows
- Supabase returns a non-2xx response
- local source file does not exist or is empty

Non-2xx responses are converted into runtime errors containing the HTTP status and response body.

## Related Contracts

- `docs/api/endpoints/orchestrate.md`
- `docs/api/workflows/image-generation-workflow.md`
- `docs/api/workflows/storyboard-video-workflow.md`
