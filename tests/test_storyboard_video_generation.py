"""Unit tests for the StoryBoardVideoGeneration Temporal workflow (TAB-123 / TAB-125).

These tests complement ``test_tab56_tab57_workflow_handoff.py`` (which covers the
compositor handoff branch). They exercise the remaining paths to bring
``StoryBoardVideoGeneration.run`` coverage to ≥ 90%:

- runpod provider success (legacy tail)
- fal provider success (legacy tail)
- resumed run: some scenes already generated, remainder generated and reassembled in order
- empty scene output → non-retryable ``ApplicationError``
- top-level exception (setup_run_directory fails) → failure webhook + raise
- legacy-tail activity ordering
- regression: handoff failure sends the failure webhook exactly once (TAB-124)

All tests patch ``videomerge.temporal.workflows.workflow`` so the workflow body
runs as a normal coroutine without a Temporal worker.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


MOD = "videomerge.temporal.workflows"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_req(
    handoff_to_compositor=False,
    brief=False,
    platform=None,
    client_id=None,
    run_id="run-sb-xyz",
):
    try:
        from videomerge.models import StoryboardVideoGenerationRequest, Brief
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"import failed: {exc}")

    kwargs = dict(
        user_id="u1",
        script="a storyboard script",
        user_access_token="tok-abc",
        run_id=run_id,
        workflow_id=f"wf-{run_id}",
        video_format="9:16",
        target_resolution="720p",
        handoff_to_compositor=handoff_to_compositor,
    )
    if brief:
        kwargs["brief"] = Brief()
    if platform is not None:
        kwargs["platform"] = platform
    if client_id is not None:
        kwargs["client_id"] = client_id
    return StoryboardVideoGenerationRequest(**kwargs)


def _scene(index: int):
    return {
        "index": index,
        "video_prompt": f"vp-{index}",
        "image_path": f"/data/shared/run-sb-xyz/image_{index:03d}.png",
    }


def _make_workflow_mock():
    """Return a MagicMock configured as a stand-in for ``temporalio.workflow``."""
    mock_wf = MagicMock()
    mock_wf.execute_activity = AsyncMock()
    mock_wf.start_activity = AsyncMock()
    mock_wf.logger = MagicMock()
    mock_wf.info.return_value = MagicMock(parent=None)
    return mock_wf


class _ActivityRecorder:
    """Records calls to ``execute_activity`` + ``start_activity`` by activity name.

    Handlers may be registered per activity name; missing handlers default to a
    MagicMock return value so the workflow body continues executing.
    """

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._handlers: dict[str, object] = {}

    def register(self, name: str, value):
        self._handlers[name] = value

    def _resolve(self, fn, args, kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, tuple(args or ()), dict(kwargs or {})))
        handler = self._handlers.get(name)
        if callable(handler):
            result = handler(*(args or ()), **(kwargs or {}))
            return result
        if handler is not None:
            return handler
        return MagicMock()

    async def execute_activity(self, fn, args=None, **kwargs):
        value = self._resolve(fn, args, kwargs)
        if isinstance(value, Exception):
            raise value
        return value

    async def start_activity(self, fn, args=None, **kwargs):
        # The workflow body does `await asyncio.gather(*start_tasks)` where each
        # start_task is the coroutine produced by `workflow.start_activity(...)`.
        # With AsyncMock(side_effect=self.start_activity), that coroutine resolves
        # to the return value of this method — so we return the value directly.
        value = self._resolve(fn, args, kwargs)
        if isinstance(value, Exception):
            raise value
        return value

    def names(self) -> list[str]:
        return [name for name, _a, _k in self.calls]

    def count(self, name: str) -> int:
        return sum(1 for n in self.names() if n == name)

    def webhook_status_calls(self) -> list[str]:
        """Return the second positional arg (status) of every send_completion_webhook call."""
        out: list[str] = []
        for name, args, _k in self.calls:
            if name != "send_completion_webhook":
                continue
            # args == (run_id, status, ...) when passed via args=[...]
            if len(args) >= 2:
                out.append(args[1])
        return out


# ---------------------------------------------------------------------------
# Shared patched-workflow harness
# ---------------------------------------------------------------------------

def _with_patched_workflow(req, recorder: _ActivityRecorder, provider: str = "fal"):
    """Execute ``StoryBoardVideoGeneration.run(req)`` with the workflow module mocked.

    Patches:
      - workflows.workflow (execute_activity, start_activity, logger, info)
      - workflows.asyncio.gather — async generators/coroutines in workflows.py
        call gather on awaitables returned by start_activity; since those are
        regular coroutines in tests, passthrough works.
      - workflows.VIDEO_PROVIDER to select runpod vs fal branch.
    """
    try:
        from videomerge.temporal.workflows import StoryBoardVideoGeneration
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"import failed: {exc}")

    wf = StoryBoardVideoGeneration()

    mock_wf = _make_workflow_mock()
    mock_wf.execute_activity.side_effect = recorder.execute_activity
    mock_wf.start_activity.side_effect = recorder.start_activity

    with patch(f"{MOD}.workflow", mock_wf), \
         patch(f"{MOD}.VIDEO_PROVIDER", provider):
        return _run(wf.run(req))


# ===========================================================================
# Tests — success paths (legacy tail)
# ===========================================================================

class TestSuccessPathsLegacyTail:
    """Non-handoff runs that exercise stitch/subtitles/upload/webhook."""

    def _legacy_recorder(self, scene_inputs, existing_clips=None, provider_job="job-1"):
        rec = _ActivityRecorder()
        rec.register("setup_run_directory", "/data/shared/run-sb-xyz/")
        rec.register("generate_voiceover", "/data/shared/run-sb-xyz/voiceover.mp3")
        rec.register("load_storyboard_scene_inputs", list(scene_inputs))
        rec.register("list_existing_video_clips", dict(existing_clips or {}))
        rec.register("start_video_generation_provider", provider_job)

        def _poll(*args, **_kw):
            # args == (provider, job_id, run_id, scene_index, ...)
            idx = args[3] if len(args) >= 4 else 0
            return [f"/data/shared/run-sb-xyz/{int(idx):03d}_clip.mp4"]

        rec.register("poll_video_generation_provider", _poll)
        rec.register("stitch_videos", "/data/shared/run-sb-xyz/stitched.mp4")
        rec.register("burn_subtitles_into_video", "/data/shared/run-sb-xyz/final.mp4")
        rec.register("upload_final_video_output", "user-1/run-sb-xyz/final.mp4")
        rec.register("send_completion_webhook", None)
        return rec

    def test_runpod_success_legacy_tail(self):
        """Two scenes, runpod provider, legacy tail invoked in order, ordered clip paths."""
        req = _make_req(handoff_to_compositor=False)
        rec = self._legacy_recorder(scene_inputs=[_scene(0), _scene(1)])

        final_path = _with_patched_workflow(req, rec, provider="runpod")

        assert final_path == "/data/shared/run-sb-xyz/final.mp4"
        # runpod branch starts & polls 2 activities
        assert rec.count("start_video_generation_provider") == 2
        assert rec.count("poll_video_generation_provider") == 2
        # legacy tail ran
        assert rec.count("stitch_videos") == 1
        assert rec.count("burn_subtitles_into_video") == 1
        assert rec.count("upload_final_video_output") == 1
        # exactly one completion webhook, and it is "completed"
        assert rec.count("send_completion_webhook") == 1
        assert rec.webhook_status_calls() == ["completed"]
        # handoff activity NOT invoked
        assert rec.count("handoff_to_compositor") == 0

        # Verify stitch received ordered clip paths
        stitch_call = next(c for c in rec.calls if c[0] == "stitch_videos")
        _, stitch_args, _ = stitch_call
        _run_id, clip_paths, _voiceover = stitch_args
        assert clip_paths == [
            "/data/shared/run-sb-xyz/000_clip.mp4",
            "/data/shared/run-sb-xyz/001_clip.mp4",
        ]

    def test_fal_success_legacy_tail(self):
        """Single scene, fal provider, legacy tail completes and returns final path."""
        req = _make_req(handoff_to_compositor=False)
        rec = self._legacy_recorder(scene_inputs=[_scene(0)])

        final_path = _with_patched_workflow(req, rec, provider="fal")

        assert final_path == "/data/shared/run-sb-xyz/final.mp4"
        assert rec.count("start_video_generation_provider") == 1
        assert rec.count("poll_video_generation_provider") == 1
        # fal poll passes the FAL model as a trailing arg — verify we took that branch
        poll_call = next(c for c in rec.calls if c[0] == "poll_video_generation_provider")
        _, poll_args, _ = poll_call
        assert poll_args[0] == "fal"

    def test_resumed_run_skips_existing_clips(self):
        """list_existing_video_clips returns one already-completed scene; only the
        missing scene is regenerated, and the final video_paths preserves order."""
        req = _make_req(handoff_to_compositor=False)
        existing = {"0": ["/data/shared/run-sb-xyz/000_clip.mp4"]}
        rec = self._legacy_recorder(
            scene_inputs=[_scene(0), _scene(1)],
            existing_clips=existing,
        )

        final_path = _with_patched_workflow(req, rec, provider="fal")

        assert final_path == "/data/shared/run-sb-xyz/final.mp4"
        # Only one scene should have been generated (scene index 1)
        assert rec.count("start_video_generation_provider") == 1
        assert rec.count("poll_video_generation_provider") == 1
        start_call = next(c for c in rec.calls if c[0] == "start_video_generation_provider")
        _, start_args, _ = start_call
        # start_video_generation_provider args: (provider, video_prompt, image_path, model, w, h, index)
        assert start_args[-1] == 1
        # Stitch received clips in scene order (existing first, new second)
        stitch_call = next(c for c in rec.calls if c[0] == "stitch_videos")
        _, stitch_args, _ = stitch_call
        assert stitch_args[1] == [
            "/data/shared/run-sb-xyz/000_clip.mp4",
            "/data/shared/run-sb-xyz/001_clip.mp4",
        ]

    def test_all_clips_already_exist_skips_generation_entirely(self):
        """When every scene is in existing_clips, the provider activities are never invoked."""
        req = _make_req(handoff_to_compositor=False)
        existing = {
            "0": ["/data/shared/run-sb-xyz/000_clip.mp4"],
            "1": ["/data/shared/run-sb-xyz/001_clip.mp4"],
        }
        rec = self._legacy_recorder(
            scene_inputs=[_scene(0), _scene(1)],
            existing_clips=existing,
        )

        final_path = _with_patched_workflow(req, rec, provider="runpod")

        assert final_path == "/data/shared/run-sb-xyz/final.mp4"
        assert rec.count("start_video_generation_provider") == 0
        assert rec.count("poll_video_generation_provider") == 0
        assert rec.count("stitch_videos") == 1


# ===========================================================================
# Tests — failure paths
# ===========================================================================

class TestFailurePaths:
    """Error branches: empty scene output, top-level exception, double-webhook regression."""

    def test_empty_scene_output_raises_non_retryable(self):
        """poll_video_generation_provider returning [] should raise ApplicationError(non_retryable=True)."""
        from temporalio.exceptions import ApplicationError

        req = _make_req(handoff_to_compositor=False)
        rec = _ActivityRecorder()
        rec.register("setup_run_directory", "/data/shared/run-sb-xyz/")
        rec.register("generate_voiceover", "/data/shared/run-sb-xyz/voiceover.mp3")
        rec.register("load_storyboard_scene_inputs", [_scene(0)])
        rec.register("list_existing_video_clips", {})
        rec.register("start_video_generation_provider", "job-1")
        rec.register("poll_video_generation_provider", [])  # empty list → error
        rec.register("send_completion_webhook", None)

        with pytest.raises(ApplicationError) as excinfo:
            _with_patched_workflow(req, rec, provider="fal")

        assert "No video output generated for scene" in str(excinfo.value)
        # Failure webhook sent exactly once from the outer handler
        assert rec.count("send_completion_webhook") == 1
        assert rec.webhook_status_calls() == ["failed"]
        # Legacy tail never started
        assert rec.count("stitch_videos") == 0

    def test_setup_run_directory_failure_sends_webhook_and_raises(self):
        """Top-level exception path: setup_run_directory fails → failure webhook + ApplicationError."""
        from temporalio.exceptions import ApplicationError

        req = _make_req(handoff_to_compositor=False)
        rec = _ActivityRecorder()
        rec.register("setup_run_directory", RuntimeError("disk full"))
        rec.register("send_completion_webhook", None)

        with pytest.raises(ApplicationError) as excinfo:
            _with_patched_workflow(req, rec, provider="fal")

        assert "Storyboard video generation workflow" in str(excinfo.value)
        assert "failed" in str(excinfo.value)
        # Exactly one failure webhook
        assert rec.count("send_completion_webhook") == 1
        assert rec.webhook_status_calls() == ["failed"]
        # No downstream activities ran
        assert rec.count("generate_voiceover") == 0
        assert rec.count("stitch_videos") == 0
        assert rec.count("handoff_to_compositor") == 0

    def test_handoff_failure_sends_exactly_one_failure_webhook(self):
        """Regression for TAB-124: handoff activity failure must not trigger a duplicate webhook."""
        from temporalio.exceptions import ApplicationError

        req = _make_req(
            handoff_to_compositor=True,
            brief=True,
            platform="LinkedIn",
            client_id="client-42",
        )
        rec = _ActivityRecorder()
        rec.register("setup_run_directory", "/data/shared/run-sb-xyz/")
        rec.register("generate_voiceover", "/data/shared/run-sb-xyz/voiceover.mp3")
        rec.register("load_storyboard_scene_inputs", [_scene(0)])
        rec.register("list_existing_video_clips", {})
        rec.register("start_video_generation_provider", "job-1")
        rec.register(
            "poll_video_generation_provider",
            ["/data/shared/run-sb-xyz/000_clip.mp4"],
        )
        rec.register("handoff_to_compositor", RuntimeError("compositor 503"))
        rec.register("send_completion_webhook", None)

        with pytest.raises(ApplicationError) as excinfo:
            _with_patched_workflow(req, rec, provider="fal")

        assert "Handoff to compositor failed" in str(excinfo.value)
        # Exactly one failure webhook, even though the outer handler also ran.
        assert rec.count("send_completion_webhook") == 1
        assert rec.webhook_status_calls() == ["failed"]
        # Legacy tail never ran
        assert rec.count("stitch_videos") == 0
        assert rec.count("burn_subtitles_into_video") == 0


# ===========================================================================
# Tests — effective_handoff auto-computation
# ===========================================================================

class TestEffectiveHandoffAutoCompute:
    """When handoff_to_compositor is None, it should auto-compute from brief+platform+client_id."""

    def _handoff_recorder(self):
        rec = _ActivityRecorder()
        rec.register("setup_run_directory", "/data/shared/run-sb-xyz/")
        rec.register("generate_voiceover", "/data/shared/run-sb-xyz/voiceover.mp3")
        rec.register("load_storyboard_scene_inputs", [_scene(0)])
        rec.register("list_existing_video_clips", {})
        rec.register("start_video_generation_provider", "job-1")
        rec.register(
            "poll_video_generation_provider",
            ["/data/shared/run-sb-xyz/000_clip.mp4"],
        )
        rec.register("handoff_to_compositor", "compose-job-1")
        rec.register("poll_compose_status", "/data/shared/run-sb-xyz/composed.mp4")
        rec.register("upload_final_video_output", "user-1/run-sb-xyz/composed.mp4")
        rec.register("send_completion_webhook", None)
        return rec

    def test_auto_handoff_when_brief_platform_client_id_all_present(self):
        """handoff_to_compositor=None + brief + platform + client_id ⇒ handoff path selected."""
        # Build with explicit None via pydantic default
        try:
            from videomerge.models import StoryboardVideoGenerationRequest, Brief
        except ImportError as exc:  # pragma: no cover
            pytest.skip(f"import failed: {exc}")
        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="s",
            user_access_token="tok",
            run_id="run-sb-xyz",
            workflow_id="wf-sb-xyz",
            video_format="9:16",
            target_resolution="720p",
            brief=Brief(),
            platform="LinkedIn",
            client_id="client-42",
            # handoff_to_compositor intentionally omitted → None
        )
        rec = self._handoff_recorder()

        final_path = _with_patched_workflow(req, rec, provider="fal")

        assert final_path == "/data/shared/run-sb-xyz/composed.mp4"
        assert rec.count("handoff_to_compositor") == 1
        assert rec.count("stitch_videos") == 0

    def test_auto_legacy_when_brief_missing(self):
        """Without brief/platform/client_id, auto-compute is False → legacy tail runs."""
        try:
            from videomerge.models import StoryboardVideoGenerationRequest
        except ImportError as exc:  # pragma: no cover
            pytest.skip(f"import failed: {exc}")
        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="s",
            user_access_token="tok",
            run_id="run-sb-xyz",
            workflow_id="wf-sb-xyz",
            video_format="9:16",
            target_resolution="720p",
        )
        rec = _ActivityRecorder()
        rec.register("setup_run_directory", "/data/shared/run-sb-xyz/")
        rec.register("generate_voiceover", "/data/shared/run-sb-xyz/voiceover.mp3")
        rec.register("load_storyboard_scene_inputs", [_scene(0)])
        rec.register("list_existing_video_clips", {})
        rec.register("start_video_generation_provider", "job-1")
        rec.register(
            "poll_video_generation_provider",
            ["/data/shared/run-sb-xyz/000_clip.mp4"],
        )
        rec.register("stitch_videos", "/data/shared/run-sb-xyz/stitched.mp4")
        rec.register("burn_subtitles_into_video", "/data/shared/run-sb-xyz/final.mp4")
        rec.register("upload_final_video_output", "user-1/run-sb-xyz/final.mp4")
        rec.register("send_completion_webhook", None)

        final_path = _with_patched_workflow(req, rec, provider="fal")

        assert final_path == "/data/shared/run-sb-xyz/final.mp4"
        assert rec.count("handoff_to_compositor") == 0
        assert rec.count("stitch_videos") == 1
