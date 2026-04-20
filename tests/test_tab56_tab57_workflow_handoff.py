"""Unit tests for TAB-56 + TAB-57: compositor handoff branching in both workflows.

TAB-56 — VideoGenerationWorkflow (/orchestrate/start):
  - handoff_to_compositor=True → calls handoff_to_compositor activity, skips legacy tail
  - handoff_to_compositor=False → calls legacy tail (stitch/subtitles/webhook), skips handoff
  - handoff activity failure → sends failure webhook and raises ApplicationError

TAB-57 — StoryBoardVideoGeneration (/orchestrate/generate-videos):
  - handoff_to_compositor=True → calls handoff_to_compositor activity, skips legacy tail
  - handoff_to_compositor=False → calls legacy tail, skips handoff
  - handoff activity failure → sends failure webhook and raises ApplicationError
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_brief():
    try:
        from videomerge.models import Brief
        return Brief()
    except ImportError:
        return MagicMock()


def _make_orchestrate_start_req(handoff_to_compositor=True, client_id="client-42"):
    try:
        from videomerge.models import OrchestrateStartRequest, Brief
        return OrchestrateStartRequest(
            user_id="u1",
            script="hello world",
            caption="cap",
            run_id="run-vgw-123",
            workflow_id="wf-vgw-123",
            image_style="default",
            video_format="9:16",
            target_resolution="720p",
            brief=Brief(),
            platform="LinkedIn",
            client_id=client_id,
            handoff_to_compositor=handoff_to_compositor,
        )
    except ImportError as exc:
        pytest.skip(f"import failed: {exc}")


def _make_storyboard_req(handoff_to_compositor=True, client_id="client-42"):
    try:
        from videomerge.models import StoryboardVideoGenerationRequest, Brief
        return StoryboardVideoGenerationRequest(
            user_id="u1",
            script="storyboard script",
            user_access_token="tok-abc",
            run_id="run-sb-123",
            workflow_id="wf-sb-123",
            video_format="9:16",
            target_resolution="720p",
            brief=Brief(),
            platform="LinkedIn",
            client_id=client_id,
            handoff_to_compositor=handoff_to_compositor,
        )
    except ImportError as exc:
        pytest.skip(f"import failed: {exc}")


def _patch_workflow_module():
    """Return a context-manager-compatible patch target string prefix."""
    return "videomerge.temporal.workflows"


# ---------------------------------------------------------------------------
# TAB-56: VideoGenerationWorkflow
# ---------------------------------------------------------------------------

class TestVideoGenerationWorkflowHandoff:
    """Integration-style unit tests for the VideoGenerationWorkflow handoff branch."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_handoff_true_calls_handoff_activity_not_stitch(self):
        """When handoff_to_compositor=True, handoff_to_compositor is called; stitch_videos is NOT."""
        try:
            from videomerge.temporal.workflows import VideoGenerationWorkflow
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_orchestrate_start_req(handoff_to_compositor=True)
        wf = VideoGenerationWorkflow()

        activity_calls = []

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "setup_run_directory":
                return "/data/shared/run-vgw-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-vgw-123/voiceover.mp3"
            if name == "generate_scene_prompts":
                return [{"image_prompt": "img1", "video_prompt": "vid1"}]
            if name == "handoff_to_compositor":
                return "cj-compose-001"
            return MagicMock()

        async def fake_execute_child_workflow(fn, args=None, **kwargs):
            return ["/data/shared/run-vgw-123/000_clip.mp4"]

        mock_workflow_module = MagicMock()
        mock_workflow_module.execute_activity = fake_execute_activity
        mock_workflow_module.execute_child_workflow = fake_execute_child_workflow
        mock_workflow_module.logger = MagicMock()
        mock_workflow_module.info.return_value = MagicMock()

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.execute_child_workflow = AsyncMock(side_effect=fake_execute_child_workflow)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(
                workflow_id="wf-parent",
                run_id="run-parent",
                parent=None,
            )

            result = self._run(wf.run(req))

        assert result == "cj-compose-001"
        assert "handoff_to_compositor" in activity_calls
        assert "stitch_videos" not in activity_calls
        assert "burn_subtitles_into_video" not in activity_calls
        assert "send_completion_webhook" not in activity_calls

    def test_handoff_false_calls_legacy_tail_not_handoff(self):
        """When handoff_to_compositor=False, legacy tail runs; handoff_to_compositor is NOT called."""
        try:
            from videomerge.temporal.workflows import VideoGenerationWorkflow
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_orchestrate_start_req(handoff_to_compositor=False)
        wf = VideoGenerationWorkflow()

        activity_calls = []

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "setup_run_directory":
                return "/data/shared/run-vgw-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-vgw-123/voiceover.mp3"
            if name == "generate_scene_prompts":
                return [{"image_prompt": "img1", "video_prompt": "vid1"}]
            if name == "stitch_videos":
                return "/data/shared/run-vgw-123/stitched.mp4"
            if name == "burn_subtitles_into_video":
                return "/data/shared/run-vgw-123/final.mp4"
            if name == "send_completion_webhook":
                return None
            return MagicMock()

        async def fake_execute_child_workflow(fn, args=None, **kwargs):
            return ["/data/shared/run-vgw-123/000_clip.mp4"]

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.execute_child_workflow = AsyncMock(side_effect=fake_execute_child_workflow)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(
                workflow_id="wf-parent",
                run_id="run-parent",
                parent=None,
            )

            result = self._run(wf.run(req))

        assert result == "/data/shared/run-vgw-123/final.mp4"
        assert "stitch_videos" in activity_calls
        assert "burn_subtitles_into_video" in activity_calls
        assert "send_completion_webhook" in activity_calls
        assert "handoff_to_compositor" not in activity_calls

    def test_handoff_failure_sends_webhook_and_raises(self):
        """When the handoff activity raises, a failure webhook is sent and ApplicationError is raised."""
        try:
            from videomerge.temporal.workflows import VideoGenerationWorkflow
            from temporalio.exceptions import ApplicationError
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_orchestrate_start_req(handoff_to_compositor=True)
        wf = VideoGenerationWorkflow()

        activity_calls = []

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "setup_run_directory":
                return "/data/shared/run-vgw-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-vgw-123/voiceover.mp3"
            if name == "generate_scene_prompts":
                return [{"image_prompt": "img1", "video_prompt": "vid1"}]
            if name == "handoff_to_compositor":
                raise RuntimeError("compositor is down")
            if name == "send_completion_webhook":
                return None
            return MagicMock()

        async def fake_execute_child_workflow(fn, args=None, **kwargs):
            return ["/data/shared/run-vgw-123/000_clip.mp4"]

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.execute_child_workflow = AsyncMock(side_effect=fake_execute_child_workflow)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(
                workflow_id="wf-parent",
                run_id="run-parent",
                parent=None,
            )

            with pytest.raises(ApplicationError, match="Handoff to compositor failed"):
                self._run(wf.run(req))

        assert "handoff_to_compositor" in activity_calls
        assert "send_completion_webhook" in activity_calls
        assert "stitch_videos" not in activity_calls

    def test_handoff_builds_payload_with_correct_fields(self):
        """HandoffPayload passed to the activity uses run_id, clip_paths, voiceover_path from workflow state."""
        try:
            from videomerge.temporal.workflows import VideoGenerationWorkflow
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_orchestrate_start_req(handoff_to_compositor=True)
        wf = VideoGenerationWorkflow()

        captured_payload = {}

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            if name == "setup_run_directory":
                return "/data/shared/run-vgw-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-vgw-123/voiceover.mp3"
            if name == "generate_scene_prompts":
                return [{"image_prompt": "img1", "video_prompt": "vid1"}]
            if name == "handoff_to_compositor":
                captured_payload["payload"] = args[0] if args else None
                return "cj-xyz"
            return MagicMock()

        async def fake_execute_child_workflow(fn, args=None, **kwargs):
            return ["/data/shared/run-vgw-123/000_clip.mp4"]

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.execute_child_workflow = AsyncMock(side_effect=fake_execute_child_workflow)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(
                workflow_id="wf-parent",
                run_id="run-parent",
                parent=None,
            )

            self._run(wf.run(req))

        payload = captured_payload.get("payload")
        assert payload is not None
        assert payload.run_id == "run-vgw-123"
        assert payload.client_id == "client-42"
        assert payload.platform == "LinkedIn"
        assert payload.voiceover_path == "/data/shared/run-vgw-123/voiceover.mp3"
        assert "/data/shared/run-vgw-123/000_clip.mp4" in payload.clip_paths
        assert payload.video_format == "9:16"
        assert payload.workflow_id == "wf-vgw-123"


