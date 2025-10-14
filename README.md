# Video Audio Merger API

A FastAPI service that merges or stitches videos with a voiceover using ffmpeg.

- `POST /merge`: Merge a single video with a WAV audio file.
- `POST /stitch`: Stitch multiple video segments sequentially and overlay a voiceover MP3.
- `GET /health`: Simple health check.

## Requirements
- Docker (recommended)
- ffmpeg is installed inside the provided container image

## Run with Docker

### Build and run with docker-compose
```bash
# From the project directory
docker-compose up --build
```

This exposes the API at: http://localhost:8086

Note:
- The service listens inside the container on port 8000, mapped to host port 8086 via `docker-compose.yml`.
- If you need the container to access local/shared files, mount those paths as volumes in `docker-compose.yml` (see examples below).

### Example volume mounts for shared paths
```yaml
services:
  video-merger:
    build: .
    ports:
      - "8086:8000"
    volumes:
      - /mnt/shared:/mnt/shared:ro   # Linux host path example
      # - //server/share:/mnt/share:ro # Docker Desktop bind mount for SMB share (Windows/Mac)
```

Then pass paths like `/mnt/shared/result_0.mp4` in requests.

## Endpoints

### 1) POST `/merge`
Merge a single MP4 video with a WAV audio track. The audio is normalized to -14 LUFS (loudness) using ffmpeg's `loudnorm` filter. If audio is longer, it may be sped up to match the video. Output is MP4.

- Content-Type: multipart/form-data
- Fields:
  - `audio` (required): WAV audio file (content-type audio/wav)
  - `video` (optional): MP4 video file upload
  - `videoUrl` (optional): URL to an MP4

Exactly one of `video` or `videoUrl` must be provided.

Response:
- 200: MP4 video file as binary
- 4xx/5xx: JSON error

Example using uploaded video:
```bash
curl -X POST http://localhost:8086/merge \
  -F "audio=@/path/to/voice.wav;type=audio/wav" \
  -F "video=@/path/to/input.mp4;type=video/mp4" \
  -o merged.mp4
```

Example using video URL:
```bash
curl -X POST http://localhost:8086/merge \
  -F "audio=@/path/to/voice.wav;type=audio/wav" \
  -F "videoUrl=https://example.com/input.mp4" \
  -o merged.mp4
```

### 2) POST `/stitch`
Stitch an ordered list of video files together and overlay a single MP3 voiceover on the result. The voiceover is normalized to -14 LUFS using ffmpeg's `loudnorm` filter, padded with silence if shorter, and trimmed if longer than the stitched video.

- Content-Type: application/json
- Body schema:
```json
{
  "voiceover": "<url-or-path-to-voiceover.mp3>",
  "videos": ["<url-or-path-to-video0.mp4>", "<url-or-path-to-video1.mp4>", "..."]
}
```

Notes:
- The order of the `videos` array is the stitch order.
- URLs are downloaded; non-URLs are treated as file paths inside the container.
- For local/shared files, ensure the paths are mounted and accessible inside the container.

Response:
- 200: MP4 video file as binary
- 4xx/5xx: JSON error

Example with local (mounted) paths:
```bash
curl -X POST http://localhost:8086/stitch \
  -H "Content-Type: application/json" \
  -d '{
    "voiceover": "/mnt/shared/voiceover.mp3",
    "videos": [
      "/mnt/shared/result_0.mp4",
      "/mnt/shared/result_1.mp4",
      "/mnt/shared/result_2.mp4"
    ]
  }' \
  -o stitched.mp4
```

Example mixing URL and path:
```bash
curl -X POST http://localhost:8086/stitch \
  -H "Content-Type: application/json" \
  -d '{
    "voiceover": "https://example.com/voiceover.mp3",
    "videos": [
      "https://example.com/result_0.mp4",
      "/mnt/shared/result_1.mp4"
    ]
  }' \
  -o stitched.mp4
```

### 3) GET `/health`
Returns service health.

```bash
curl http://localhost:8086/health
```

## How path handling works
- URLs: Strings beginning with `http://` or `https://` are downloaded.
- Paths: Anything else is treated as a filesystem path inside the container. If you pass Windows or Linux paths, ensure that the corresponding location is mounted into the container and use the container-visible path in requests (e.g., `/mnt/share/...`).

## ffmpeg concat compatibility
The `concat` demuxer used by `/stitch` works best when input videos share the same codec, pixel format, resolution, and frame rate. If your sources differ, consider pre-normalizing them or let us add a step to normalize each input before concatenation (re-encode to a common format like H.264 yuv420p, consistent FPS and resolution).

