"""Unit tests for Fal.ai client."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from videomerge.services.fal.fal_client import FalClient


@pytest.fixture
def fal_client():
    """Create a FalClient instance with mocked API key."""
    with patch("videomerge.services.fal.fal_client.FAL_AI_API_KEY", "test-api-key"):
        return FalClient()


@pytest.mark.asyncio
async def test_submit_text_to_image(fal_client):
    """Test text-to-image submission."""
    mock_handler = MagicMock()
    mock_handler.request_id = "test-request-123"
    
    with patch("fal_client.submit_async", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = mock_handler
        
        request_id = await fal_client.submit_text_to_image(
            prompt="A beautiful landscape",
            model="fal-ai/flux/dev",
            width=720,
            height=1280
        )
        
        assert request_id == "test-request-123"
        mock_submit.assert_called_once()
        
        call_args = mock_submit.call_args
        assert call_args[0][0] == "fal-ai/flux/dev"
        assert call_args[1]["arguments"]["prompt"] == "A beautiful landscape"
        assert call_args[1]["arguments"]["image_size"] == {"width": 720, "height": 1280}


@pytest.mark.asyncio
async def test_submit_image_to_video_with_data_url(fal_client):
    """Test image-to-video submission with data URL."""
    mock_handler = MagicMock()
    mock_handler.request_id = "test-video-456"
    
    data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    
    with patch("fal_client.submit_async", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = mock_handler
        
        request_id = await fal_client.submit_image_to_video(
            prompt="Slow zoom in",
            image_input=data_url,
            model="bytedance/seedance-2.0/image-to-video",
            width=720,
            height=1280,
            length=81
        )
        
        assert request_id == "test-video-456"
        mock_submit.assert_called_once()
        
        call_args = mock_submit.call_args
        assert call_args[0][0] == "bytedance/seedance-2.0/image-to-video"
        assert call_args[1]["arguments"]["prompt"] == "Slow zoom in"
        assert call_args[1]["arguments"]["width"] == 720
        assert call_args[1]["arguments"]["length"] == 81
        assert call_args[1]["arguments"]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_poll_until_complete_success(fal_client):
    """Test polling until job completes successfully."""
    mock_status_responses = [
        {"status": "IN_QUEUE"},
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED"}
    ]
    
    mock_result = {
        "images": [
            {"url": "https://fal.media/files/test-image.png"}
        ]
    }
    
    with patch("fal_client.status", side_effect=mock_status_responses) as mock_status, \
         patch("fal_client.result", return_value=mock_result) as mock_result_call:
        
        outputs = await fal_client.poll_until_complete(
            model="fal-ai/flux/dev",
            request_id="test-123",
            timeout_s=60,
            poll_interval_s=0.1,
            operation_type="image"
        )
        
        assert len(outputs) == 1
        assert outputs[0] == "https://fal.media/files/test-image.png"
        assert mock_status.call_count == 3
        mock_result_call.assert_called_once_with("fal-ai/flux/dev", "test-123")


@pytest.mark.asyncio
async def test_poll_until_complete_failure(fal_client):
    """Test polling when job fails."""
    mock_status_response = {
        "status": "FAILED",
        "error": "Model inference failed"
    }
    
    with patch("fal_client.status", return_value=mock_status_response):
        with pytest.raises(RuntimeError, match="Fal job failed"):
            await fal_client.poll_until_complete(
                model="fal-ai/flux/dev",
                request_id="test-fail",
                timeout_s=60,
                poll_interval_s=0.1,
                operation_type="image"
            )


@pytest.mark.asyncio
async def test_poll_until_complete_timeout(fal_client):
    """Test polling timeout."""
    mock_status_response = {"status": "IN_QUEUE"}
    
    with patch("fal_client.status", return_value=mock_status_response):
        with pytest.raises(TimeoutError, match="Timed out waiting for Fal results"):
            await fal_client.poll_until_complete(
                model="fal-ai/flux/dev",
                request_id="test-timeout",
                timeout_s=1,
                poll_interval_s=0.5,
                operation_type="image"
            )


@pytest.mark.asyncio
async def test_download_outputs_data_url(fal_client, tmp_path):
    """Test downloading outputs from data URL."""
    data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    
    saved_files = await fal_client.download_outputs(
        output_urls=[data_url],
        dest_dir=tmp_path,
        index=0
    )
    
    assert len(saved_files) == 1
    assert saved_files[0].exists()
    assert saved_files[0].suffix == ".png"
    assert saved_files[0].name.startswith("000_")


@pytest.mark.asyncio
async def test_download_outputs_http_url(fal_client, tmp_path):
    """Test downloading outputs from HTTP URL."""
    mock_response = MagicMock()
    mock_response.content = b"fake-image-data"
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        saved_files = await fal_client.download_outputs(
            output_urls=["https://fal.media/files/test.jpg"],
            dest_dir=tmp_path,
            index=1
        )
        
        assert len(saved_files) == 1
        assert saved_files[0].exists()
        assert saved_files[0].suffix == ".jpg"
        assert saved_files[0].name.startswith("001_")
        assert saved_files[0].read_bytes() == b"fake-image-data"


@pytest.mark.asyncio
async def test_extract_outputs_image(fal_client):
    """Test extracting image outputs from result."""
    result = {
        "images": [
            {"url": "https://fal.media/image1.png"},
            {"url": "https://fal.media/image2.png"}
        ]
    }
    
    outputs = fal_client._extract_outputs(result, "image")
    
    assert len(outputs) == 2
    assert outputs[0] == "https://fal.media/image1.png"
    assert outputs[1] == "https://fal.media/image2.png"


@pytest.mark.asyncio
async def test_extract_outputs_video(fal_client):
    """Test extracting video outputs from result."""
    result = {
        "video": {
            "url": "https://fal.media/video.mp4",
            "content_type": "video/mp4"
        }
    }
    
    outputs = fal_client._extract_outputs(result, "video")
    
    assert len(outputs) == 1
    assert outputs[0] == "https://fal.media/video.mp4"


def test_fal_client_requires_api_key():
    """Test that FalClient raises error without API key."""
    with patch("videomerge.services.fal.fal_client.FAL_AI_API_KEY", None):
        with pytest.raises(ValueError, match="FAL_AI_API_KEY is required"):
            FalClient()
