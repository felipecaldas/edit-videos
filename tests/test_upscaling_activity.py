import asyncio
import base64
import pytest
from unittest.mock import Mock, patch, mock_open


def _subprocess_result(stdout: str) -> Mock:
    result = Mock()
    result.stdout = stdout
    return result


class TestStartVideoUpscaling:
    def test_start_video_upscaling_uses_config_batch_size_and_returns_job_id(self):
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as e:
            pytest.skip(f"videomerge.temporal.activities import failed in this environment: {e}")

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(
                activities_module.subprocess,
                "run",
                side_effect=[
                    _subprocess_result("640x360"),
                    _subprocess_result("300"),
                ],
                autospec=True,
            ) as mock_run,
            patch.object(
                activities_module,
                "open",
                mock_open(read_data=b"fake-mp4-bytes"),
                create=True,
            ),
            patch.object(activities_module, "UPSCALE_BATCH_SIZE", 21),
            patch.object(activities_module, "RUNPOD_BASE_URL", "https://api.runpod.ai"),
            patch.object(activities_module, "RUNPOD_VIDEO_INSTANCE_ID", "instance-123"),
            patch.object(activities_module, "RUNPOD_API_KEY", "test-key"),
            patch.object(activities_module, "COMFY_ORG_API_KEY", "test-comfy-org"),
        ):
            post_called = {"called": False}
            captured = {}

            class _FakeResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self):
                    return {"id": "job-123"}

            class _FakeClient:
                def __init__(self, *args, **kwargs):
                    return None

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def post(self, url, json, headers):
                    post_called["called"] = True
                    captured["url"] = url
                    captured["json"] = json
                    captured["headers"] = headers
                    return _FakeResponse()

            with patch.object(activities_module.httpx, "AsyncClient", _FakeClient):
                job_id = asyncio.run(
                    activities_module.start_video_upscaling(
                        video_id="vid-1",
                        video_path="C:/tmp/input.mp4",
                        target_resolution="1080p",
                    )
                )

            assert job_id == "job-123"
            assert post_called["called"] is True
            assert captured["url"].endswith("/v2/instance-123/run")
            assert captured["headers"]["Authorization"] == "Bearer test-key"
            assert captured["json"]["input"]["batch_size"] == 21
            assert captured["json"]["input"]["output_resolution"] == 1920
            assert mock_run.call_count == 2


class TestSaveUpscaledVideo:
    def test_save_upscaled_video_writes_expected_path(self, tmp_path):
        try:
            from videomerge.temporal import activities as activities_module
        except ImportError as e:
            pytest.skip(f"videomerge.temporal.activities import failed in this environment: {e}")

        run_id = "run-123"
        video_id = "000_clip"
        raw = b"fake-mp4-bytes"
        payload = base64.b64encode(raw).decode("utf-8")
        data_url = f"data:video/mp4;base64,{payload}"

        with (
            patch.object(activities_module.activity, "heartbeat", autospec=True),
            patch.object(activities_module, "DATA_SHARED_BASE", tmp_path),
        ):
            out_path = asyncio.run(activities_module.save_upscaled_video(run_id, video_id, data_url))

        expected = tmp_path / run_id / f"{video_id}_upscaled.mp4"
        assert out_path == str(expected)
        assert expected.exists()
        assert expected.read_bytes() == raw
