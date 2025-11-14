import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
from temporalio import activity

from videomerge.config import DATA_SHARED_BASE, WORKFLOW_I2V_PATH, VIDEO_COMPLETED_N8N_WEBHOOK_URL
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
async def generate_voiceover(run_id: str, script: str, language: str, elevenlabs_voice_id: str) -> str:
    """Triggers external workflow to generate voiceover audio and records its duration.

    The external N8N webhook is responsible for creating the actual voiceover.mp3 file
    in the shared DATA_SHARED_BASE/run_id directory. This activity:
    - Calls the webhook with the required payload
    - Persists the returned audio_duration in a metadata JSON file
    - Returns the expected voiceover.mp3 path for downstream activities
    """
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    audio_path = run_dir / "voiceover.mp3"

    url = "https://birthdaypartyai.app/n8n/webhook/96b6d82c-ee94-46aa-b38d-4c9e77d096b4"
    payload: Dict[str, Any] = {
        "script": script,
        "runId": run_id,
        "elevenlabs_voice_id": elevenlabs_voice_id,
        "language": language,
    }

    logger.info(f"[voiceover] Calling N8N webhook for run_id={run_id}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    audio_duration = data.get("audio_duration")
    if audio_duration is not None:
        metadata_path = run_dir / "voiceover_metadata.json"
        try:
            metadata_path.write_text(json.dumps({"audio_duration": audio_duration}, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"[voiceover] Saved audio_duration metadata for run_id={run_id}: {audio_duration}")
        except Exception as e:
            logger.warning(f"[voiceover] Failed to write metadata for run_id={run_id}: {e}")

    logger.info(f"[voiceover] Voiceover generation triggered successfully for run_id={run_id}")
    # The external workflow is expected to materialize the audio at this path.
    return str(audio_path)


@activity.defn
async def generate_scene_prompts(run_id: str, script: str, image_style: str | None = None) -> List[Dict[str, Any]]:
    """Generates scene prompts by calling the external N8N webhook.

    This activity:
    - Reads audio_duration from voiceover_metadata.json written by generate_voiceover
    - Calls the prompts webhook with script, audio_duration and image_style
    - Returns the list of prompts (each with image_prompt and video_prompt)
    """
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    metadata_path = run_dir / "voiceover_metadata.json"

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"voiceover_metadata.json not found for run_id={run_id}; cannot generate prompts")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid voiceover metadata for run_id={run_id}: {e}")

    audio_duration = metadata.get("audio_duration")
    if audio_duration is None:
        raise RuntimeError(f"audio_duration missing in voiceover metadata for run_id={run_id}")

    url = "https://birthdaypartyai.app/n8n/webhook/1f8c887d-0247-4378-b855-934f780bdb0c"
    payload: Dict[str, Any] = {
        "script": script,
        "audio_duration": audio_duration,
        "image_style": image_style,
    }

    logger.info(f"[prompts] Calling N8N prompts webhook for run_id={run_id}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise RuntimeError(f"Prompts webhook returned invalid payload for run_id={run_id}: {data}")

    # Persist prompts for debugging/traceability
    prompts_path = run_dir / "scene_prompts.json"
    try:
        prompts_path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[prompts] Saved scene prompts for run_id={run_id} to {prompts_path}")
    except Exception as e:
        logger.warning(f"[prompts] Failed to write scene prompts for run_id={run_id}: {e}")

    return prompts


@activity.defn
async def generate_image(prompt_text: str, workflow_path: str, index: int) -> str:
    """Generates a single image from a text prompt."""
    activity.heartbeat()
    logger.info(f"Generating image for prompt index {index}")
    
    # Convert string path to Path object
    workflow_path = Path(workflow_path)
    
    # Force refresh the client to get latest configuration
    client = get_comfyui_client(ClientType.IMAGE, force_refresh=True)
    
    prompt_id = await asyncio.to_thread(client.submit_text_to_image, prompt_text, template_path=workflow_path)
    filenames = await asyncio.to_thread(client.poll_until_complete, prompt_id, timeout_s=600, poll_interval_s=15)
    if not filenames:
        raise RuntimeError(f"Image generation failed for prompt index {index}: No output files.")
    #logger.info(f"Image generated for prompt index {index}: {filenames[0]}")
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
    
    # Force refresh the client to get latest configuration
    client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)
    
    prompt_id = await asyncio.to_thread(
        client.submit_image_to_video,
        video_prompt,
        image_input,
        template_path=WORKFLOW_I2V_PATH,
        run_id=run_id,
    )
    video_hints = await asyncio.to_thread(client.poll_until_complete, prompt_id, timeout_s=600, poll_interval_s=15)
    saved_files = await asyncio.to_thread(client.download_outputs, video_hints, run_dir)
    logger.info(f"Video generated for prompt index {index}: {saved_files}")
    return [str(p) for p in saved_files]


@activity.defn
async def stitch_videos(run_id: str, video_paths: List[str], voiceover_path: str) -> str:
    """Stitches video clips together with a voiceover."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    output_path = run_dir / "stitched_output.mp4"
    logger.info(f"Stitching {len(video_paths)} videos for run_id={run_id}")
    await asyncio.to_thread(
        concat_videos_with_voiceover,
        [Path(p) for p in video_paths],
        Path(voiceover_path),
        output_path,
    )
    logger.info(f"Stitching complete for run_id={run_id}")
    return str(output_path)


@activity.defn
async def burn_subtitles_into_video(run_id: str, stitched_video_path: str, language: str, voiceover_path: str) -> str:
    """Generates and burns subtitles into the final video."""
    activity.heartbeat()
    run_dir = DATA_SHARED_BASE / run_id
    final_path = run_dir / "final_video.mp4"
    logger.info(f"Generating and burning subtitles for run_id={run_id}")
    await asyncio.to_thread(generate_and_burn_subtitles,
        Path(stitched_video_path),
        final_path,
        language=language,
        audio_hint=Path(voiceover_path),
    )
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
