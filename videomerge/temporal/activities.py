import asyncio
import json
import time
import base64
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
from temporalio import activity

from videomerge.exceptions import NonRetryableError

from videomerge.config import (
    COMFYUI_POLL_INTERVAL_SECONDS,
    COMFYUI_TIMEOUT_SECONDS,
    COMFY_ORG_API_KEY,
    DATA_SHARED_BASE,
    IMAGE_JOB_TIMEOUT_SECONDS,
    IMAGE_POLL_INTERVAL_SECONDS,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    N8N_PROMPTS_WEBHOOK_URL,
    N8N_VOICEOVER_WEBHOOK_URL,
    N8N_WEBHOOK_TIMEOUT_SECONDS,
    RUNPOD_UPSCALE_HTTP_TIMEOUT_SECONDS,
    RUNPOD_API_KEY,
    RUNPOD_BASE_URL,
    RUNPOD_VIDEO_INSTANCE_ID,
    UPSCALE_BATCH_SIZE,
    UPSCALE_JOB_TIMEOUT_SECONDS,
    UPSCALE_POLL_INTERVAL_SECONDS,
    UPSCALE_QUEUE_TIMEOUT_SECONDS,
    UPSCALE_RUNNING_TIMEOUT_SECONDS,
    VIDEO_JOB_TIMEOUT_SECONDS,
    VIDEO_POLL_INTERVAL_SECONDS,
    VIDEO_COMPLETED_N8N_WEBHOOK_URL,
    WORKFLOW_I2V_PATH,
)
from videomerge.services.media import get_duration
from videomerge.services.metrics import (
    voiceover_length_seconds,
    get_length_bucket,
    total_images_generation_seconds,
    total_videos_generation_seconds,
    stitch_seconds,
    subtitles_seconds,
    videos_completed_total,
    jobs_started_total,
    jobs_completed_total,
    jobs_failed_total,
    job_total_seconds,
    worker_active,
)
from videomerge.services.comfyui_client import get_image_client, get_video_client, refresh_comfyui_client, ClientType, get_comfyui_client
from videomerge.services.comfyui_wrapper import (
    submit_text_to_image,
    poll_until_complete,
    download_outputs,
    fetch_output_bytes,
    upload_image_to_input,
    submit_image_to_video,
)
from videomerge.services.stitcher import concat_videos_with_voiceover, generate_and_burn_subtitles
from videomerge.services.voiceover import synthesize_voice
from videomerge.services.webhook_manager import webhook_manager
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class ActivityTimeoutError(Exception):
    """Raised when an activity fails due to an upstream HTTP timeout."""

    pass


_metrics_lock = asyncio.Lock()
_active_runs: set[str] = set()
_job_start_times: Dict[str, float] = {}


async def _run_in_thread_with_heartbeats(
    fn,
    *args,
    heartbeat_interval_s: float = 30.0,
    **kwargs,
) -> Any:
    """Run a blocking function in a thread while periodically heartbeating.

    This is used for long-running polling loops implemented in synchronous client
    code (e.g., RunPod/ComfyUI polling) so the activity doesn't appear stuck.
    """

    async def _heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(heartbeat_interval_s)
            _safe_heartbeat()

    _safe_heartbeat()
    task = asyncio.create_task(_heartbeat_loop())
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _safe_heartbeat() -> None:
    """Call Temporal activity heartbeat if running in an activity context."""

    try:
        activity.heartbeat()
    except Exception:
        return


def _load_length_bucket(run_id: str) -> Optional[str]:
    """Load cached length_bucket for a given run, if available."""
    try:
        bucket_path = DATA_SHARED_BASE / run_id / "length_bucket.txt"
        if bucket_path.exists():
            value = bucket_path.read_text(encoding="utf-8").strip()
            return value or None
    except Exception as e:
        logger.warning(f"Failed to load length_bucket for run_id={run_id}: {e}")
    return None


@activity.defn
async def setup_run_directory(run_id: str, payload: Dict[str, Any]) -> str:
    """Creates the run directory and saves the manifest."""
    activity.heartbeat()
    start_ts = time.time()
    first_start = False
    async with _metrics_lock:
        if run_id not in _active_runs:
            _active_runs.add(run_id)
            _job_start_times[run_id] = start_ts
            worker_active.set(len(_active_runs))
            first_start = True
    if first_start:
        jobs_started_total.inc()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    try:
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Manifest saved for run_id={run_id}")
    except Exception as e:
        logger.warning(f"Failed to write manifest for run_id={run_id}: {e}")
    return str(run_dir)


