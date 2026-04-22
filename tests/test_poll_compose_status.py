"""Unit tests for the poll_compose_status Temporal activity (TAB-87/TAB-89)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from videomerge.exceptions import NonRetryableError


def _fake_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=Exception("no JSON"))
    return resp


def _make_fake_client(response: MagicMock) -> MagicMock:
    """Return a mock AsyncClient context manager that always returns the given response."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    return client


class TestPollComposeStatus:
    """Tests for the poll_compose_status activity."""

    def test_done_status_returns_final_video_path(self):
        """When compositor responds status=done with final_video_path, the path is returned."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        done_response = _fake_response(200, {
            "status": "done",
            "final_video_path": "/data/shared/run-123/final.mp4",
        })
        fake_client = _make_fake_client(done_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", new_callable=AsyncMock),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                activities_module.poll_compose_status(
                    compose_job_id="cj-abc123",
                    run_id="run-123",
                    poll_interval_seconds=0.01,
                )
            )

        assert result == "/data/shared/run-123/final.mp4"
        fake_client.get.assert_awaited_once()
        call_url = fake_client.get.call_args[0][0]
        assert call_url == "http://compositor:9312/compose/cj-abc123"

    def test_failed_status_raises_non_retryable_error(self):
        """When compositor responds status=failed, NonRetryableError is raised immediately."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        failed_response = _fake_response(200, {
            "status": "failed",
            "error": "render pipeline crashed",
        })
        fake_client = _make_fake_client(failed_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(NonRetryableError, match="cj-abc123"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.poll_compose_status(
                        compose_job_id="cj-abc123",
                        run_id="run-123",
                        poll_interval_seconds=0.01,
                    )
                )

    def test_missing_compositor_url_raises_runtime_error(self):
        """If TABARIO_VIDEO_COMPOSITOR_URL is not set, RuntimeError is raised before any HTTP call."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", None),
        ):
            with pytest.raises(RuntimeError, match="TABARIO_VIDEO_COMPOSITOR_URL"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.poll_compose_status(
                        compose_job_id="cj-abc123",
                        run_id="run-123",
                    )
                )

    def test_pending_then_done_polls_multiple_times(self):
        """A pending response followed by done should poll twice before returning."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        pending_response = _fake_response(200, {"status": "pending"})
        done_response = _fake_response(200, {
            "status": "done",
            "final_video_path": "/data/shared/run-456/final.mp4",
        })

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.get = AsyncMock(side_effect=[pending_response, done_response])

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", new_callable=AsyncMock),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                activities_module.poll_compose_status(
                    compose_job_id="cj-xyz",
                    run_id="run-456",
                    poll_interval_seconds=0.01,
                    timeout_seconds=5.0,
                )
            )

        assert result == "/data/shared/run-456/final.mp4"
        assert fake_client.get.await_count == 2

    def test_timeout_raises_runtime_error(self):
        """If polling exceeds timeout_seconds, RuntimeError is raised."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        pending_response = _fake_response(200, {"status": "pending"})
        fake_client = _make_fake_client(pending_response)

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", side_effect=fake_sleep),
        ):
            with pytest.raises(RuntimeError, match="Timed out"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.poll_compose_status(
                        compose_job_id="cj-timeout",
                        run_id="run-timeout",
                        poll_interval_seconds=0.5,
                        timeout_seconds=0.9,
                    )
                )

        assert len(sleep_calls) > 0

    def test_network_error_retries_and_eventually_succeeds(self):
        """A transient network error should be swallowed and retried until success."""
        try:
            from videomerge.temporal import activities as activities_module
            import httpx as httpx_module
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        done_response = _fake_response(200, {
            "status": "done",
            "final_video_path": "/data/shared/run-789/final.mp4",
        })

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.get = AsyncMock(side_effect=[
            httpx_module.RequestError("connection refused"),
            done_response,
        ])

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", new_callable=AsyncMock),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                activities_module.poll_compose_status(
                    compose_job_id="cj-retry",
                    run_id="run-789",
                    poll_interval_seconds=0.01,
                    timeout_seconds=5.0,
                )
            )

        assert result == "/data/shared/run-789/final.mp4"
        assert fake_client.get.await_count == 2

    def test_done_without_final_video_path_raises_runtime_error(self):
        """If compositor returns status=done but omits final_video_path, RuntimeError is raised."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        bad_done_response = _fake_response(200, {"status": "done"})
        fake_client = _make_fake_client(bad_done_response)

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(RuntimeError, match="final_video_path is missing"):
                asyncio.get_event_loop().run_until_complete(
                    activities_module.poll_compose_status(
                        compose_job_id="cj-badresp",
                        run_id="run-bad",
                        poll_interval_seconds=0.01,
                    )
                )

    def test_5xx_response_retries_not_raises(self):
        """A 5xx HTTP error from the compositor should be treated as transient — retry, not raise."""
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as exc:
            pytest.skip(f"videomerge.temporal.activities import failed: {exc}")

        error_response = _fake_response(503)
        done_response = _fake_response(200, {
            "status": "done",
            "final_video_path": "/data/shared/run-503/final.mp4",
        })

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.get = AsyncMock(side_effect=[error_response, done_response])

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "TABARIO_VIDEO_COMPOSITOR_URL", "http://compositor:9312"),
            patch.object(activities_module.httpx, "AsyncClient", return_value=fake_client),
            patch.object(activities_module.asyncio, "sleep", new_callable=AsyncMock),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                activities_module.poll_compose_status(
                    compose_job_id="cj-503",
                    run_id="run-503",
                    poll_interval_seconds=0.01,
                    timeout_seconds=5.0,
                )
            )

        assert result == "/data/shared/run-503/final.mp4"
        assert fake_client.get.await_count == 2
