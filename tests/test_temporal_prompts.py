import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from videomerge.models import OrchestrateStartRequest
from videomerge.temporal import activities as temporal_activities
from videomerge.temporal.workflows import VideoGenerationWorkflow
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


@pytest.mark.asyncio
async def test_generate_scene_prompts_success(monkeypatch, tmp_path: Path) -> None:
    """generate_scene_prompts should read audio_duration, call webhook, and persist prompts."""

    # Point DATA_SHARED_BASE to a temporary directory
    temporal_activities.DATA_SHARED_BASE = tmp_path

    run_id = "run-123"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Prepare metadata with audio_duration
    metadata_path = run_dir / "voiceover_metadata.json"
    metadata_path.write_text(json.dumps({"audio_duration": 40}, ensure_ascii=False), encoding="utf-8")

    # Mock httpx.AsyncClient used inside the activity
    class DummyResponse:
        def __init__(self, payload: Dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:  # pragma: no cover - no error path here
            return None

        def json(self) -> Dict[str, Any]:
            return self._payload

    recorded_request: Dict[str, Any] = {}

    class DummyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "DummyClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - trivial
            return None

        async def post(self, url: str, json: Dict[str, Any]) -> DummyResponse:  # type: ignore[override]
            recorded_request["url"] = url
            recorded_request["json"] = json
            return DummyResponse({
                "prompts": [
                    {
                        "image_prompt": "image-1",
                        "video_prompt": "video-1",
                    },
                    {
                        "image_prompt": "image-2",
                        "video_prompt": "video-2",
                    },
                ]
            })

    monkeypatch.setattr(temporal_activities.httpx, "AsyncClient", DummyClient)

    prompts = await temporal_activities.generate_scene_prompts(
        run_id=run_id,
        script="Test script",
        image_style="cinematic",
    )

    # Verify HTTP request payload
    assert recorded_request["url"].endswith("1f8c887d-0247-4378-b855-934f780bdb0c")
    assert recorded_request["json"] == {
        "script": "Test script",
        "audio_duration": 40,
        "image_style": "cinematic",
    }

    # Verify prompts returned and persisted to disk
    assert isinstance(prompts, list)
    assert len(prompts) == 2
    assert prompts[0]["image_prompt"] == "image-1"
    assert prompts[0]["video_prompt"] == "video-1"

    prompts_path = run_dir / "scene_prompts.json"
    assert prompts_path.is_file()
    persisted = json.loads(prompts_path.read_text(encoding="utf-8"))
    assert persisted == prompts


@pytest.mark.asyncio
async def test_generate_scene_prompts_missing_metadata(tmp_path: Path) -> None:
    """generate_scene_prompts should fail clearly when metadata file is missing."""

    temporal_activities.DATA_SHARED_BASE = tmp_path
    run_id = "run-no-metadata"

    with pytest.raises(RuntimeError, match="voiceover_metadata.json not found"):
        await temporal_activities.generate_scene_prompts(
            run_id=run_id,
            script="Test script",
            image_style="cinematic",
        )


@pytest.mark.asyncio
async def test_video_generation_workflow_uses_generated_prompts(tmp_path: Path) -> None:
    """End-to-end wiring test for VideoGenerationWorkflow using generated prompts.

    This uses Temporal's in-memory test environment with stub activities to verify that:
    - generate_scene_prompts is invoked
    - its returned prompts drive the number of scenes
    - image_prompt values flow into the completion webhook payload.
    """

    recorded: Dict[str, Any] = {}

    # Stub activities used by the workflow
    async def setup_run_directory(run_id: str, payload: Dict[str, Any]) -> str:
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return str(run_dir)

    async def generate_voiceover(run_id: str, script: str, language: str, elevenlabs_voice_id: str) -> str:
        # Pretend voiceover exists
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return str(run_dir / "voiceover.mp3")

    async def generate_scene_prompts(run_id: str, script: str, image_style: str | None = None) -> List[Dict[str, Any]]:
        prompts: List[Dict[str, Any]] = [
            {"image_prompt": "scene-1-image", "video_prompt": "scene-1-video"},
            {"image_prompt": "scene-2-image", "video_prompt": "scene-2-video"},
        ]
        recorded["scene_prompts"] = prompts
        return prompts

    async def generate_image(
        run_id: str,
        prompt_text: str,
        workflow_path: str,
        index: int,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> str:
        # Return a dummy image hint per scene
        return f"image-{index}.png"

    async def upload_image_for_video_generation(image_hint: str) -> str:
        return image_hint

    async def generate_video_from_image(run_id: str, video_prompt: str, image_input: str, index: int) -> List[str]:
        # Each scene yields one video file
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        video_path = run_dir / f"scene-{index}.mp4"
        video_path.write_text("dummy", encoding="utf-8")
        return [str(video_path)]

    async def stitch_videos(run_id: str, video_paths: List[str], voiceover_path: str) -> str:
        run_dir = tmp_path / run_id
        output = run_dir / "stitched.mp4"
        output.write_text("dummy-stitched", encoding="utf-8")
        # Record for assertions
        recorded["stitched_videos"] = list(video_paths)
        return str(output)

    async def burn_subtitles_into_video(run_id: str, stitched_video_path: str, language: str, voiceover_path: str) -> str:
        run_dir = tmp_path / run_id
        final = run_dir / "final.mp4"
        final.write_text("dummy-final", encoding="utf-8")
        return str(final)

    async def send_completion_webhook(
        run_id: str,
        status: str,
        final_video_path: str,
        workflow_id: str | None = None,
        run_dir: str | None = None,
        video_files: List[str] | None = None,
        image_files: List[str] | None = None,
        voiceover_path: str | None = None,
    ) -> None:
        recorded["completion"] = {
            "run_id": run_id,
            "status": status,
            "final_video_path": final_video_path,
            "workflow_id": workflow_id,
            "run_dir": run_dir,
            "video_files": list(video_files or []),
            "image_files": list(image_files or []),
            "voiceover_path": voiceover_path,
        }

    # Run workflow in Temporal test environment
    async with WorkflowEnvironment.start_time_skipping() as env:
        client: Client = await env.new_client()

        worker = Worker(
            client,
            task_queue="test-video-generation",
            workflows=[VideoGenerationWorkflow],
            activities=[
                setup_run_directory,
                generate_voiceover,
                generate_scene_prompts,
                generate_image,
                upload_image_for_video_generation,
                generate_video_from_image,
                stitch_videos,
                burn_subtitles_into_video,
                send_completion_webhook,
            ],
        )

        async with worker:
            req = OrchestrateStartRequest(
                user_id="user-1",
                script="Test script",
                caption="Test caption",
                prompts=None,
                language="en",
                image_style="cinematic",
                run_id="run-workflow-1",
                elevenlabs_voice_id="voice-123",
            )

            final_video_path = await client.execute_workflow(
                VideoGenerationWorkflow.run,
                req,
                id="test-video-generation-workflow",
                task_queue="test-video-generation",
            )

    # Assertions on wiring
    assert "scene_prompts" in recorded
    assert len(recorded["scene_prompts"]) == 2

    completion = recorded["completion"]
    assert completion["status"] == "completed"
    # image_files in webhook should come from generated prompts
    assert completion["image_files"] == ["scene-1-image", "scene-2-image"]
    # Final video path returned by workflow should match completion payload
    assert completion["final_video_path"] == final_video_path
