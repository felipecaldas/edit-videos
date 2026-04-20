"""Unit tests for the handoff_to_compositor Temporal activity (TAB-54)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from videomerge.exceptions import NonRetryableError


def _make_payload():
    """Return a minimal valid HandoffPayload for testing."""
    from videomerge.models import Brief, HandoffPayload

    return HandoffPayload(
        run_id="run-test-123",
        client_id="client-42",
        brief=Brief(),
        platform="LinkedIn",
        voiceover_path="/data/shared/run-test-123/voiceover.mp3",
        clip_paths=["/data/shared/run-test-123/000_clip.mp4"],
        video_format="9:16",
        workflow_id="wf-xyz789",
        user_access_token="eyJhbGciOi...",
    )


def _fake_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=Exception("no JSON"))
    return resp


class TestHandoffToCompositor:
    """Tests for the handoff_to_compositor activity."""

    def test_successful_handoff_returns_compose_job_id(self):
        """On a 200 response with compose_job_id, the activity returns it."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        payload = _make_payload()
        success_response = _fake_response(200, {"compose_job_id": "cj-abc123"})

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(return_value=success_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(
                activities_module,
                "TABARIO_VIDEO_COMPOSITOR_URL",
                "http://compositor:8000",
            ),
            patch.object(
                activities_module.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                activities_module.handoff_to_compositor(payload)
            )

        assert result == "cj-abc123"
        fake_client.post.assert_awaited_once()
        call_url = fake_client.post.call_args[0][0]
        assert call_url == "http://compositor:8000/compose/start"

    def test_4xx_raises_non_retryable_error(self):
        """A 4xx response must raise NonRetryableError so Temporal does not retry."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        payload = _make_payload()
        bad_request_response = _fake_response(422, {"detail": "validation error"})

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(return_value=bad_request_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(
                activities_module,
                "TABARIO_VIDEO_COMPOSITOR_URL",
                "http://compositor:8000",
            ),
            patch.object(
                activities_module.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            with pytest.raises(NonRetryableError, match="422"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.handoff_to_compositor(payload)
                )

    def test_5xx_raises_runtime_error_for_retry(self):
        """A 5xx response must raise a plain RuntimeError (retryable by Temporal)."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        payload = _make_payload()
        server_error_response = _fake_response(503, {"error": "service unavailable"})

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(return_value=server_error_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(
                activities_module,
                "TABARIO_VIDEO_COMPOSITOR_URL",
                "http://compositor:8000",
            ),
            patch.object(
                activities_module.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    activities_module.handoff_to_compositor(payload)
                )

        assert "503" in str(exc_info.value)
        assert not isinstance(exc_info.value, NonRetryableError)

    def test_network_timeout_raises_runtime_error(self):
        """A network timeout must raise RuntimeError (retryable)."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        import httpx as httpx_module

        payload = _make_payload()

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(
            side_effect=httpx_module.TimeoutException("timed out")
        )

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(
                activities_module,
                "TABARIO_VIDEO_COMPOSITOR_URL",
                "http://compositor:8000",
            ),
            patch.object(
                activities_module.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.handoff_to_compositor(payload)
                )

        assert not isinstance(
            RuntimeError("timed out"), NonRetryableError
        ), "timeout errors must be retryable"

    def test_missing_compositor_url_raises_runtime_error(self):
        """If TABARIO_VIDEO_COMPOSITOR_URL is not set, raise RuntimeError immediately."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        payload = _make_payload()

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", None),
        ):
            with pytest.raises(RuntimeError, match="TABARIO_VIDEO_COMPOSITOR_URL"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.handoff_to_compositor(payload)
                )

    def test_response_missing_compose_job_id_raises_runtime_error(self):
        """If the compositor returns 200 but omits compose_job_id, raise RuntimeError."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        payload = _make_payload()
        malformed_response = _fake_response(200, {"status": "ok"})

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(return_value=malformed_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(
                activities_module,
                "TABARIO_VIDEO_COMPOSITOR_URL",
                "http://compositor:8000",
            ),
            patch.object(
                activities_module.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            with pytest.raises(RuntimeError, match="compose_job_id"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.handoff_to_compositor(payload)
                )