@activity.defn
async def generate_voiceover(run_id: str, script: str, language: str, elevenlabs_voice_id: str) -> str:
    """Trigger voiceover generation through N8N and record duration metrics."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    audio_path = run_dir / "voiceover.mp3"

    url = N8N_VOICEOVER_WEBHOOK_URL
    if not url:
        raise RuntimeError("N8N_VOICEOVER_WEBHOOK_URL environment variable is not set")
    payload: Dict[str, Any] = {
        "script": script,
        "runId": run_id,
        "elevenlabs_voice_id": elevenlabs_voice_id,
        "language": language,
    }

    logger.info(f"[voiceover] Calling N8N webhook for run_id={run_id}")

    async with httpx.AsyncClient(timeout=float(N8N_WEBHOOK_TIMEOUT_SECONDS)) as client:
        response = await client.post(url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                error_detail = response.json()
                raise RuntimeError(f"N8N voiceover webhook failed with status {response.status_code}: {error_detail}") from exc
            except Exception:
                raise RuntimeError(f"N8N voiceover webhook failed with status {response.status_code}: {response.text}") from exc
        data = response.json()

    audio_duration_raw = data.get("audio_duration")
    duration: Optional[float] = None
    if audio_duration_raw is not None:
        try:
            duration = float(audio_duration_raw)
        except (TypeError, ValueError):
            logger.warning(
                f"[voiceover] Invalid audio_duration '{audio_duration_raw}' for run_id={run_id}."
            )

    metadata_path = run_dir / "voiceover_metadata.json"
    try:
        metadata_payload = {"audio_duration": duration} if duration is not None else {}
        metadata_path.write_text(
            json.dumps(metadata_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[voiceover] Saved audio metadata for run_id={run_id}: {metadata_payload}")
    except Exception as exc:
        logger.warning(f"[voiceover] Failed to write metadata for run_id={run_id}: {exc}")

    if duration is not None:
        length_bucket = get_length_bucket(duration)
        voiceover_length_seconds.labels(length_bucket=length_bucket).observe(duration)

        try:
            bucket_path = run_dir / "length_bucket.txt"
            bucket_path.write_text(length_bucket, encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[voiceover] Failed to write length_bucket for run_id={run_id}: {exc}")

    logger.info(f"[voiceover] Voiceover generation triggered successfully for run_id={run_id}")
    return str(audio_path)


@activity.defn
async def generate_scene_prompts(run_id: str, script: str, image_style: str | None = None) -> List[Dict[str, Any]]:
    """Generate scene prompts based on the synthesized voiceover duration."""
    _safe_heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    metadata_path = run_dir / "voiceover_metadata.json"

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"voiceover_metadata.json not found for run_id={run_id}; cannot generate prompts"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid voiceover metadata for run_id={run_id}: {exc}") from exc

    audio_duration = metadata.get("audio_duration")
    if audio_duration is None:
        raise RuntimeError(f"audio_duration missing in voiceover metadata for run_id={run_id}")

    from videomerge.config import VIDEO_SPEED_FACTOR
    # N8N uses audio_duration to decide how many clips to generate.
    # Scale by VIDEO_SPEED_FACTOR so enough source material is produced to
    # cover the full voiceover after the video stream is sped up.
    adjusted_audio_duration = float(audio_duration) * max(float(VIDEO_SPEED_FACTOR), 1.0)

    url = N8N_PROMPTS_WEBHOOK_URL
    if not url:
        raise RuntimeError("N8N_PROMPTS_WEBHOOK_URL environment variable is not set")
    payload: Dict[str, Any] = {
        "script": script,
        "audio_duration": adjusted_audio_duration,
        "image_style": image_style,
    }

    logger.info(f"[prompts] Calling N8N prompts webhook for run_id={run_id}")

    try:
        async with httpx.AsyncClient(timeout=float(N8N_WEBHOOK_TIMEOUT_SECONDS)) as client:
            response = await client.post(url, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    error_detail = response.json()
                    raise RuntimeError(f"N8N prompts webhook failed with status {response.status_code}: {error_detail}") from exc
                except Exception:
                    raise RuntimeError(f"N8N prompts webhook failed with status {response.status_code}: {response.text}") from exc
            data = response.json()
    except httpx.TimeoutException as exc:
        raise ActivityTimeoutError(
            f"N8N prompts webhook timed out after {N8N_WEBHOOK_TIMEOUT_SECONDS}s for run_id={run_id}"
        ) from exc

    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise RuntimeError(f"Prompts webhook returned invalid payload for run_id={run_id}: {data}")

    prompts_path = run_dir / "scene_prompts.json"
    try:
        prompts_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[prompts] Saved scene prompts for run_id={run_id} to {prompts_path}")
    except Exception as exc:
        logger.warning(f"[prompts] Failed to write scene prompts for run_id={run_id}: {exc}")

    return prompts


@activity.defn
async def generate_image(
    run_id: str,
    prompt_text: str,
    workflow_path: str,
    index: int,
    image_width: int | None = None,
    image_height: int | None = None,
    comfyui_workflow_name: str | None = None,
    image_style: str | None = None,
) -> str:
    """Generates a single image from a text prompt."""
    activity.heartbeat()
    logger.info(f"Generating image for prompt index {index}")

    # Determine length bucket for this run (used for aggregated GPU timing)
    length_bucket = _load_length_bucket(run_id)

    # Convert string path to Path object
    workflow_path = Path(workflow_path)

    # Force refresh the client to get latest configuration
    client = get_comfyui_client(ClientType.IMAGE, force_refresh=True)

    start_time = time.time()
    width = int(image_width) if image_width is not None else int(IMAGE_WIDTH)
    height = int(image_height) if image_height is not None else int(IMAGE_HEIGHT)
    prompt_id = await asyncio.to_thread(
        client.submit_text_to_image,
        prompt_text,
        template_path=workflow_path,
        comfyui_workflow_name=comfyui_workflow_name,
        image_width=width,
        image_height=height,
        image_style=image_style,
    )
    filenames = await _run_in_thread_with_heartbeats(
        client.poll_until_complete,
        prompt_id,
        timeout_s=int(IMAGE_JOB_TIMEOUT_SECONDS),
        poll_interval_s=float(IMAGE_POLL_INTERVAL_SECONDS),
        heartbeat_interval_s=30.0,
    )
    duration = time.time() - start_time

    if length_bucket is not None:
        total_images_generation_seconds.labels(length_bucket=length_bucket).observe(duration)

    if not filenames:
        raise RuntimeError(f"Image generation failed for prompt index {index}: No output files.")
    return filenames[0]


@activity.defn
async def upload_image_for_video_generation(image_hint: str) -> str:
    """Process image for video generation.
    
    For RunPod: Returns the local file path. The client will handle reading and converting to base64.
    For Local: Uploads the image to ComfyUI input directory.
    
    Args:
        image_hint: Either base64 image data, data URL, or local file path.
    
    Returns:
        For RunPod: Local file path or base64 data URL
        For Local: Uploaded filename in ComfyUI
    """
    activity.heartbeat()
    
    from videomerge.config import RUN_ENV
    
    # Check if this is already a RunPod base64 image data URL
    if image_hint.startswith("data:image/"):
        logger.info(f"[RunPod] Passing through base64 image data for video generation: {image_hint[:50]}...")
        return image_hint
        
    if RUN_ENV == "runpod":
        logger.info(f"[RunPod] Returning local file path for video generation client to read later: {image_hint}")
        return image_hint
        
    # Local environment
    client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)

    if image_hint.startswith("/data/shared/") or "\\" in image_hint or "/" in image_hint:
        # This is a local file path from poll_image_generation
        logger.info(f"[Local] Reading image file for video generation: {image_hint}")
        
        # Read the file directly
        with open(image_hint, "rb") as f:
            content = f.read()
        filename = Path(image_hint).name
        
        uploaded_filename = await asyncio.to_thread(
            client.upload_image_to_input, filename, content, overwrite=True
        )
        logger.info(f"[Local] Uploaded image {image_hint} as {uploaded_filename}")
        return uploaded_filename
    else:
        # For local development, upload the image to ComfyUI
        logger.info(f"[Local] Fetching and uploading image {image_hint} to ComfyUI input directory.")
        
        filename, content = await asyncio.to_thread(client.fetch_output_bytes, image_hint)
        uploaded_filename = await asyncio.to_thread(
            client.upload_image_to_input, filename, content, overwrite=True
        )
        logger.info(f"[Local] Uploaded image {image_hint} as {uploaded_filename}")
        return uploaded_filename


@activity.defn
async def generate_video_from_image(run_id: str, video_prompt: str, image_input: str, index: int) -> List[str]:
    """Generates a video clip from an image and a video prompt."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    logger.info(f"Generating video for prompt index {index}")

    length_bucket = _load_length_bucket(run_id)

    # Force refresh the client to get latest configuration
    client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)

    start_time = time.time()
    prompt_id = await asyncio.to_thread(
        client.submit_image_to_video,
        video_prompt,
        image_input,
        template_path=WORKFLOW_I2V_PATH,
        run_id=run_id,
    )
    video_hints = await _run_in_thread_with_heartbeats(
        client.poll_until_complete,
        prompt_id,
        timeout_s=int(VIDEO_JOB_TIMEOUT_SECONDS),
        poll_interval_s=float(VIDEO_POLL_INTERVAL_SECONDS),
        heartbeat_interval_s=30.0,
    )
    saved_files = await asyncio.to_thread(client.download_outputs, video_hints, run_dir)
    duration = time.time() - start_time

    # Rename files to sequential prefixed names
    renamed_files = []
    for p in saved_files:
        original_name = p.name
        if original_name.startswith("000_"):
            uuid_part = original_name[4:]  # remove "000_"
            new_name = f"{index:03d}_{uuid_part}"
            new_path = p.parent / new_name
            p.rename(new_path)
            renamed_files.append(new_path)
        else:
            renamed_files.append(p)

    if length_bucket is not None:
        total_videos_generation_seconds.labels(length_bucket=length_bucket).observe(duration)

    logger.info(f"Video generated for prompt index {index}: {renamed_files}")
    return [str(p) for p in renamed_files]


