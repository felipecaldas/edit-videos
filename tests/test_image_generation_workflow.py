"""End-to-end tests for ImageGenerationWorkflow.

Each test drives the real workflow through Temporal's time-skipping test
environment. Every activity the workflow calls is replaced by a local stub
decorated with ``@activity.defn(name=...)`` so the Worker registers the stub
under the same name the workflow invokes — the trick that the earlier skipped
tests in ``test_temporal_prompts.py`` were missing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from videomerge.models import (
    Brief,
    ImageGenerationStartRequest,
    PlatformBriefModel,
    SceneBrief,
    VisualDirection,
)
from videomerge.temporal import workflows as workflows_module
from videomerge.temporal.workflows import ImageGenerationWorkflow


# ──────────────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _make_brief(num_scenes: int = 2, platform: str = "LinkedIn") -> Brief:
    """Build a minimally-valid Brief with ``num_scenes`` scenes on one platform."""
    scenes = [
        SceneBrief(
            scene_number=i + 1,
            spoken_line=f"Line {i + 1}",
            caption_text=f"Caption {i + 1}",
            duration_seconds=2.0,
            visual_description=f"Visual {i + 1}",
        )
        for i in range(num_scenes)
    ]
    return Brief(
        hook="Test hook",
        title="Test title",
        narrative_structure="problem-solution-CTA",
        visual_direction=VisualDirection(
            mood="optimistic",
            color_feel="warm pastels",
            shot_style="clean studio",
            branding_elements="Tabario lower-third",
        ),
        platform_briefs=[
            PlatformBriefModel(
                platform=platform,
                hook="Platform hook",
                tone="confident",
                aspect_ratio="9:16",
                scenes=scenes,
                call_to_action="Visit tabario.com",
            )
        ],
    )


def _make_request(
    *,
    with_brief: bool = False,
    video_format: Optional[str] = None,
    target_resolution: Optional[str] = None,
    num_scenes: int = 2,
    platform: Optional[str] = "LinkedIn",
    run_id: str = "test-run-1",
    workflow_id: str = "test-wf-1",
) -> ImageGenerationStartRequest:
    kwargs: Dict[str, Any] = {
        "user_id": "user-1",
        "script": "Test script",
        "language": "en",
        "image_style": "default",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "user_access_token": "jwt-token",
        "video_format": video_format,
        "target_resolution": target_resolution,
    }
    if with_brief:
        kwargs["brief"] = _make_brief(num_scenes=num_scenes, platform=platform or "LinkedIn")
        kwargs["platform"] = platform
    return ImageGenerationStartRequest(**kwargs)


class _Recorder:
    """Per-test recorder for activity calls and stub-behavior overrides."""

    def __init__(self) -> None:
        self.calls: Dict[str, List[tuple]] = {}
        # Scene prompts the legacy n8n stub should return (list of dicts).
        self.legacy_prompts: List[Dict[str, Any]] = [
            {"image_prompt": "scene-1"},
            {"image_prompt": "scene-2"},
        ]
        # Classifier stub return value. None = classifier not called; [] = empty list.
        self.classifications: Optional[List[Dict[str, Any]]] = None
        # If set, next call to the given activity raises ApplicationError.
        self.raise_on: Dict[str, str] = {}

    def record(self, name: str, args: tuple) -> None:
        self.calls.setdefault(name, []).append(args)

    def called(self, name: str) -> bool:
        return name in self.calls and len(self.calls[name]) > 0


def _build_stubs(rec: _Recorder) -> List[Any]:
    """Return a list of activity-decorated stubs that record calls into ``rec``."""

    @activity.defn(name="setup_run_directory")
    async def setup_run_directory(run_id: str, payload: Dict[str, Any]) -> str:
        rec.record("setup_run_directory", (run_id,))
        return f"/tmp/test/{run_id}"

    @activity.defn(name="generate_image_scene_prompts")
    async def generate_image_scene_prompts(
        run_id: str, script: str, language: str, image_style: str | None = None
    ) -> List[Dict[str, Any]]:
        rec.record("generate_image_scene_prompts", (run_id, image_style))
        return list(rec.legacy_prompts)

    @activity.defn(name="persist_scene_prompts")
    async def persist_scene_prompts(run_id: str, prompts: List[Dict[str, Any]]) -> None:
        rec.record("persist_scene_prompts", (run_id, len(prompts)))

    @activity.defn(name="classify_scenes_activity")
    async def classify_scenes_activity(brief_json: str, platform: str) -> List[Dict[str, Any]]:
        rec.record("classify_scenes_activity", (platform,))
        return list(rec.classifications or [])

    @activity.defn(name="start_image_generation")
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
        rec.record("start_image_generation", (index, image_width, image_height, prompt_text))
        return f"comfy-job-{index}"

    @activity.defn(name="poll_image_generation")
    async def poll_image_generation(prompt_id: str, run_id: str, index: int) -> str:
        rec.record("poll_image_generation", (prompt_id, index))
        return f"comfy-hint-{index}"

    @activity.defn(name="start_image_generation_provider")
    async def start_image_generation_provider(
        provider: str,
        prompt_text: str,
        model: str,
        width: int,
        height: int,
        index: int,
        negative_prompt: str | None = None,
        style_id: str | None = None,
    ) -> str:
        rec.record("start_image_generation_provider", (provider, model, width, height, index))
        return f"{provider}-job-{index}"

    @activity.defn(name="poll_image_generation_provider")
    async def poll_image_generation_provider(
        provider: str,
        job_id: str,
        run_id: str,
        index: int,
        timeout_s: int,
        poll_interval_s: float,
        model: str = "",
    ) -> str:
        rec.record("poll_image_generation_provider", (provider, job_id, index, model))
        return f"{provider}-hint-{index}"

    @activity.defn(name="persist_image_output")
    async def persist_image_output(
        run_id: str, user_id: str, image_hint: str, index: int, user_access_token: str
    ) -> str:
        rec.record("persist_image_output", (index, image_hint))
        return f"image_{index + 1:03d}.png"

    @activity.defn(name="send_image_generation_webhook")
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
        rec.record(
            "send_image_generation_webhook",
            (status, tuple(image_files), tuple(image_prompts), failure_reason, video_idea_id, platform),
        )

    return [
        setup_run_directory,
        generate_image_scene_prompts,
        persist_scene_prompts,
        classify_scenes_activity,
        start_image_generation,
        poll_image_generation,
        start_image_generation_provider,
        poll_image_generation_provider,
        persist_image_output,
        send_image_generation_webhook,
    ]


async def _run_workflow(
    req: ImageGenerationStartRequest, rec: _Recorder
) -> List[str]:
    """Spin up a time-skipping test env, run the workflow, and return its result."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="test-igw",
            workflows=[ImageGenerationWorkflow],
            activities=_build_stubs(rec),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                ImageGenerationWorkflow.run,
                req,
                id=f"test-igw-{req.run_id}",
                task_queue="test-igw",
            )
    finally:
        await env.shutdown()


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 1 — legacy n8n path, happy path, 2 scenes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_path_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", False)
    rec = _Recorder()
    rec.legacy_prompts = [
        {"image_prompt": "scene-1-image"},
        {"image_prompt": "scene-2-image"},
    ]

    req = _make_request(with_brief=False, run_id="run-legacy-1")
    result = await _run_workflow(req, rec)

    assert result == ["image_001.png", "image_002.png"]
    assert rec.called("setup_run_directory")
    assert rec.called("generate_image_scene_prompts")
    assert not rec.called("persist_scene_prompts")
    assert not rec.called("classify_scenes_activity")
    # 2 scenes → 2 ComfyUI starts and polls
    assert len(rec.calls["start_image_generation"]) == 2
    assert len(rec.calls["poll_image_generation"]) == 2
    # Completion webhook with status=completed and ordered prompts
    status, image_files, image_prompts, failure_reason, _, _ = rec.calls[
        "send_image_generation_webhook"
    ][0]
    assert status == "completed"
    assert image_files == ("image_001.png", "image_002.png")
    assert image_prompts == ("scene-1-image", "scene-2-image")
    assert failure_reason is None


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 2 — brief-aware path, persist_scene_prompts called
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_brief_aware_path_persists_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Classifier disabled so this test isolates the prompt-persistence branch
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", False)
    rec = _Recorder()

    req = _make_request(with_brief=True, num_scenes=2, run_id="run-brief-1")
    result = await _run_workflow(req, rec)

    assert result == ["image_001.png", "image_002.png"]
    assert rec.called("persist_scene_prompts")
    assert not rec.called("generate_image_scene_prompts")
    # persist_scene_prompts called with 2 prompts
    run_id, count = rec.calls["persist_scene_prompts"][0]
    assert count == 2


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 3 — brief-aware + classifier → all Fal
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classifier_routes_all_scenes_to_fal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", True)
    rec = _Recorder()
    rec.classifications = [
        {"image_provider": "fal", "image_model": "fal-ai/flux/dev"},
        {"image_provider": "fal", "image_model": "fal-ai/flux/dev"},
    ]

    req = _make_request(with_brief=True, num_scenes=2, run_id="run-fal-1")
    await _run_workflow(req, rec)

    assert rec.called("classify_scenes_activity")
    assert len(rec.calls["start_image_generation_provider"]) == 2
    assert len(rec.calls["poll_image_generation_provider"]) == 2
    assert not rec.called("start_image_generation")
    assert not rec.called("poll_image_generation")
    # Each provider call includes the model name
    for provider, model, _w, _h, _idx in rec.calls["start_image_generation_provider"]:
        assert provider == "fal"
        assert model == "fal-ai/flux/dev"


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 4 — brief-aware + classifier → all RunPod/ComfyUI
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classifier_routes_all_scenes_to_comfyui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", True)
    rec = _Recorder()
    rec.classifications = [
        {"image_provider": "runpod", "image_model": None},
        {"image_provider": "runpod", "image_model": None},
    ]

    req = _make_request(with_brief=True, num_scenes=2, run_id="run-comfy-1")
    await _run_workflow(req, rec)

    assert rec.called("classify_scenes_activity")
    assert len(rec.calls["start_image_generation"]) == 2
    assert len(rec.calls["poll_image_generation"]) == 2
    assert not rec.called("start_image_generation_provider")


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 5 — mixed classification (fal + runpod in one run)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", True)
    rec = _Recorder()
    rec.classifications = [
        {"image_provider": "fal", "image_model": "fal-ai/flux/dev"},
        {"image_provider": "runpod", "image_model": None},
    ]

    req = _make_request(with_brief=True, num_scenes=2, run_id="run-mix-1")
    await _run_workflow(req, rec)

    # Scene 0 went to fal, scene 1 went to comfyui
    assert len(rec.calls.get("start_image_generation_provider", [])) == 1
    assert len(rec.calls.get("start_image_generation", [])) == 1
    provider_call = rec.calls["start_image_generation_provider"][0]
    assert provider_call[0] == "fal"
    assert provider_call[4] == 0  # scene index
    comfy_call = rec.calls["start_image_generation"][0]
    assert comfy_call[0] == 1  # scene index


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 6 — classifier returns fewer entries than scenes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classifier_partial_response_falls_back_to_comfyui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", True)
    rec = _Recorder()
    # Only 1 classification for 3 scenes
    rec.classifications = [{"image_provider": "fal", "image_model": "fal-ai/flux/dev"}]

    req = _make_request(with_brief=True, num_scenes=3, run_id="run-partial-1")
    result = await _run_workflow(req, rec)

    assert result == ["image_001.png", "image_002.png", "image_003.png"]
    # Scene 0 → fal, scenes 1 and 2 → comfyui (out-of-bounds fallback)
    assert len(rec.calls["start_image_generation_provider"]) == 1
    assert len(rec.calls["start_image_generation"]) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 7 — missing image_prompt → non-retryable failure + failed webhook
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_image_prompt_fails_with_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", False)
    rec = _Recorder()
    # Scene 1 is missing "image_prompt" entirely
    rec.legacy_prompts = [
        {"image_prompt": "scene-1-image"},
        {"video_prompt": "scene-2-video-only"},
    ]

    req = _make_request(with_brief=False, run_id="run-fail-1")
    with pytest.raises(WorkflowFailureError):
        await _run_workflow(req, rec)

    # Failure webhook was called with status="failed"
    assert rec.called("send_image_generation_webhook")
    status, _, _, failure_reason, _, _ = rec.calls["send_image_generation_webhook"][0]
    assert status == "failed"
    assert failure_reason is not None
    assert "image_prompt" in failure_reason.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 8 — target_resolution="1080p" → image dims capped at 720p (720×1280)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_dimensions_capped_at_720p(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", False)
    rec = _Recorder()
    rec.legacy_prompts = [{"image_prompt": "scene-1-image"}]

    req = _make_request(
        with_brief=False,
        video_format="9:16",
        target_resolution="1080p",
        run_id="run-cap-1",
    )
    await _run_workflow(req, rec)

    # Inspect the dims the workflow passed to start_image_generation
    idx, width, height, _prompt = rec.calls["start_image_generation"][0]
    assert (width, height) == (720, 1280)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 9 — video_format/target_resolution both None → default 9:16 / 720p
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_defaults_to_9_16_720p_when_fields_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", False)
    rec = _Recorder()
    rec.legacy_prompts = [{"image_prompt": "scene-1-image"}]

    req = _make_request(
        with_brief=False,
        video_format=None,
        target_resolution=None,
        run_id="run-default-1",
    )
    await _run_workflow(req, rec)

    idx, width, height, _prompt = rec.calls["start_image_generation"][0]
    assert (width, height) == (720, 1280)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 10 — success webhook carries video_idea_id and platform
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_forwards_video_idea_id_and_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflows_module, "SCENE_CLASSIFIER_ENABLED", False)
    rec = _Recorder()

    req_kwargs: Dict[str, Any] = {
        "user_id": "user-1",
        "script": "Test",
        "language": "en",
        "image_style": "default",
        "run_id": "run-webhook-1",
        "workflow_id": "wf-webhook-1",
        "user_access_token": "jwt",
        "video_idea_id": "vid-42",
        "platform": "LinkedIn",
        "brief": _make_brief(num_scenes=1),
    }
    req = ImageGenerationStartRequest(**req_kwargs)
    await _run_workflow(req, rec)

    status, _files, _prompts, failure_reason, video_idea_id, platform = rec.calls[
        "send_image_generation_webhook"
    ][0]
    assert status == "completed"
    assert failure_reason is None
    assert video_idea_id == "vid-42"
    assert platform == "LinkedIn"
