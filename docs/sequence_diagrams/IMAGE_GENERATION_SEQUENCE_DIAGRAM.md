# Image Generation System - Sequence Diagram

```mermaid
sequenceDiagram
    actor U as User
    participant F as Frontend
    participant N as N8N
    participant B as Backend API (FastAPI /orchestrate)
    participant T as Temporal Server
    participant TW as Temporal Worker
    participant C as ComfyUI / RunPod
    participant FS as File System (/data/shared)
    participant S as Supabase Storage

    Note over U,N: 🖼️ Image Generation Request
    U->>F: Requests image generation for script
    F->>N: POST image-generation webhook<br/>{user_id, script, language, image_style, z_image_style?}

    Note over N,B: Workflow Initiation
    N->>B: POST /orchestrate/generate-images<br/>{user_id, script, language, image_style, z_image_style?, image_width?, image_height?, run_id?}
    B->>B: Compute deterministic 6-char hex run_id if omitted
    B->>T: Start Workflow 'ImageGenerationWorkflow'<br/>with workflow_id + run_id
    B-->>N: 202 Accepted {workflow_id, run_id, status: "received"}
    N-->>F: Acknowledge request accepted

    Note over T,TW: ⚡ Image Workflow Execution
    T->>TW: Add 'ImageGenerationWorkflow' task to queue
    TW->>T: Poll for task
    TW-->>TW: Execute workflow logic

    Note over TW,FS: Setup Run Directory
    TW->>T: Schedule Activity 'setup_run_directory'
    T->>TW: Execute 'setup_run_directory'
    TW-->>FS: Create /data/shared/{run_id}
    TW-->>FS: Write manifest.json

    Note over TW,N: 🧩 Scene Prompt Generation
    TW->>T: Schedule Activity 'generate_image_scene_prompts'
    T->>TW: Execute 'generate_image_scene_prompts'
    TW->>N: POST Create Scenes webhook<br/>{script, language, image_style}
    N-->>TW: {prompts: [{image_prompt, video_prompt?}, ...]}
    TW-->>FS: Write scenes_response.json

    loop For each scene prompt in order
        Note over TW,C: 🎨 Generate ordered image
        TW->>T: Schedule Activity 'start_image_generation'
        T->>TW: Execute 'start_image_generation'
        TW->>C: Submit text-to-image job<br/>{image_prompt, workflow, dimensions, style}
        C-->>TW: prompt_id

        TW->>T: Schedule Activity 'poll_image_generation'
        T->>TW: Execute 'poll_image_generation'
        TW->>C: Poll job status until complete
        C-->>TW: image output hint

        Note over TW,FS: Persist sequential filename
        TW->>T: Schedule Activity 'persist_image_output'
        T->>TW: Execute 'persist_image_output'
        TW-->>FS: Save image_{index:03d}.png in /data/shared/{run_id}
        TW->>S: Upload image_{index:03d}.png<br/>to storage/{user_id}/{run_id}/
        S-->>TW: Upload confirmed
    end

    alt Workflow Success
        Note over TW,N: ✅ Send completion webhook
        TW->>T: Schedule Activity 'send_image_generation_webhook'
        T->>TW: Execute activity
        TW->>N: POST {IMAGE_GENERATION_N8N_WEBHOOK_URL}<br/>{workflow_id, run_id, user_id, status: "completed", image_files, storage_path}
        N->>F: Notify frontend with ordered image list
    else Workflow Failure
        Note over TW,N: ❌ Send failure webhook
        TW-->>TW: Workflow catches exception
        TW->>T: Schedule Activity 'send_image_generation_webhook'
        T->>TW: Execute activity
        TW->>N: POST {IMAGE_GENERATION_N8N_WEBHOOK_URL}<br/>{workflow_id, run_id, user_id, status: "failed", image_files, failure_reason}
        N->>F: Notify frontend of failure
    end

    Note over U: 👀 User receives async update through frontend
```

## API Endpoints Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/orchestrate/generate-images` | POST | Create new image generation job and return `workflow_id` + `run_id` immediately |
| `{IMAGE_GENERATION_N8N_WEBHOOK_URL}` | POST | N8N receives image-generation completion/failure notifications |

## Data Flow

### File System
- `/data/shared/{run_id}/` - Run working directory
- `manifest.json` - Initial request payload for the workflow run
- `scenes_response.json` - Full Create Scenes response persisted for later reuse
- `image_001.png`, `image_002.png`, ... - Ordered local image outputs

### Supabase Storage
- `storage/{user_id}/{run_id}/image_001.png`
- `storage/{user_id}/{run_id}/image_002.png`
- Images are uploaded in the same order as the generated scene prompts

## Processing Pipeline

1. **API initiation (`/orchestrate/generate-images`)**
   - Accepts `user_id`, `script`, `language`, and image-generation options.
   - Generates a deterministic 6-character hexadecimal `run_id` when one is not provided.
   - Starts `ImageGenerationWorkflow` and immediately returns `202 Accepted`.

2. **Prompt generation**
   - `generate_image_scene_prompts` calls the Create Scenes webhook.
   - The full response is saved to `scenes_response.json` for future video-clip generation stages.

3. **Ordered image generation**
   - For each scene prompt, the workflow submits image generation and polls until completion.
   - `persist_image_output` stores the final image locally with a deterministic sequential name.
   - The same file is uploaded to Supabase Storage under `storage/{user_id}/{run_id}/`.

4. **Async frontend notification**
   - On success, the workflow sends an ordered list of image filenames to N8N.
   - On failure, the workflow sends the failure reason and any images already persisted.

## Key Participants

- **Frontend** - Initiates the request and receives async updates from N8N.
- **N8N** - Entry and exit integration point for the frontend.
- **Backend API** - Starts the Temporal workflow.
- **Temporal Worker** - Runs the workflow and activities.
- **ComfyUI / RunPod** - Generates images from prompts.
- **File System** - Persists local artifacts under `/data/shared/{run_id}`.
- **Supabase Storage** - Stores ordered image files per user and run.
