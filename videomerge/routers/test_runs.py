from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from videomerge.config import DATA_SHARED_BASE, IMAGE_WORKFLOWS, WORKFLOWS_BASE_PATH, WORKFLOW_I2V_PATH
from videomerge.services.comfyui_client import ClientType, get_comfyui_client
from videomerge.temporal.activities import generate_scene_prompts
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["tests"])
logger = get_logger(__name__)


class TestRunRequest(BaseModel):
    script: str = Field(..., min_length=1)
    language: str = Field(..., min_length=1)
    image_style: Optional[str] = None
    image_width: Optional[int] = Field(default=None, ge=64)
    image_height: Optional[int] = Field(default=None, ge=64)


class TestRunResponse(BaseModel):
    guid: str
    output_dir: str
    scene_prompts: List[Dict[str, Any]]
    image_files: List[str]
    video_files: List[str]


def _estimate_audio_duration_seconds(script: str) -> float:
    """Estimate voiceover duration in seconds from the script.

    This endpoint intentionally does not generate voiceover audio, but the existing
    `generate_scene_prompts` activity requires an `audio_duration` value.

    The heuristic is based on a typical narration pace of ~150 words per minute.
    """

    words = [w for w in script.split() if w.strip()]
    wpm = 150.0
    seconds = max(5.0, (len(words) / wpm) * 60.0)
    return float(seconds)


def _unique_output_name(prefix: str, ext: str) -> str:
    """Return a unique filename for test outputs."""

    token = uuid.uuid4().hex
    safe_ext = ext.lstrip(".") or "bin"
    return f"{prefix}_{token}.{safe_ext}"


def _write_voiceover_metadata(run_dir: Path, audio_duration: float) -> None:
    """Write a minimal voiceover metadata file required by `generate_scene_prompts`."""

    payload = {"audio_duration": audio_duration}
    (run_dir / "voiceover_metadata.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _save_hint_to_file(*, client_type: ClientType, hint: str, dest_path: Path) -> None:
    """Fetch an output hint from ComfyUI (local or RunPod) and save it to `dest_path`."""

    client = get_comfyui_client(client_type, force_refresh=True)
    _filename, content = client.fetch_output_bytes(hint)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)


def _infer_extension_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix
    return suffix.lstrip(".") if suffix else "bin"


def _prepare_image_input_for_video(*, image_hint: str) -> str:
    """Prepare an image input value suitable for the video client."""

    if image_hint.startswith("data:image/"):
        return image_hint

    image_client = get_comfyui_client(ClientType.IMAGE, force_refresh=True)
    video_client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)
    filename, content = image_client.fetch_output_bytes(image_hint)
    uploaded = video_client.upload_image_to_input(filename, content, overwrite=True)
    return uploaded


@router.post("/tests/run", response_model=TestRunResponse)
async def run_test(req: TestRunRequest) -> TestRunResponse:
    """Run a lightweight generation test.

    Creates `/data/shared/tests/{guid}` (under `DATA_SHARED_BASE`) and generates:
    - Scene prompts via `generate_scene_prompts`
    - One image per scene
    - One video clip per scene

    It intentionally does not generate voiceovers, subtitles, or stitch clips.
    """

    guid = str(uuid.uuid4())
    run_id = str(Path("tests") / guid)
    run_dir = DATA_SHARED_BASE / run_id

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create test output directory: {exc}")

    try:
        audio_duration = _estimate_audio_duration_seconds(req.script)
        _write_voiceover_metadata(run_dir, audio_duration)

        image_style = req.image_style or "cinematic"
        scene_prompts = await generate_scene_prompts(run_id=run_id, script=req.script, image_style=image_style)

        workflow_filename = IMAGE_WORKFLOWS.get(image_style, IMAGE_WORKFLOWS["default"])
        workflow_path = f"{WORKFLOWS_BASE_PATH}/{workflow_filename}"

        comfyui_workflow_name: Optional[str] = None
        if image_style == "cinematic":
            comfyui_workflow_name = "image_qwen_t2i"
        elif image_style == "disney":
            comfyui_workflow_name = "image_disneyizt_t2i"

        image_files: List[str] = []
        video_files: List[str] = []

        image_client = get_comfyui_client(ClientType.IMAGE, force_refresh=True)
        video_client = get_comfyui_client(ClientType.VIDEO, force_refresh=True)

        for index, prompt in enumerate(scene_prompts):
            image_prompt = prompt.get("image_prompt") if isinstance(prompt, dict) else None
            video_prompt = prompt.get("video_prompt") if isinstance(prompt, dict) else None

            if not image_prompt or not video_prompt:
                continue

            prompt_id = image_client.submit_text_to_image(
                image_prompt,
                template_path=None if comfyui_workflow_name else Path(workflow_path),
                comfyui_workflow_name=comfyui_workflow_name,
                image_width=req.image_width,
                image_height=req.image_height,
            )
            image_hints = image_client.poll_until_complete(prompt_id, timeout_s=600, poll_interval_s=15)
            if not image_hints:
                raise RuntimeError(f"No image outputs for scene {index}")

            image_hint = image_hints[0]
            img_ext = "png" if image_hint.startswith("data:image/") else _infer_extension_from_filename(image_hint)
            img_name = _unique_output_name(f"scene_{index:03d}_image", img_ext)
            img_path = run_dir / img_name
            _save_hint_to_file(client_type=ClientType.IMAGE, hint=image_hint, dest_path=img_path)
            image_files.append(str(img_path))

            image_input = _prepare_image_input_for_video(image_hint=image_hint)
            video_prompt_id = video_client.submit_image_to_video(
                video_prompt,
                image_input,
                template_path=WORKFLOW_I2V_PATH,
                run_id=run_id,
            )
            video_hints = video_client.poll_until_complete(video_prompt_id, timeout_s=600, poll_interval_s=15)
            if not video_hints:
                raise RuntimeError(f"No video outputs for scene {index}")

            for v_i, video_hint in enumerate(video_hints):
                vid_ext = "mp4" if video_hint.startswith("data:") else _infer_extension_from_filename(video_hint)
                vid_name = _unique_output_name(f"scene_{index:03d}_clip_{v_i:02d}", vid_ext)
                vid_path = run_dir / vid_name
                _save_hint_to_file(client_type=ClientType.VIDEO, hint=video_hint, dest_path=vid_path)
                video_files.append(str(vid_path))

        return TestRunResponse(
            guid=guid,
            output_dir=str(run_dir),
            scene_prompts=scene_prompts,
            image_files=image_files,
            video_files=video_files,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[/tests/run] Failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