# ---------------------------------------------------------------------------
# TAB-57: StoryBoardVideoGeneration
# ---------------------------------------------------------------------------

class TestStoryBoardVideoGenerationHandoff:
    """Integration-style unit tests for the StoryBoardVideoGeneration handoff branch."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_handoff_true_calls_handoff_activity_not_stitch(self):
        """When handoff_to_compositor=True, handoff_to_compositor is called; stitch_videos is NOT."""
        try:
            from videomerge.temporal.workflows import StoryBoardVideoGeneration
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_storyboard_req(handoff_to_compositor=True)
        wf = StoryBoardVideoGeneration()

        activity_calls = []

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "setup_run_directory":
                return "/data/shared/run-sb-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-sb-123/voiceover.mp3"
            if name == "load_storyboard_scene_inputs":
                return [
                    {"index": 0, "video_prompt": "vp1", "image_path": "/data/shared/run-sb-123/image_000.png"},
                ]
            if name == "start_video_generation":
                return "job-001"
            if name == "poll_video_generation":
                return ["/data/shared/run-sb-123/000_clip.mp4"]
            if name == "handoff_to_compositor":
                return "cj-sb-compose-001"
            return MagicMock()

        async def fake_start_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "start_video_generation":
                return "job-001"
            if name == "poll_video_generation":
                return ["/data/shared/run-sb-123/000_clip.mp4"]
            return MagicMock()

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.start_activity = AsyncMock(side_effect=fake_start_activity)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(parent=None)

            with patch(f"{mod}.asyncio.gather", new_callable=AsyncMock) as mock_gather:
                mock_gather.side_effect = [
                    ["job-001"],
                    [["/data/shared/run-sb-123/000_clip.mp4"]],
                ]

                result = self._run(wf.run(req))

        assert result == "cj-sb-compose-001"
        assert "handoff_to_compositor" in activity_calls
        assert "stitch_videos" not in activity_calls
        assert "burn_subtitles_into_video" not in activity_calls
        assert "send_completion_webhook" not in activity_calls

    def test_handoff_false_calls_legacy_tail_not_handoff(self):
        """When handoff_to_compositor=False, legacy tail runs; handoff_to_compositor is NOT called."""
        try:
            from videomerge.temporal.workflows import StoryBoardVideoGeneration
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_storyboard_req(handoff_to_compositor=False)
        wf = StoryBoardVideoGeneration()

        activity_calls = []

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "setup_run_directory":
                return "/data/shared/run-sb-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-sb-123/voiceover.mp3"
            if name == "load_storyboard_scene_inputs":
                return [
                    {"index": 0, "video_prompt": "vp1", "image_path": "/data/shared/run-sb-123/image_000.png"},
                ]
            if name == "stitch_videos":
                return "/data/shared/run-sb-123/stitched.mp4"
            if name == "burn_subtitles_into_video":
                return "/data/shared/run-sb-123/final.mp4"
            if name == "upload_final_video_output":
                return "user-1/run-sb-123/final.mp4"
            if name == "send_completion_webhook":
                return None
            return MagicMock()

        async def fake_start_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            return MagicMock()

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.start_activity = AsyncMock(side_effect=fake_start_activity)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(parent=None)

            with patch(f"{mod}.asyncio.gather", new_callable=AsyncMock) as mock_gather:
                mock_gather.side_effect = [
                    ["job-001"],
                    [["/data/shared/run-sb-123/000_clip.mp4"]],
                ]

                result = self._run(wf.run(req))

        assert result == "/data/shared/run-sb-123/final.mp4"
        assert "stitch_videos" in activity_calls
        assert "burn_subtitles_into_video" in activity_calls
        assert "upload_final_video_output" in activity_calls
        assert "send_completion_webhook" in activity_calls
        assert "handoff_to_compositor" not in activity_calls

    def test_handoff_failure_sends_webhook_and_raises(self):
        """When the handoff activity raises, a failure webhook is sent and ApplicationError is raised."""
        try:
            from videomerge.temporal.workflows import StoryBoardVideoGeneration
            from temporalio.exceptions import ApplicationError
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_storyboard_req(handoff_to_compositor=True)
        wf = StoryBoardVideoGeneration()

        activity_calls = []

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            if name == "setup_run_directory":
                return "/data/shared/run-sb-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-sb-123/voiceover.mp3"
            if name == "load_storyboard_scene_inputs":
                return [
                    {"index": 0, "video_prompt": "vp1", "image_path": "/data/shared/run-sb-123/image_000.png"},
                ]
            if name == "handoff_to_compositor":
                raise RuntimeError("compositor unavailable")
            if name == "send_completion_webhook":
                return None
            return MagicMock()

        async def fake_start_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            activity_calls.append(name)
            return MagicMock()

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.start_activity = AsyncMock(side_effect=fake_start_activity)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(parent=None)

            with patch(f"{mod}.asyncio.gather", new_callable=AsyncMock) as mock_gather:
                mock_gather.side_effect = [
                    ["job-001"],
                    [["/data/shared/run-sb-123/000_clip.mp4"]],
                ]

                with pytest.raises(ApplicationError, match="Handoff to compositor failed"):
                    self._run(wf.run(req))

        assert "handoff_to_compositor" in activity_calls
        assert "send_completion_webhook" in activity_calls
        assert "stitch_videos" not in activity_calls

    def test_handoff_payload_uses_user_access_token(self):
        """HandoffPayload for storyboard workflow includes user_access_token from the request."""
        try:
            from videomerge.temporal.workflows import StoryBoardVideoGeneration
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = _make_storyboard_req(handoff_to_compositor=True)
        wf = StoryBoardVideoGeneration()

        captured_payload = {}

        async def fake_execute_activity(fn, args=None, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            if name == "setup_run_directory":
                return "/data/shared/run-sb-123/"
            if name == "generate_voiceover":
                return "/data/shared/run-sb-123/voiceover.mp3"
            if name == "load_storyboard_scene_inputs":
                return [
                    {"index": 0, "video_prompt": "vp1", "image_path": "/data/shared/run-sb-123/image_000.png"},
                ]
            if name == "handoff_to_compositor":
                captured_payload["payload"] = args[0] if args else None
                return "cj-sb-xyz"
            return MagicMock()

        async def fake_start_activity(fn, args=None, **kwargs):
            return MagicMock()

        mod = _patch_workflow_module()
        with patch(f"{mod}.workflow") as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=fake_execute_activity)
            mock_wf.start_activity = AsyncMock(side_effect=fake_start_activity)
            mock_wf.logger = MagicMock()
            mock_wf.info.return_value = MagicMock(parent=None)

            with patch(f"{mod}.asyncio.gather", new_callable=AsyncMock) as mock_gather:
                mock_gather.side_effect = [
                    ["job-001"],
                    [["/data/shared/run-sb-123/000_clip.mp4"]],
                ]

                self._run(wf.run(req))

        payload = captured_payload.get("payload")
        assert payload is not None
        assert payload.user_access_token == "tok-abc"
        assert payload.run_id == "run-sb-123"
        assert payload.client_id == "client-42"
        assert payload.platform == "LinkedIn"
        assert payload.video_format == "9:16"
        assert payload.workflow_id == "wf-sb-123"