## Audio loudness normalization
- Both `/merge` and `/stitch` apply a one-pass `loudnorm` with parameters targeting broadcast-friendly loudness:
  - `I=-14` (integrated loudness, LUFS)
  - `TP=-1.5` (true peak limit)
  - `LRA=7` (loudness range)
- For most voiceover use-cases, one-pass `loudnorm` is sufficient. If you need stricter compliance, we can implement a two-pass `loudnorm` (analyze then apply measured parameters).

## ComfyUI workflows selection (environment-aware)

This service dynamically selects ComfyUI workflow JSONs based on the `RUN_ENV` environment variable. You can still override the paths explicitly if needed.

- When `RUN_ENV=runpod` (as set in `docker-compose.runpod.yml`):
  - Text-to-Image default: `videomerge/comfyui-workflows/Wan2.2_Text-To-Image.json`
  - Image-to-Video default: `videomerge/comfyui-workflows/Wan2.2_5B_I2V_60FPS.json`

- When `RUN_ENV` is anything else (default is `local`):
  - Text-to-Image default: `videomerge/comfyui-workflows/qwen-image-fast-runpod.json`
  - Image-to-Video default: `videomerge/comfyui-workflows/I2V-Wan 2.2 Lightning.json`

You may override these defaults via environment variables:

```bash
WORKFLOW_IMAGE_PATH=/app/videomerge/comfyui-workflows/Wan2.2_Text-To-Image.json
WORKFLOW_I2V_PATH=/app/videomerge/comfyui-workflows/Wan2.2_5B_I2V_60FPS.json
```

Notes:
- In containers, the app path is `/app`, so the workflow files live under `/app/videomerge/comfyui-workflows/`.
- `docker-compose.runpod.yml` already sets `RUN_ENV=runpod` to activate the RunPod defaults.

## Troubleshooting
- 400 errors for local paths: Verify the path exists inside the container and that your volume mounts are correct.
- 400 errors for URLs: Ensure the URL is reachable and returns the expected content.
- Empty output: Check ffmpeg logs in the server output for details.
- Performance: Adjust `-preset` and `-crf` in the ffmpeg command to balance speed/quality.

## docker-compose healthcheck note
The service listens on port 8000 inside the container. If you configure a container-internal healthcheck, it should target `http://localhost:8000/health`. External checks (from the host) should target `http://localhost:8086/health`.

Current `docker-compose.yml` example maps 8086->8000. If the healthcheck runs inside the container, set:
```yaml
test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
```
If you run the healthcheck from outside (host), use 8086.

## License
MIT (or your preferred license)

# Orchestration API Endpoint: /orchestrate/start

The primary entry point for the video generation service is the `POST /orchestrate/start` endpoint. It is designed to be called by an external system (like n8n) to initiate a video generation job.

### Description

This endpoint accepts a JSON payload with all the necessary information to create a video. It validates the request, creates a unique run directory, and enqueues a job for a background worker to process. It returns immediately with a `job_id`.

### Request Body

```json
{
  "script": "The text for the voiceover.",
  "prompts": [
    {
      "image_prompt": "A prompt for the first image.",
      "video_prompt": "A prompt for the video generation."
    },
    {
      "image_prompt": "A prompt for the second image.",
      "video_prompt": "A prompt for the video generation."
    }
  ],
  "image_style": "crayon_drawing",
  "run_id": "unique-run-identifier"
}
```
- **`script`**: The full text for the voiceover audio.
- **`prompts`**: A list of objects, each containing prompts for generating an image and its corresponding video segment.
- **`image_style`**: (Optional) A string specifying which ComfyUI workflow to use for text-to-image generation (e.g., `"crayon_drawing"`, `"default"`).
- **`run_id`**: A unique identifier for this specific job run.

### Workflow

1.  **Enqueue Job**: The endpoint creates a job and pushes it to a Redis queue.
2.  **Worker Processing**: A background worker picks up the job.
3.  **Voiceover**: The worker generates the voiceover from the script (or finds an existing one).
4.  **Image Generation**: For each item in the `prompts` array, the worker calls the ComfyUI service to generate an image using the specified `image_style` workflow.
5.  **Video Generation**: For each generated image, the worker calls the ComfyUI service again, this time using the appropriate image-to-video workflow (`local` or `runpod` version) to create a video segment.
6.  **Completion**: Once all video segments are created, the job is marked as complete, and a webhook is called to notify the originating system.