@activity.defn
async def start_image_generation(
    run_id: str,
    prompt_text: str,
    workflow_path: str,
    index: int,
    image_width: int | None = None,
    image_height: int | None = None,
    comfyui_workflow_name: str | None = None,
    image_style: str | None = None,
) -> str:
    """Submit an image generation job and return the provider job id."""

    activity.heartbeat()
    logger.info(f"Submitting image generation for prompt index {index}")

    workflow_path_obj = Path(workflow_path)
    client = get_comfyui_client(ClientType.IMAGE, force_refresh=True)

    width = int(image_width) if image_width is not None else int(IMAGE_WIDTH)
    height = int(image_height) if image_height is not None else int(IMAGE_HEIGHT)
    prompt_id = await asyncio.to_thread(
        client.submit_text_to_image,
        prompt_text,
        template_path=workflow_path_obj,
        comfyui_workflow_name=comfyui_workflow_name,
        image_width=width,
        image_height=height,
        image_style=image_style,
    )
    return prompt_id


@activity.defn
async def poll_image_generation(prompt_id: str, run_id: str, index: int) -> str:
    """Poll for image completion, save to disk, and return the output filename."""

    activity.heartbeat()
    logger.info(f"Polling image generation for prompt index {index}")

    client = get_comfyui_client(ClientType.IMAGE, force_refresh=True)
    filenames = await _run_in_thread_with_heartbeats(
        client.poll_until_complete,
        prompt_id,
        timeout_s=int(IMAGE_JOB_TIMEOUT_SECONDS),
        poll_interval_s=float(IMAGE_POLL_INTERVAL_SECONDS),
        heartbeat_interval_s=30.0,
    )
    if not filenames:
        raise RuntimeError(f"Image generation failed for prompt index {index}: No output files.")

    # Handle the first output file
    first_hint = filenames[0]

    # If it's a data URL (RunPod), save to disk to avoid Temporal payload size limit
    if first_hint.startswith("data:"):
        logger.info(f"[image] Saving base64 image data to disk for prompt index {index}")
        run_dir = DATA_SHARED_BASE / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        filename, content = await asyncio.to_thread(client.fetch_output_bytes, first_hint)
        image_path = run_dir / filename
        image_path.write_bytes(content)

        logger.info(f"[image] Saved image to {image_path}")
        return str(image_path)
    else:
        # For local ComfyUI, the file is already saved, return the path
        return first_hint


