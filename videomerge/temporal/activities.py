import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from temporalio import activity

from videomerge.config import DATA_SHARED_BASE, WORKFLOW_I2V_PATH, VIDEO_COMPLETED_N8N_WEBHOOK_URL
from videomerge.services.media import get_duration
from videomerge.services.metrics import (
    voiceover_length_seconds,
    get_length_bucket,
    total_images_generation_seconds,
    total_videos_generation_seconds,
    stitch_seconds,
    subtitles_seconds,
    videos_completed_total,
)
from videomerge.services.comfyui_client import get_image_client, get_video_client, refresh_comfyui_client, ClientType, get_comfyui_client
from videomerge.services.comfyui import (
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
async def generate_voiceover(run_id: str, script: str) -> str:
    """Generates voiceover audio from the script."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    audio_path = run_dir / "voiceover.mp3"
    logger.info(f"Generating voiceover for run_id={run_id}")
    # This is a CPU-bound task, so we run it in a thread pool to avoid blocking the event loop.
    await asyncio.to_thread(synthesize_voice, script, audio_path)

    # Measure resulting audio length and record it as a Prometheus metric
    duration = get_duration(audio_path)
    if duration is not None:
        length_bucket = get_length_bucket(duration)
        voiceover_length_seconds.labels(length_bucket=length_bucket).observe(duration)

        # Persist length_bucket so other activities (image/video/stitch) can reuse it
        try:
            bucket_path = run_dir / "length_bucket.txt"
            bucket_path.write_text(length_bucket, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write length_bucket for run_id={run_id}: {e}")

    logger.info(f"Voiceover generated successfully for run_id={run_id}")
    return str(audio_path)


@activity.defn
async def generate_image(run_id: str, prompt_text: str, workflow_path: str, index: int) -> str:
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
    prompt_id = await asyncio.to_thread(client.submit_text_to_image, prompt_text, template_path=workflow_path)
    filenames = await asyncio.to_thread(client.poll_until_complete, prompt_id, timeout_s=600, poll_interval_s=15)
    duration = time.time() - start_time

    if length_bucket is not None:
        total_images_generation_seconds.labels(length_bucket=length_bucket).observe(duration)

    if not filenames:
        raise RuntimeError(f"Image generation failed for prompt index {index}: No output files.")
    return filenames[0]


@activity.defn
async def upload_image_for_video_generation(image_hint: str) -> str:
    """Process image for video generation.
    
    For RunPod: Passes through base64 image data URL (no upload needed).
    For Local: Uploads the image to ComfyUI input directory.
    
    Args:
        image_hint: Either base64 image data (RunPod) or filename hint (local)
    
    Returns:
        For RunPod: Base64 image data URL (unchanged)
        For Local: Uploaded filename in ComfyUI
    """
    activity.heartbeat()
    
    # Check if this is a RunPod base64 image
    if image_hint.startswith("data:image/"):
        logger.info(f"[RunPod] Passing through base64 image data for video generation: {image_hint[:50]}...")
        
        # For RunPod, we don't need to upload - just return the base64 data
        # The video generation will handle it directly
        return image_hint
    else:
        # For local development, upload the image to ComfyUI
        logger.info(f"[Local] Uploading image {image_hint} to ComfyUI input directory.")
        
        # Check if ComfyUI configuration has changed
        client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)
        
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
    video_hints = await asyncio.to_thread(client.poll_until_complete, prompt_id, timeout_s=600, poll_interval_s=15)
    saved_files = await asyncio.to_thread(client.download_outputs, video_hints, run_dir)
    duration = time.time() - start_time

    if length_bucket is not None:
        total_videos_generation_seconds.labels(length_bucket=length_bucket).observe(duration)

    logger.info(f"Video generated for prompt index {index}: {saved_files}")
    return [str(p) for p in saved_files]


@activity.defn
async def stitch_videos(run_id: str, video_paths: List[str], voiceover_path: str) -> str:
    """Stitches video clips together with a voiceover."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    output_path = run_dir / "stitched_output.mp4"
    logger.info(f"Stitching {len(video_paths)} videos for run_id={run_id}")

    length_bucket = _load_length_bucket(run_id)

    start_time = time.time()
    await asyncio.to_thread(
        concat_videos_with_voiceover,
        [Path(p) for p in video_paths],
        Path(voiceover_path),
        output_path,
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
