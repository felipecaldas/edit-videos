import asyncio
import json
import time
import base64
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import aiohttp
import httpx
from temporalio import activity

from videomerge.exceptions import NonRetryableError

from videomerge.config import (
    COMFYUI_POLL_INTERVAL_SECONDS,
    COMFYUI_TIMEOUT_SECONDS,
    COMFY_ORG_API_KEY,
    DATA_SHARED_BASE,
    IMAGE_GENERATION_N8N_WEBHOOK_URL,
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
    TABARIO_VIDEO_COMPOSITOR_URL,
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
from videomerge.models import HandoffPayload
from videomerge.services.comfyui_client import get_image_client, get_video_client, refresh_comfyui_client, ClientType, get_comfyui_client
from videomerge.services.media_providers.registry import get_image_provider, get_video_provider
from videomerge.services.comfyui_wrapper import (
    submit_text_to_image,
    poll_until_complete,
    download_outputs,
    fetch_output_bytes,
    upload_image_to_input,
    submit_image_to_video,
)
from videomerge.services.stitcher import concat_videos_with_voiceover, generate_and_burn_subtitles
from videomerge.services.supabase_client import supabase_storage_client
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


async def _run_async_with_heartbeats(
    coro_fn,
    *args,
    heartbeat_interval_s: float = 30.0,
    **kwargs,
) -> Any:
    """Run an async function while periodically heartbeating.

    This is used for long-running async operations (e.g., Fal.ai polling)
    so the activity doesn't appear stuck.
    """

    async def _heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(heartbeat_interval_s)
            _safe_heartbeat()

    _safe_heartbeat()
    task = asyncio.create_task(_heartbeat_loop())
    try:
        return await coro_fn(*args, **kwargs)
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
async def generate_image_scene_prompts(
    run_id: str,
    script: str,
    language: str,
    image_style: str | None = None,
) -> List[Dict[str, Any]]:
    """Generate scene prompts for image-only orchestration and persist the full response."""
    _safe_heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    url = N8N_PROMPTS_WEBHOOK_URL
    if not url:
        raise RuntimeError("N8N_PROMPTS_WEBHOOK_URL environment variable is not set")

    payload: Dict[str, Any] = {
        "script": script,
        "language": language,
        "image_style": image_style,
    }

    logger.info(f"[image-prompts] Calling Create Scenes webhook for run_id={run_id}")

    try:
        async with httpx.AsyncClient(timeout=float(N8N_WEBHOOK_TIMEOUT_SECONDS)) as client:
            response = await client.post(url, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                try:
                    error_detail = response.json()
                    raise RuntimeError(
                        f"Create Scenes webhook failed with status {response.status_code}: {error_detail}"
                    ) from exc
                except Exception:
                    raise RuntimeError(
                        f"Create Scenes webhook failed with status {response.status_code}: {response.text}"
                    ) from exc
            data = response.json()
    except httpx.TimeoutException as exc:
        raise ActivityTimeoutError(
            f"Create Scenes webhook timed out after {N8N_WEBHOOK_TIMEOUT_SECONDS}s for run_id={run_id}"
        ) from exc

    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise RuntimeError(f"Create Scenes webhook returned invalid payload for run_id={run_id}: {data}")

    scenes_response_path = run_dir / "scenes_response.json"
    try:
        scenes_response_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[image-prompts] Saved scenes response for run_id={run_id} to {scenes_response_path}")
    except Exception as exc:
        logger.warning(f"[image-prompts] Failed to write scenes response for run_id={run_id}: {exc}")

    prompts_path = run_dir / "scene_prompts.json"
    try:
        prompts_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[image-prompts] Saved scene prompts for run_id={run_id} to {prompts_path}")
    except Exception as exc:
        logger.warning(f"[image-prompts] Failed to write scene prompts for run_id={run_id}: {exc}")

    return prompts


@activity.defn
async def persist_scene_prompts(run_id: str, prompts: List[Dict[str, Any]]) -> None:
    """Persist scene_prompts.json to the run directory.

    This activity is used when prompts were built from a V-CaaS brief
    (rather than fetched from the N8N webhook).

    Args:
        run_id: The run identifier.
        prompts: List of prompt dictionaries to write to scene_prompts.json.
    """
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    prompts_path = run_dir / "scene_prompts.json"
    try:
        prompts_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[scene-prompts] Persisted scene_prompts.json for run_id={run_id}")
    except Exception as exc:
        logger.error(f"[scene-prompts] Failed to write scene_prompts.json for run_id={run_id}: {exc}")
        raise


@activity.defn
async def load_storyboard_scene_inputs(run_id: str) -> List[Dict[str, Any]]:
    """Load ordered storyboard scene prompts and image paths from the shared run directory."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    prompts_path = run_dir / "scene_prompts.json"

    if not prompts_path.exists():
        message = f"scene_prompts.json not found for run_id={run_id} at {prompts_path}"
        logger.error(message)
        raise RuntimeError(message)

    try:
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        message = f"Invalid scene_prompts.json for run_id={run_id}: {exc}"
        logger.error(message)
        raise RuntimeError(message) from exc

    if not isinstance(prompts, list):
        message = f"scene_prompts.json must contain a list for run_id={run_id}"
        logger.error(message)
        raise RuntimeError(message)

    scene_inputs: List[Dict[str, Any]] = []
    for sequence_number, prompt in enumerate(prompts, start=1):
        if not isinstance(prompt, dict):
            message = f"Scene prompt at index={sequence_number - 1} is not an object for run_id={run_id}"
            logger.error(message)
            raise RuntimeError(message)

        video_prompt = prompt.get("video_prompt")
        if not video_prompt:
            message = f"Scene prompt at index={sequence_number - 1} is missing video_prompt for run_id={run_id}"
            logger.error(message)
            raise RuntimeError(message)

        image_path = run_dir / f"image_{sequence_number:03d}.png"
        if not image_path.exists():
            message = f"Storyboard image not found for run_id={run_id}: {image_path}"
            logger.error(message)
            raise RuntimeError(message)

        scene_inputs.append(
            {
                "index": sequence_number - 1,
                "image_path": str(image_path),
                "video_prompt": str(video_prompt),
            }
        )

    logger.info("Loaded %s storyboard scene inputs for run_id=%s", len(scene_inputs), run_id)
    return scene_inputs


@activity.defn
async def persist_image_output(run_id: str, user_id: str, image_hint: str, index: int, user_access_token: str) -> str:
    """Persist a generated image using a deterministic sequence filename and upload it to Supabase.
    
    Args:
        run_id: Unique run identifier
        user_id: User identifier for storage path
        image_hint: URL or path to the generated image
        index: Sequential index for filename
        user_access_token: Supabase user JWT for authenticated storage upload
    """
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    sequence_number = index + 1
    file_name = f"image_{sequence_number:03d}.png"
    destination_path = run_dir / file_name

    if image_hint.startswith("http://") or image_hint.startswith("https://"):
        async with aiohttp.ClientSession() as session:
            async with session.get(image_hint) as resp:
                resp.raise_for_status()
                content = await resp.read()
    else:
        client = get_comfyui_client()
        hint_path = Path(image_hint)
        if hint_path.exists():
            content = hint_path.read_bytes()
        else:
            _, content = await asyncio.to_thread(client.fetch_output_bytes, image_hint)

    destination_path.write_bytes(content)
    
    # Create a client instance with user JWT for authenticated upload
    from videomerge.services.supabase_client import SupabaseStorageClient
    authenticated_client = SupabaseStorageClient(user_jwt=user_access_token)
    
    await asyncio.to_thread(
        authenticated_client.upload_file,
        user_id,
        run_id,
        file_name,
        content,
        "image/png",
    )
    logger.info(f"[image] Persisted image {file_name} for run_id={run_id}")
    return file_name


@activity.defn
async def upload_final_video_output(
    run_id: str,
    user_id: str,
    final_video_path: str,
    user_access_token: str,
) -> str:
    """Upload the final stitched video to Supabase storage."""
    activity.heartbeat()
    final_path = Path(final_video_path)
    if not final_path.exists() or final_path.stat().st_size == 0:
        raise RuntimeError(f"Final video file does not exist or is empty: {final_video_path}")
    
    from videomerge.services.supabase_client import SupabaseStorageClient

    authenticated_client = SupabaseStorageClient(user_jwt=user_access_token)
    object_path = await asyncio.to_thread(
        authenticated_client.upload_local_file,
        user_id,
        run_id,
        final_path,
        "video/mp4",
    )
    logger.info("[video] Uploaded final video for run_id=%s to object_path=%s", run_id, object_path)
    return object_path


@activity.defn
async def send_image_generation_webhook(
    run_id: str,
    user_id: str,
    status: str,
    image_files: List[str],
    image_prompts: List[str],
    workflow_id: str,
    failure_reason: Optional[str] = None,
    video_idea_id: Optional[str] = None,
    platform: Optional[str] = None,
) -> None:
    """Send an image-generation completion or failure webhook.
    
    Args:
        run_id: The run identifier.
        user_id: The user identifier.
        status: Completion status ("completed" or "failed").
        image_files: List of generated image file paths.
        image_prompts: List of image prompts used.
        workflow_id: The Temporal workflow ID.
        failure_reason: Optional failure reason for failed status.
        video_idea_id: Optional Supabase video_ideas.id for V-CaaS correlation.
        platform: Optional platform identifier for V-CaaS correlation.
    """
    activity.heartbeat()

    if not workflow_id:
        raise RuntimeError(f"workflow_id is required for image generation webhook run_id={run_id}")

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "image_files": image_files,
        "image_prompts": image_prompts,
        "output_dir": str(DATA_SHARED_BASE / run_id),
    }

    if video_idea_id is not None:
        payload["video_idea_id"] = video_idea_id
    if platform is not None:
        payload["platform"] = platform

    if not IMAGE_GENERATION_N8N_WEBHOOK_URL:
        raise RuntimeError("IMAGE_GENERATION_N8N_WEBHOOK_URL environment variable is not set")

    event_type = "job_completed" if status == "completed" else "job_failed"
    logger.info(f"Sending '{event_type}' webhook for run_id={run_id}")
    await webhook_manager.send_webhook(IMAGE_GENERATION_N8N_WEBHOOK_URL, payload, event_type)

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

    if status == "completed":
        jobs_completed_total.inc()
    else:
        reason_label = failure_reason or "unknown"
        jobs_failed_total.labels(reason=reason_label).inc()

    if not duration_observed:
        logger.debug(f"[metrics] No start timestamp recorded for run_id={run_id}; skipping job_total_seconds")


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
async def start_video_generation(
    run_id: str,
    video_prompt: str,
    image_input: str,
    index: int,
    video_width: int,
    video_height: int,
    length: Optional[int] = None,
) -> str:
    """Submit a video generation job and return the provider job id.

    Args:
        run_id: The run identifier.
        video_prompt: The video generation prompt text.
        image_input: Path to the input image or base64 data URL.
        index: Scene index for file naming.
        video_width: Video width in pixels.
        video_height: Video height in pixels.
        length: Optional number of frames for video generation (default 81).
    """

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
        length=length,
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
    uploaded_video_object_path: Optional[str] = None,
    video_idea_id: Optional[str] = None,
    platform: Optional[str] = None,
):
    """Sends a webhook notification to N8N upon completion.
    
    Args:
        run_id: The run identifier.
        status: Completion status ("completed" or "failed").
        final_video_path: Path to the final video file.
        workflow_id: Optional Temporal workflow ID.
        run_dir: Optional output directory path.
        video_files: Optional list of video file paths.
        image_files: Optional list of image file paths.
        voiceover_path: Optional voiceover file path.
        failure_reason: Optional failure reason for failed status.
        uploaded_video_object_path: Optional Supabase storage path.
        video_idea_id: Optional Supabase video_ideas.id for V-CaaS correlation.
        platform: Optional platform identifier for V-CaaS correlation.
    """
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
    if uploaded_video_object_path:
        payload["uploaded_video_object_path"] = uploaded_video_object_path
    if video_idea_id is not None:
        payload["video_idea_id"] = video_idea_id
    if platform is not None:
        payload["platform"] = platform

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


@activity.defn
async def handoff_to_compositor(payload: HandoffPayload) -> str:
    """POST a HandoffPayload to tabario-video-compositor and return its compose_job_id.

    Retry policy (configured in the calling workflow):
    - Retryable: 5xx HTTP errors, network-level errors.
    - Non-retryable: 4xx HTTP errors (bad request — retrying will not help).

    Args:
        payload: The :class:`HandoffPayload` describing the clips and metadata
            to pass to the compositor.

    Returns:
        The ``compose_job_id`` string returned by the compositor.

    Raises:
        RuntimeError: If ``TABARIO_VIDEO_COMPOSITOR_URL`` is not configured.
        NonRetryableError: If the compositor responds with a 4xx status code.
        RuntimeError: On 5xx errors or unexpected response shapes (retryable).
    """
    activity.heartbeat()

    if not TABARIO_VIDEO_COMPOSITOR_URL:
        raise RuntimeError(
            "TABARIO_VIDEO_COMPOSITOR_URL environment variable is not set; "
            "cannot forward handoff payload to compositor."
        )

    url = f"{TABARIO_VIDEO_COMPOSITOR_URL.rstrip('/')}/compose/start"
    body = payload.model_dump(mode="json")

    logger.info(
        "[handoff] POSTing HandoffPayload to compositor for run_id=%s workflow_id=%s url=%s",
        payload.run_id,
        payload.workflow_id,
        url,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=body)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"[handoff] Request to compositor timed out for run_id={payload.run_id}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            f"[handoff] Network error contacting compositor for run_id={payload.run_id}: {exc}"
        ) from exc

    if 400 <= response.status_code < 500:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text
        raise NonRetryableError(
            f"[handoff] Compositor rejected payload with {response.status_code} for "
            f"run_id={payload.run_id}: {error_detail}"
        )

    if not response.is_success:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text
        raise RuntimeError(
            f"[handoff] Compositor returned {response.status_code} for "
            f"run_id={payload.run_id}: {error_detail}"
        )

    data = response.json()
    compose_job_id = data.get("compose_job_id")
    if not compose_job_id:
        raise RuntimeError(
            f"[handoff] Compositor response missing 'compose_job_id' for "
            f"run_id={payload.run_id}: {data}"
        )

    logger.info(
        "[handoff] Compositor accepted handoff for run_id=%s; compose_job_id=%s",
        payload.run_id,
        compose_job_id,
    )
    return compose_job_id


@activity.defn
async def poll_compose_status(
    compose_job_id: str,
    run_id: str,
    poll_interval_seconds: float = 15.0,
    timeout_seconds: float = 900.0,
) -> str:
    """Poll ``GET /compose/:id`` until the job is ``done`` or ``failed``.

    Heartbeats on every poll cycle so Temporal knows the activity is alive.

    Args:
        compose_job_id: The compose job ID returned by ``handoff_to_compositor``.
        run_id: The run ID, used only for structured log messages.
        poll_interval_seconds: Seconds to wait between poll requests.
        timeout_seconds: Maximum total seconds to wait before raising.

    Returns:
        The ``final_video_path`` from the compositor response (a container-absolute
        path under ``/data/shared/{run_id}/``).

    Raises:
        RuntimeError: If ``TABARIO_VIDEO_COMPOSITOR_URL`` is not set or the job fails.
        NonRetryableError: If the compositor reports ``status=failed``.
        RuntimeError: If the poll timeout is exceeded.
    """
    if not TABARIO_VIDEO_COMPOSITOR_URL:
        raise RuntimeError(
            "TABARIO_VIDEO_COMPOSITOR_URL environment variable is not set; "
            "cannot poll compose status."
        )

    url = f"{TABARIO_VIDEO_COMPOSITOR_URL.rstrip('/')}/compose/{compose_job_id}"
    elapsed = 0.0

    logger.info(
        "[poll_compose] Starting poll for compose_job_id=%s run_id=%s url=%s",
        compose_job_id,
        run_id,
        url,
    )

    while elapsed < timeout_seconds:
        activity.heartbeat()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
        except httpx.RequestError as exc:
            logger.warning(
                "[poll_compose] Network error polling compose_job_id=%s: %s — retrying",
                compose_job_id,
                exc,
            )
            await asyncio.sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds
            continue

        if not response.is_success:
            logger.warning(
                "[poll_compose] Unexpected %s from compositor for compose_job_id=%s — retrying",
                response.status_code,
                compose_job_id,
            )
            await asyncio.sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds
            continue

        data = response.json()
        status = data.get("status")

        logger.info(
            "[poll_compose] compose_job_id=%s run_id=%s status=%s elapsed=%.0fs",
            compose_job_id,
            run_id,
            status,
            elapsed,
        )

        if status == "done":
            final_video_path = data.get("final_video_path")
            if not final_video_path:
                raise RuntimeError(
                    f"[poll_compose] Compositor reported done but final_video_path is missing "
                    f"for compose_job_id={compose_job_id}"
                )
            logger.info(
                "[poll_compose] compose_job_id=%s complete. final_video_path=%s",
                compose_job_id,
                final_video_path,
            )
            return final_video_path

        if status == "failed":
            error = data.get("error", "unknown error")
            raise NonRetryableError(
                f"[poll_compose] Compositor job failed for compose_job_id={compose_job_id} "
                f"run_id={run_id}: {error}"
            )

        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds

    raise RuntimeError(
        f"[poll_compose] Timed out after {timeout_seconds}s waiting for compose_job_id={compose_job_id} "
        f"run_id={run_id} to complete"
    )


@activity.defn
async def classify_scenes_activity(brief_json: str, platform: str) -> List[Dict[str, Any]]:
    """Classify scenes using the scene classifier.
    
    Args:
        brief_json: JSON-serialized Brief object
        platform: Platform identifier (e.g., 'LinkedIn')
    
    Returns:
        List of SceneClassification dicts
    """
    from videomerge.models import Brief
    from videomerge.services.scene_classifier import classify_scenes
    
    _safe_heartbeat()
    logger.info(f"[classify_scenes] Classifying scenes for platform={platform}")
    
    brief = Brief.model_validate_json(brief_json)
    classifications = classify_scenes(brief, platform)
    
    # Convert to dicts for Temporal serialization
    result = [cls.model_dump() for cls in classifications]
    
    logger.info(f"[classify_scenes] Classified {len(result)} scenes")
    return result


@activity.defn
async def classify_scenes_from_script_activity(script_json: str, scenes_json: str) -> List[Dict[str, Any]]:
    """Classify scenes using script and scene prompts from N8N.

    This activity is used by the /orchestrate/start endpoint when SCENE_CLASSIFIER_ENABLED=true.
    It takes the voiceover script and scene prompts (generated by N8N) and determines
    which image generation model to use for each scene.

    Args:
        script_json: JSON-serialized voiceover script string
        scenes_json: JSON-serialized list of scene dicts from N8N prompts webhook

    Returns:
        List of SceneClassification dicts
    """
    import json
    from videomerge.services.scene_classifier import classify_scenes_from_script

    _safe_heartbeat()
    logger.info("[classify_scenes_from_script] Classifying scenes from script")

    script = json.loads(script_json)
    scenes = json.loads(scenes_json)

    classifications = classify_scenes_from_script(script, scenes)

    # Convert to dicts for Temporal serialization
    result = [cls.model_dump() for cls in classifications]

    logger.info(f"[classify_scenes_from_script] Classified {len(result)} scenes")
    return result


from videomerge.services.media_providers.registry import get_image_provider, get_video_provider

@activity.defn
async def start_image_generation_provider(
    provider: str,
    prompt_text: str,
    model: str,
    width: int,
    height: int,
    index: int,
    **kwargs
) -> str:
    """Submit image generation job to specified provider.
    
    Args:
        provider: Provider name ("fal" or "runpod")
        prompt_text: Image generation prompt
        model: Model identifier
        width: Image width
        height: Image height
        index: Scene index
        **kwargs: Provider-specific parameters
    
    Returns:
        Job ID
    """
    _safe_heartbeat()
    logger.info(f"[start_image_{provider}] Submitting for scene {index}, model={model}")
    
    provider_instance = get_image_provider(provider)
    job_id = await provider_instance.submit_text_to_image(
        prompt=prompt_text,
        model=model,
        width=width,
        height=height,
        **kwargs
    )
    
    logger.info(f"[start_image_{provider}] Job submitted: {job_id}")
    return job_id


@activity.defn
async def poll_image_generation_provider(
    provider: str,
    job_id: str,
    run_id: str,
    index: int,
    timeout_s: int,
    poll_interval_s: float,
    model: str = ""
) -> str:
    """Poll image generation job and download outputs.
    
    Args:
        provider: Provider name ("fal" or "runpod")
        job_id: Job ID from start_image_generation_provider
        run_id: Run identifier
        index: Scene index
        timeout_s: Timeout in seconds
        poll_interval_s: Poll interval in seconds
    
    Returns:
        Local file path to generated image
    """
    _safe_heartbeat()
    logger.info(f"[poll_image_{provider}] Polling job {job_id} for scene {index}")
    
    provider_instance = get_image_provider(provider)
    
    # Poll for completion
    if provider == "fal":
        output_urls = await _run_async_with_heartbeats(
            provider_instance.poll_image_generation,
            job_id,
            timeout_s,
            poll_interval_s,
            model,
            heartbeat_interval_s=30.0
        )
    else:
        output_urls = await _run_async_with_heartbeats(
            provider_instance.poll_image_generation,
            job_id,
            timeout_s,
            poll_interval_s,
            heartbeat_interval_s=30.0
        )
    
    if not output_urls:
        raise RuntimeError(f"Image generation failed for scene {index}: No outputs")
    
    # Download outputs
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = await provider_instance.download_outputs(
        output_urls=output_urls,
        dest_dir=run_dir,
        index=index
    )
    
    if not saved_files:
        raise RuntimeError(f"Failed to download image outputs for scene {index}")
    
    logger.info(f"[poll_image_{provider}] Saved to {saved_files[0]}")
    return str(saved_files[0])


@activity.defn
async def start_video_generation_provider(
    provider: str,
    prompt_text: str,
    image_input: str,
    model: str,
    width: int,
    height: int,
    index: int,
    **kwargs
) -> str:
    """Submit video generation job to specified provider.
    
    Args:
        provider: Provider name ("fal" or "runpod")
        prompt_text: Video motion prompt
        image_input: Input image path or data URL
        model: Model identifier
        width: Video width
        height: Video height
        index: Scene index
        **kwargs: Provider-specific parameters
    
    Returns:
        Job ID
    """
    _safe_heartbeat()
    logger.info(f"[start_video_{provider}] Submitting for scene {index}, model={model}")
    
    provider_instance = get_video_provider(provider)
    job_id = await provider_instance.submit_image_to_video(
        prompt=prompt_text,
        image_input=image_input,
        model=model,
        width=width,
        height=height,
        **kwargs
    )
    
    logger.info(f"[start_video_{provider}] Job submitted: {job_id}")
    return job_id


@activity.defn
async def poll_video_generation_provider(
    provider: str,
    job_id: str,
    run_id: str,
    index: int,
    timeout_s: int,
    poll_interval_s: float,
    model: str = ""
) -> List[str]:
    """Poll video generation job and download outputs.

    Args:
        provider: Provider name ("fal" or "runpod")
        job_id: Job ID from start_video_generation_provider
        run_id: Run identifier
        index: Scene index
        timeout_s: Timeout in seconds
        poll_interval_s: Poll interval in seconds
        model: Model identifier (required for Fal to construct the correct status URL)

    Returns:
        List of local file paths to generated videos
    """
    _safe_heartbeat()
    logger.info(f"[poll_video_{provider}] Polling job {job_id} for scene {index}")

    provider_instance = get_video_provider(provider)

    # Poll for completion
    if provider == "fal":
        output_urls = await _run_async_with_heartbeats(
            provider_instance.poll_video_generation,
            job_id,
            timeout_s,
            poll_interval_s,
            model,
            heartbeat_interval_s=30.0
        )
    else:
        output_urls = await _run_async_with_heartbeats(
            provider_instance.poll_video_generation,
            job_id,
            timeout_s,
            poll_interval_s,
            heartbeat_interval_s=30.0
        )

    if not output_urls:
        raise RuntimeError(f"Video generation failed for scene {index}: No outputs")
    
    # Download outputs (if needed - Runpod already downloads during polling)
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    if provider == "fal":
        saved_files = await provider_instance.download_outputs(
            output_urls=output_urls,
            dest_dir=run_dir,
            index=index
        )
    else:
        # RunPod outputs are local file paths OR inline base64 data URLs.
        # Inline base64 would exceed Temporal's 2 MB activity-return size limit,
        # so decode and persist them to disk and return local paths instead.
        saved_files = []
        for i, url in enumerate(output_urls):
            if url.startswith("data:"):
                # Strip optional #filename= fragment before decoding
                if "#filename=" in url:
                    fragment_filename: str | None = url.split("#filename=", 1)[1]
                    clean_url = url.split("#filename=", 1)[0]
                else:
                    fragment_filename = None
                    clean_url = url
                raw_b64 = _strip_base64_data_url(clean_url)
                video_data = base64.b64decode(raw_b64)
                # Always prefix with scene index so concurrent scenes writing the
                # same ComfyUI output name (e.g. ComfyUI_00001_.mp4) don't
                # overwrite each other on disk.
                out_name = f"{index:03d}_{fragment_filename}" if fragment_filename else f"video_{index:03d}_{i}.mp4"
                dest_path = run_dir / out_name
                dest_path.write_bytes(video_data)
                logger.info(
                    "[poll_video_runpod] Saved inline base64 video (%d bytes) to %s",
                    len(video_data),
                    dest_path,
                )
                saved_files.append(dest_path)
            else:
                saved_files.append(Path(url))
    
    if not saved_files:
        raise RuntimeError(f"Failed to download video outputs for scene {index}")
    
    logger.info(f"[poll_video_{provider}] Saved {len(saved_files)} files")
    return [str(p) for p in saved_files]