@activity.defn
async def start_video_generation(run_id: str, video_prompt: str, image_input: str, index: int, video_width: int, video_height: int) -> str:
    """Submit a video generation job and return the provider job id."""

    activity.heartbeat()
    logger.info(f"Submitting video generation for prompt index {index}")

    client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)
    prompt_id = await asyncio.to_thread(
        client.submit_image_to_video,
        video_prompt,
        image_input,
        template_path=WORKFLOW_I2V_PATH,
        run_id=run_id,
        video_width=video_width,
        video_height=video_height,
    )
    return prompt_id


@activity.defn
async def poll_video_generation(prompt_id: str, run_id: str, index: int) -> List[str]:
    """Poll for video completion, download outputs, and return saved file paths."""

    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    logger.info(f"Polling video generation for prompt index {index}")

    client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)
    video_hints = await _run_in_thread_with_heartbeats(
        client.poll_until_complete,
        prompt_id,
        timeout_s=int(VIDEO_JOB_TIMEOUT_SECONDS),
        poll_interval_s=float(VIDEO_POLL_INTERVAL_SECONDS),
        heartbeat_interval_s=30.0,
    )
    saved_files = await asyncio.to_thread(client.download_outputs, video_hints, run_dir)

    renamed_files = []
    for p in saved_files:
        original_name = p.name
        if original_name.startswith("000_"):
            uuid_part = original_name[4:]
            new_name = f"{index:03d}_{uuid_part}"
            new_path = p.parent / new_name
            p.rename(new_path)
            renamed_files.append(new_path)
        else:
            renamed_files.append(p)

    return [str(p) for p in renamed_files]


