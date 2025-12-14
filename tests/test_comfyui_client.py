"""Tests for ComfyUI client wrapper."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from videomerge.services.comfyui_client import (
    ComfyUIClient,
    LocalComfyUIClient,
    RunPodComfyUIClient,
    ComfyUIClientFactory,
    get_comfyui_client,
    reset_comfyui_client,
)


class TestComfyUIClientFactory:
    """Test the ComfyUI client factory."""

    def test_create_local_client(self):
        """Test creating a local ComfyUI client."""
        client = ComfyUIClientFactory.create_client("http://192.168.68.51:8188", "local")
        assert isinstance(client, LocalComfyUIClient)
        assert client.base_url == "http://192.168.68.51:8188"

    def test_create_runpod_client(self):
        """Test creating a RunPod ComfyUI client."""
        client = ComfyUIClientFactory.create_client("https://api.runpod.ai", "runpod")
        assert isinstance(client, RunPodComfyUIClient)
        assert client.base_url == "https://api.runpod.ai"

    def test_create_unsupported_client(self):
        """Test creating a client for unsupported environment."""
        with pytest.raises(ValueError, match="Unsupported ComfyUI environment"):
            ComfyUIClientFactory.create_client("http://localhost:8188", "unsupported")


class TestLocalComfyUIClient:
    """Test the local ComfyUI client."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = LocalComfyUIClient("http://192.168.68.51:8188")
        self.template_path = Path("test_workflow.json")

    @patch('videomerge.services.comfyui_client.Path.open')
    @patch('videomerge.services.comfyui_client.requests.request')
    def test_submit_text_to_image_success(self, mock_request, mock_open):
        """Test successful text-to-image submission."""
        # Mock template file
        mock_file = MagicMock()
        mock_file.read.return_value = '{"prompt": {"text": "{{ POSITIVE_PROMPT }}"}}'
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock HTTP response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"prompt_id": "test-prompt-id"}
        mock_request.return_value = mock_response

        result = self.client.submit_text_to_image("test prompt", template_path=self.template_path)

        assert result == "test-prompt-id"
        mock_request.assert_called_once()

    @patch('videomerge.services.comfyui_client.Path.open')
    def test_submit_text_to_image_missing_placeholder(self, mock_open):
        """Test text-to-image submission with missing placeholder."""
        mock_file = MagicMock()
        mock_file.read.return_value = '{"prompt": {"text": "fixed text"}}'
        mock_open.return_value.__enter__.return_value = mock_file

        with pytest.raises(ValueError, match="missing the '{{ POSITIVE_PROMPT }}' placeholder"):
            self.client.submit_text_to_image("test prompt", template_path=self.template_path)

    @patch('videomerge.services.comfyui_client.Path.open')
    @patch('videomerge.services.comfyui_client.requests.request')
    def test_submit_image_to_video_success(self, mock_request, mock_open):
        """Test successful image-to-video submission."""
        # Mock template file
        mock_file = MagicMock()
        mock_file.read.return_value = (
            '{"prompt": {"video_prompt": "{{ VIDEO_PROMPT }}", "input_image": "{{ INPUT_IMAGE }}"}}'
        )
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock HTTP response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"prompt_id": "test-video-id"}
        mock_request.return_value = mock_response

        result = self.client.submit_image_to_video(
            "video prompt", "test_image.png", template_path=self.template_path
        )

        assert result == "test-video-id"
        mock_request.assert_called_once()

    @patch('videomerge.services.comfyui_client.requests.request')
    def test_poll_until_complete_success(self, mock_request):
        """Test successful polling until completion."""
        # Mock queue response
        mock_queue_response = Mock()
        mock_queue_response.ok = True
        mock_queue_response.json.return_value = {"queue_running": []}

        # Mock history response with completed job
        mock_history_response = Mock()
        mock_history_response.ok = True
        mock_history_response.json.return_value = {
            "history": {
                "test-prompt-id": {
                    "status": {"completed": True},
                    "outputs": {
                        "1": {"images": [{"filename": "test.png", "subfolder": ""}]}
                    }
                }
            }
        }

        mock_request.side_effect = [mock_queue_response, mock_history_response]

        result = self.client.poll_until_complete("test-prompt-id", timeout_s=60, poll_interval_s=1)

        assert result == ["test.png"]
        assert mock_request.call_count == 2

    @patch('videomerge.services.comfyui_client.requests.request')
    def test_download_outputs_success(self, mock_request):
        """Test successful output download."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.iter_content.return_value = [b"test", b"image", b"data"]
        mock_request.return_value = mock_response

        with patch('pathlib.Path.mkdir'), patch('pathlib.Path.open') as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file

            dest_dir = Path("/tmp/test")
            result = self.client.download_outputs(["test.png"], dest_dir)

            assert len(result) == 1
            assert result[0].name == "test.png"

    @patch('videomerge.services.comfyui_client.requests.request')
    def test_fetch_output_bytes_success(self, mock_request):
        """Test successful output bytes fetch."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.content = b"test image data"
        mock_request.return_value = mock_response

        filename, content = self.client.fetch_output_bytes("test.png")

        assert filename == "test.png"
        assert content == b"test image data"

    @patch('videomerge.services.comfyui_client.requests.request')
    def test_upload_image_to_input_success(self, mock_request):
        """Test successful image upload."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"name": "uploaded_image.png"}
        mock_request.return_value = mock_response

        result = self.client.upload_image_to_input("test.png", b"image data")

        assert result == "uploaded_image.png"


class TestRunPodComfyUIClient:
    """Test the RunPod ComfyUI client."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = RunPodComfyUIClient("https://api.runpod.ai")
        self.template_path = Path("test_workflow.json")

    @patch('videomerge.services.comfyui_client.Path.open')
    @patch('videomerge.services.comfyui_client.requests.request')
    def test_submit_text_to_image_success(self, mock_request, mock_open):
        """Test successful text-to-image submission to RunPod."""
        # Mock template file
        mock_file = MagicMock()
        mock_file.read.return_value = '{"prompt": {"text": "{{ POSITIVE_PROMPT }}"}}'
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock HTTP response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"id": "runpod-job-id"}
        mock_request.return_value = mock_response

        result = self.client.submit_text_to_image("test prompt", template_path=self.template_path)

        assert result == "runpod-job-id"
        mock_request.assert_called_once()

    @patch('videomerge.services.comfyui_client.requests.request')
    def test_poll_until_complete_success(self, mock_request):
        """Test successful RunPod polling until completion."""
        # Mock status response with completed job
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "status": "completed",
            "output": {
                "images": [{"filename": "test.png", "subfolder": ""}]
            }
        }
        mock_request.return_value = mock_response

        result = self.client.poll_until_complete("runpod-job-id", timeout_s=60, poll_interval_s=1)

        assert result == ["test.png"]
        mock_request.assert_called_once()

    @patch('videomerge.services.comfyui_client.requests.request')
    def test_poll_until_complete_failed(self, mock_request):
        """Test RunPod polling with failed job."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "status": "failed",
            "error": "Processing failed"
        }
        mock_request.return_value = mock_response

        with pytest.raises(RuntimeError, match="RunPod job failed: Processing failed"):
            self.client.poll_until_complete("runpod-job-id", timeout_s=60, poll_interval_s=1)


class TestRunPodOutputFilenames:
    """Tests for RunPodComfyUIClient output filename generation."""

    def setup_method(self):
        """Create a bare RunPodComfyUIClient instance without running __init__."""
        # We only need the helper methods, which don't depend on instance attributes.
        self.client = object.__new__(RunPodComfyUIClient)

    def test_video_outputs_use_uuid_based_filenames(self):
        """Video outputs should always get UUID-based filenames to avoid collisions."""
        name1 = self.client._output_filename_for_index(
            media_type="video/mp4",
            provided="ComfyUI_00002_.mp4",
            index=0,
        )
        name2 = self.client._output_filename_for_index(
            media_type="video/mp4",
            provided="ComfyUI_00002_.mp4",
            index=0,
        )

        # Names should have the index prefix and .mp4 extension
        assert name1.startswith("000_")
        assert name1.endswith(".mp4")
        assert name2.startswith("000_")
        assert name2.endswith(".mp4")

        # Even with identical inputs, UUID portion should make them different
        assert name1 != name2

    def test_non_video_outputs_preserve_sanitized_name(self):
        """Non-video outputs (e.g. images) should preserve sanitized provided names."""
        name = self.client._output_filename_for_index(
            media_type="image/png",
            provided="my image.png",
            index=3,
        )

        # Index prefix and sanitized basename should both appear
        assert name.startswith("003_")
        assert name.endswith(".png")
        assert "my_image.png" in name


class TestGlobalClient:
    """Test the global client functions."""

    @patch('videomerge.services.comfyui_client.ComfyUIClientFactory.create_client')
    @patch('videomerge.services.comfyui_client.COMFYUI_URL', 'http://192.168.68.51:8188')
    @patch('videomerge.services.comfyui_client.RUN_ENV', 'local')
    def test_get_comfyui_client_initialization(self, mock_create_client):
        """Test that get_comfyui_client initializes the client on first call."""
        mock_client = Mock()
        mock_create_client.return_value = mock_client

        # Reset global client
        reset_comfyui_client()

        # First call should create the client
        result = get_comfyui_client()
        assert result is mock_client
        mock_create_client.assert_called_once_with('http://192.168.68.51:8188', 'local')

        # Second call should return the same instance
        result2 = get_comfyui_client()
        assert result2 is mock_client
        assert mock_create_client.call_count == 1  # Should not be called again

    def test_reset_comfyui_client(self):
        """Test that reset_comfyui_client clears the global client."""
        # This test ensures the reset function works without side effects
        reset_comfyui_client()
        # We can't easily test the internal state without exposing it,
        # but we can verify it doesn't raise an exception
        assert True


class TestComfyUIClientBase:
    """Test the base ComfyUIClient class functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create a concrete implementation for testing base class methods
        class TestClient(ComfyUIClient):
            def submit_text_to_image(self, *args, **kwargs):
                pass
            def submit_image_to_video(self, *args, **kwargs):
                pass
            def poll_until_complete(self, *args, **kwargs):
                pass
            def download_outputs(self, *args, **kwargs):
                pass
            def fetch_output_bytes(self, *args, **kwargs):
                pass
            def upload_image_to_input(self, *args, **kwargs):
                pass

        self.client = TestClient("http://192.168.68.51:8188")

    @patch('videomerge.services.comfyui_client.Path.open')
    def test_load_workflow_template(self, mock_open):
        """Test loading workflow template."""
        mock_file = MagicMock()
        mock_file.read.return_value = '{"test": "workflow"}'
        mock_open.return_value.__enter__.return_value = mock_file

        result = self.client._load_workflow_template(Path("test.json"))

        assert result == '{"test": "workflow"}'

    def test_default_headers(self):
        """Test default headers generation."""
        headers = self.client._default_headers()
        
        assert "Accept" in headers
        assert "User-Agent" in headers
        assert "Origin" in headers
        assert "Referer" in headers
        assert headers["Origin"] == "http://192.168.68.51:8188"

    def test_parse_history_outputs(self):
        """Test parsing history outputs."""
        history = {
            "prompt1": {
                "outputs": {
                    "1": {
                        "images": [
                            {"filename": "test1.png", "subfolder": ""},
                            {"filename": "test2.png", "subfolder": "folder"}
                        ]
                    },
                    "2": {
                        "videos": [
                            {"filename": "test1.mp4", "subfolder": ""}
                        ]
                    }
                }
            }
        }

        # Test without preferred nodes
        result = self.client._parse_history_outputs(history)
        assert len(result) == 3
        assert ("test1.png", "") in result
        assert ("test2.png", "folder") in result
        assert ("test1.mp4", "") in result

        # Test with preferred nodes
        result = self.client._parse_history_outputs(history, prefer_node_ids=["1"])
        assert len(result) == 2
        assert ("test1.png", "") in result
        assert ("test2.png", "folder") in result

    def test_warn_if_bad_dimensions(self):
        """Test dimension warning functionality."""
        # Test workflow with bad dimensions
        workflow = {
            "1": {
                "inputs": {"width": 512, "height": 513},  # 513 is not divisible by 64
                "class_type": "TestNode"
            },
            "2": {
                "inputs": {"width": 512, "height": 512},  # Both divisible by 64
                "class_type": "TestNode"
            }
        }

        # This should not raise an exception, just log warnings
        self.client._warn_if_bad_dimensions(workflow)
        assert True  # If we get here, no exception was raised

    def test_warn_if_bad_dimensions_no_exception(self):
        """Test that dimension warnings never raise exceptions."""
        # Test with malformed workflow that might cause exceptions
        workflow = {
            "1": {
                "inputs": "not a dict",  # This could cause an exception
                "class_type": "TestNode"
            }
        }

        # This should not raise an exception
        self.client._warn_if_bad_dimensions(workflow)
        assert True