@activity.defn
async def stitch_videos(run_id: str, video_paths: List[str], voiceover_path: str) -> str:
    """Stitches video clips together with a voiceover."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    output_path = run_dir / "stitched_output.mp4"
    logger.info(f"Stitching {len(video_paths)} videos for run_id={run_id}")

    length_bucket = _load_length_bucket(run_id)

    from videomerge.config import VIDEO_SPEED_FACTOR

    start_time = time.time()
    await asyncio.to_thread(
        concat_videos_with_voiceover,
        [Path(p) for p in video_paths],
        Path(voiceover_path),
        output_path,
        video_speed_factor=VIDEO_SPEED_FACTOR,
    )
    duration = time.time() - start_time

    if length_bucket is not None:
        stitch_seconds.labels(length_bucket=length_bucket).observe(duration)

    logger.info(f"Stitching complete for run_id={run_id}")
    return str(output_path)


@activity.defn
async def burn_subtitles_into_video(run_id: str, stitched_video_path: str, language: str, voiceover_path: str) -> str:
    """Generates and burns subtitles into the final video."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    final_path = run_dir / "final_video.mp4"
    logger.info(f"Generating and burning subtitles for run_id={run_id}")

    length_bucket = _load_length_bucket(run_id)

    start_time = time.time()
    await asyncio.to_thread(
        generate_and_burn_subtitles,
        Path(stitched_video_path),
        final_path,
        language=language,
        audio_hint=Path(voiceover_path),
    )
    duration = time.time() - start_time

    if length_bucket is not None:
        subtitles_seconds.labels(length_bucket=length_bucket).observe(duration)

    logger.info(f"Subtitles burned successfully for run_id={run_id}")
    return str(final_path)


@activity.defn
async def send_completion_webhook(
    run_id: str,
    status: str,
    final_video_path: str,
    workflow_id: Optional[str] = None,
    run_dir: Optional[str] = None,
    video_files: Optional[List[str]] = None,
    image_files: Optional[List[str]] = None,
    voiceover_path: Optional[str] = None,
    failure_reason: Optional[str] = None,
):
    """Sends a webhook notification to N8N upon completion."""
    activity.heartbeat()

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "status": status,
    }

    if workflow_id:
        payload["workflow_id"] = workflow_id
    if run_dir:
        payload["output_dir"] = run_dir
    if final_video_path:
        payload["final_video_path"] = final_video_path
    if video_files:
        payload["video_files"] = video_files
    if image_files:
        payload["image_files"] = image_files
    if voiceover_path:
        payload["voiceover_path"] = voiceover_path

    event_type = "job_completed" if status == "completed" else "job_failed"
    logger.info(f"Sending '{event_type}' webhook for run_id={run_id}")
    await webhook_manager.send_webhook(VIDEO_COMPLETED_N8N_WEBHOOK_URL, payload, event_type)

    # Record a completed video for this length bucket when the job finishes
    if status == "completed":
        length_bucket = _load_length_bucket(run_id)
        if length_bucket is not None:
            videos_completed_total.labels(length_bucket=length_bucket).inc()
        jobs_completed_total.inc()
    else:
        reason_label = failure_reason or "unknown"
        jobs_failed_total.labels(reason=reason_label).inc()

    duration_observed = False
    async with _metrics_lock:
        start_ts = _job_start_times.pop(run_id, None)
        if run_id in _active_runs:
            _active_runs.remove(run_id)
        worker_active.set(len(_active_runs))
        if start_ts is not None:
            duration = max(0.0, time.time() - start_ts)
            job_total_seconds.observe(duration)
            duration_observed = True

    if not duration_observed:
        logger.debug(f"[metrics] No start timestamp recorded for run_id={run_id}; skipping job_total_seconds")


@activity.defn
async def download_video(video_url: str, video_id: str) -> str:
    """Downloads a video from the given URL and saves it to the run directory."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / video_id
    run_dir.mkdir(parents=True, exist_ok=True)
    video_path = run_dir / "input_video.mp4"

    logger.info(f"[download] Downloading video from {video_url} for video_id={video_id}")

    async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minute timeout
        response = await client.get(video_url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Failed to download video from {video_url} with status {response.status_code}: {response.text[:500]}") from exc
        with open(video_path, "wb") as f:
            f.write(response.content)

    logger.info(f"[download] Video downloaded successfully to {video_path}")
    return str(video_path)


@activity.defn
async def start_video_upscaling(video_id: str, video_path: str, target_resolution: str) -> str:
    """Prepares video for upscaling, converts to base64, gets dimensions, and calls Runpod."""
    activity.heartbeat()
    
    # Map target_resolution to output_resolution
    if target_resolution == "720p":
        output_resolution = 1280
    elif target_resolution == "1080p":
        output_resolution = 1920
    else:
        raise ValueError(f"Unsupported target_resolution: {target_resolution}")

    # Get video dimensions using ffmpeg
    probe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", 
        "stream=width,height", "-of", "csv=s=x:p=0", video_path
    ]
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        width, height = map(int, result.stdout.strip().split('x'))
        logger.info(f"[upscale] Video dimensions: {width}x{height}")
    except subprocess.CalledProcessError as e:
        logger.error(f"[upscale] Failed to get video dimensions: {e}")
        raise RuntimeError(f"Failed to get video dimensions: {e}")

    # Get video frame count for batch_size calculation
    frame_count: int | None = None
    batch_size: int

    frame_probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_read_frames",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        video_path,
    ]
    try:
        result = subprocess.run(frame_probe_cmd, capture_output=True, text=True, check=True)
        raw = result.stdout.strip()
        if raw.isdigit():
            frame_count = int(raw)
    except subprocess.CalledProcessError as e:
        logger.warning(f"[upscale] Failed to get video frame count via nb_read_frames: {e}")

    if frame_count is None:
        frame_probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            video_path,
        ]
        try:
            result = subprocess.run(frame_probe_cmd, capture_output=True, text=True, check=True)
            raw = result.stdout.strip()
            if raw.isdigit():
                frame_count = int(raw)
        except subprocess.CalledProcessError as e:
            logger.warning(f"[upscale] Failed to get video frame count via nb_frames: {e}")

    if frame_count is None:
        duration_seconds: float | None = None
        fps: float | None = None

        duration_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            video_path,
        ]
        try:
            result = subprocess.run(duration_cmd, capture_output=True, text=True, check=True)
            raw = result.stdout.strip()
            if raw:
                duration_seconds = float(raw)
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.warning(f"[upscale] Failed to get video duration for frame estimation: {e}")

        fps_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            video_path,
        ]
        try:
            result = subprocess.run(fps_cmd, capture_output=True, text=True, check=True)
            raw = result.stdout.strip()
            if raw and raw != "0/0":
                if "/" in raw:
                    num_str, den_str = raw.split("/", 1)
                    num = float(num_str)
                    den = float(den_str)
                    if den != 0:
                        fps = num / den
                else:
                    fps = float(raw)
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.warning(f"[upscale] Failed to get video fps for frame estimation: {e}")

        if duration_seconds is None or fps is None:
            raise RuntimeError(
                f"Failed to determine video frame count for upscaling (nb_read_frames/nb_frames unavailable; duration={duration_seconds}, fps={fps})"
            )

        frame_count = max(1, int(round(duration_seconds * fps)))

    batch_size = UPSCALE_BATCH_SIZE
    logger.info(f"[upscale] Video frame count: {frame_count}, using batch_size: {batch_size}")

    # Convert video to base64
    with open(video_path, "rb") as f:
        video_data = f.read()
    video_b64 = base64.b64encode(video_data).decode('utf-8')
    video_data_url = f"data:video/mp4;base64,{video_b64}"

    # Call Runpod API
    url = f"{RUNPOD_BASE_URL}/v2/{RUNPOD_VIDEO_INSTANCE_ID}/run"
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "video": video_data_url,
            "width": width,
            "height": height,
            "output_resolution": output_resolution,
            "comfyui_workflow_name": "seedvr2_video_upscale",
            "comfy_org_api_key": COMFY_ORG_API_KEY,
            "batch_size": batch_size,
        }
    }

    logger.info(f"[upscale] Calling Runpod upscaling API for video_id={video_id}")

    async with httpx.AsyncClient(timeout=float(RUNPOD_UPSCALE_HTTP_TIMEOUT_SECONDS)) as client:
        response = await client.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                error_detail = response.json()
                raise RuntimeError(f"ComfyUI job submission failed with status {response.status_code}: {error_detail}") from exc
            except Exception:
                raise RuntimeError(f"ComfyUI job submission failed with status {response.status_code}: {response.text}") from exc
        data = response.json()
        job_id = data.get("id")
        if not job_id:
            raise RuntimeError(f"Runpod API did not return job_id: {data}")

    logger.info(f"[upscale] Runpod upscaling job started: job_id={job_id}")
    return job_id


@activity.defn
async def poll_upscale_status(job_id: str, run_id: str, video_id: str) -> str:
    """Polls Runpod for upscaling job completion, saves video to disk, and returns file path."""
    activity.heartbeat()

    status_url = f"{RUNPOD_BASE_URL}/v2/{RUNPOD_VIDEO_INSTANCE_ID}/status/{job_id}"
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }

    queue_budget = UPSCALE_QUEUE_TIMEOUT_SECONDS
    running_budget = UPSCALE_RUNNING_TIMEOUT_SECONDS

    start_time = time.time()
    queue_start_time: float | None = None
    running_start_time: float | None = None

    while time.time() - start_time < UPSCALE_JOB_TIMEOUT_SECONDS:
        activity.heartbeat()
        async with httpx.AsyncClient(timeout=float(RUNPOD_UPSCALE_HTTP_TIMEOUT_SECONDS)) as client:
            response = await client.get(status_url, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    error_detail = response.json()
                    raise RuntimeError(f"ComfyUI status check failed with status {response.status_code}: {error_detail}") from exc
                except Exception:
                    raise RuntimeError(f"ComfyUI status check failed with status {response.status_code}: {response.text}") from exc
            data = response.json()

        status = data.get("status", "").upper()
        logger.debug(f"[upscale] Runpod job status: {status}")

        if status == "COMPLETED":
            outputs = data.get("output", {}).get("output", [])
            videos = outputs.get("videos", [])
            if videos:
                video_data_b64 = videos[0].get("data")
                if video_data_b64:
                    logger.info(f"[upscale] Upscaling completed, saving to disk")
                    
                    # Save video directly to disk to avoid Temporal payload size limit
                    run_dir = DATA_SHARED_BASE / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)
                    
                    payload = _strip_base64_data_url(video_data_b64)
                    video_data = base64.b64decode(payload)
                    
                    upscaled_path = run_dir / f"{video_id}_upscaled.mp4"
                    with open(upscaled_path, "wb") as f:
                        f.write(video_data)
                    
                    logger.info(f"[upscale] Saved upscaled video to {upscaled_path}")
                    return str(upscaled_path)
            raise RuntimeError("Runpod job completed but no video output found")

        elif status in ("FAILED", "ERROR"):
            error_msg = data.get("error", "Unknown Runpod error")
            raise NonRetryableError(f"Runpod upscaling failed: {error_msg}")

        elif status in ("IN_QUEUE", "RUNNING", "IN_PROGRESS"):
            now = time.time()
            if status == "IN_QUEUE":
                queue_start_time = queue_start_time or now
                if queue_budget is not None and (now - queue_start_time) > queue_budget:
                    raise TimeoutError(
                        f"Timed out waiting in Runpod queue for upscaling job {job_id} "
                        f"after {int(now - queue_start_time)}s"
                    )
            else:
                running_start_time = running_start_time or now
                if running_budget is not None and (now - running_start_time) > running_budget:
                    raise TimeoutError(
                        f"Timed out waiting for Runpod upscaling job {job_id} to finish running "
                        f"after {int(now - running_start_time)}s"
                    )
            await asyncio.sleep(UPSCALE_POLL_INTERVAL_SECONDS)
            continue
        else:
            await asyncio.sleep(UPSCALE_POLL_INTERVAL_SECONDS)
            continue

    raise TimeoutError(f"Timed out waiting for Runpod upscaling job {job_id}")


@activity.defn
async def list_run_videos_for_upscale(run_id: str) -> List[str]:
    """List video clips (000_*.mp4) in the shared run directory for an upscale run."""

    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    files = sorted(run_dir.glob("[0-9][0-9][0-9]_*.mp4"), key=lambda p: p.name)
    return [str(p) for p in files]


@activity.defn
async def list_upscaled_videos(run_id: str) -> List[str]:
    """List upscaled video clips (*_upscaled.mp4) in the shared run directory."""

    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    files = sorted(run_dir.glob("*_upscaled.mp4"), key=lambda p: p.name)
    return [str(p) for p in files]


def _strip_base64_data_url(value: str) -> str:
    """Strip a data URL prefix (e.g. data:video/mp4;base64,...) if present."""

    if value.startswith("data:"):
        _prefix, _comma, rest = value.partition("base64,")
        if rest:
            return rest
    return value


@activity.defn
async def save_upscaled_video(run_id: str, video_id: str, upscaled_video_b64: str) -> str:
    """Persist an upscaled video (base64 or data URL) to the shared run directory."""

    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    payload = _strip_base64_data_url(upscaled_video_b64)
    video_data = base64.b64decode(payload)

    upscaled_path = run_dir / f"{video_id}_upscaled.mp4"
    with open(upscaled_path, "wb") as f:
        f.write(video_data)

    logger.info(f"Saved upscaled video to {upscaled_path}")
    return str(upscaled_path)


@activity.defn
async def encode_file_to_base64(file_path: str) -> str:
    """Read a file and return its base64-encoded contents."""

    logger.info(f"[encode_file_to_base64] STARTED - file_path={file_path}")
    activity.heartbeat()
    logger.info(f"[encode_file_to_base64] Heartbeat sent")
    
    file_path_obj = Path(file_path)
    logger.info(f"[encode_file_to_base64] Path object created: {file_path_obj}")
    
    # Verify file exists and is accessible
    logger.info(f"[encode_file_to_base64] Checking if file exists...")
    if not file_path_obj.exists():
        logger.error(f"[encode_file_to_base64] File not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")
    logger.info(f"[encode_file_to_base64] File exists confirmed")
    
    # Wait a moment to ensure file is fully written and closed by previous process
    logger.info(f"[encode_file_to_base64] Sleeping for 2 seconds...")
    await asyncio.sleep(2)
    logger.info(f"[encode_file_to_base64] Sleep completed")
    
    # Get file size for logging
    file_size = file_path_obj.stat().st_size
    logger.info(f"Encoding file to base64: {file_path} (size: {file_size} bytes)")
    
    # Read file in chunks to send heartbeats for large files
    chunk_size = 10 * 1024 * 1024  # 10MB chunks
    data = bytearray()
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    data.extend(chunk)
                    activity.heartbeat()
            break  # Success, exit retry loop
        except OSError as e:
            if attempt < max_retries - 1:
                logger.warning(f"OSError reading file (attempt {attempt + 1}/{max_retries}): {e}. Retrying...")
                await asyncio.sleep(2)
            else:
                logger.error(f"Failed to read file after {max_retries} attempts: {e}")
                raise
    
    activity.heartbeat()
    logger.info(f"Encoding {len(data)} bytes to base64")
    encoded = base64.b64encode(data).decode("utf-8")
    activity.heartbeat()
    logger.info(f"Base64 encoding complete, result length: {len(encoded)}")
    
    return encoded


@activity.defn
async def send_upscale_completion_webhook(
    run_id: str,
    final_video_path: str,
    status: str,
    workflow_id: Optional[str] = None,
    user_id: Optional[str] = None,
    failure_reason: Optional[str] = None,
):
    """Sends a webhook notification to N8N upon upscaling completion."""
    activity.heartbeat()

    run_dir = DATA_SHARED_BASE / run_id
    
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "output_dir": str(run_dir),
    }

    if workflow_id:
        payload["workflow_id"] = workflow_id
    if user_id:
        payload["user_id"] = user_id
    
    if status == "completed" and final_video_path:
        payload["final_video_path"] = final_video_path
        
        # Include upscaled video files
        upscaled_files = sorted(run_dir.glob("*_upscaled.mp4"), key=lambda p: p.name)
        if upscaled_files:
            payload["video_files"] = [str(p) for p in upscaled_files]
        
        # Include voiceover path if exists
        voiceover_path = run_dir / "voiceover.mp3"
        if voiceover_path.exists():
            payload["voiceover_path"] = str(voiceover_path)
    
    if failure_reason:
        payload["failure_reason"] = failure_reason

    event_type = "job_completed" if status == "completed" else "job_failed"
    logger.info(f"Sending '{event_type}' webhook for run_id={run_id}")
    await webhook_manager.send_webhook(VIDEO_COMPLETED_N8N_WEBHOOK_URL, payload, event_type)
