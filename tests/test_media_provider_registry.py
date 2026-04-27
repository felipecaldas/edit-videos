"""Unit tests for media provider registry."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from videomerge.services.media_providers.base import MediaProvider
from videomerge.services.media_providers.fal_provider import FalProvider
from videomerge.services.media_providers.registry import (
    get_image_provider,
    get_video_provider,
    reset_providers,
)
from videomerge.services.media_providers.runpod_provider import RunpodProvider


def test_get_image_provider_fal():
    """Test getting Fal image provider."""
    reset_providers()
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient"):
        provider = get_image_provider("fal")
        
        assert isinstance(provider, FalProvider)
        assert provider.provider_name == "fal"


def test_get_image_provider_runpod():
    """Test getting Runpod image provider."""
    reset_providers()
    
    provider = get_image_provider("runpod")
    
    assert isinstance(provider, RunpodProvider)
    assert provider.provider_name == "runpod"


def test_get_image_provider_singleton():
    """Test that providers are singletons."""
    reset_providers()
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient"):
        provider1 = get_image_provider("fal")
        provider2 = get_image_provider("fal")
        
        assert provider1 is provider2


def test_get_image_provider_invalid():
    """Test getting invalid provider raises error."""
    with pytest.raises(ValueError, match="Unsupported image provider"):
        get_image_provider("invalid")


def test_get_video_provider_fal():
    """Test getting Fal video provider."""
    reset_providers()
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient"):
        provider = get_video_provider("fal")
        
        assert isinstance(provider, FalProvider)
        assert provider.provider_name == "fal"


def test_get_video_provider_runpod():
    """Test getting Runpod video provider."""
    reset_providers()
    
    provider = get_video_provider("runpod")
    
    assert isinstance(provider, RunpodProvider)
    assert provider.provider_name == "runpod"


def test_get_video_provider_same_as_image():
    """Test that video and image providers share instances."""
    reset_providers()
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient"):
        image_provider = get_image_provider("fal")
        video_provider = get_video_provider("fal")
        
        assert image_provider is video_provider


def test_reset_providers():
    """Test resetting provider singletons."""
    reset_providers()
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient"):
        provider1 = get_image_provider("fal")
        reset_providers()
        provider2 = get_image_provider("fal")
        
        assert provider1 is not provider2


@pytest.mark.asyncio
async def test_fal_provider_submit_text_to_image():
    """Test FalProvider text-to-image submission."""
    mock_client = MagicMock()
    mock_client.submit_text_to_image = AsyncMock(return_value="job-123")
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient", return_value=mock_client):
        provider = FalProvider()
        
        job_id = await provider.submit_text_to_image(
            prompt="test prompt",
            model="fal-ai/flux/dev",
            width=720,
            height=1280
        )
        
        assert job_id == "job-123"
        mock_client.submit_text_to_image.assert_called_once_with(
            prompt="test prompt",
            model="fal-ai/flux/dev",
            width=720,
            height=1280,
            negative_prompt=None,
            style_id=None,
        )


@pytest.mark.asyncio
async def test_fal_provider_submit_image_to_video():
    """Test FalProvider image-to-video submission."""
    mock_client = MagicMock()
    mock_client.submit_image_to_video = AsyncMock(return_value="video-job-456")
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient", return_value=mock_client):
        provider = FalProvider()
        
        job_id = await provider.submit_image_to_video(
            prompt="zoom in",
            image_input="data:image/png;base64,abc",
            model="bytedance/seedance-2.0/image-to-video",
            width=720,
            height=1280,
            length=81
        )
        
        assert job_id == "video-job-456"
        mock_client.submit_image_to_video.assert_called_once()


@pytest.mark.asyncio
async def test_fal_provider_poll_image_generation():
    """Test FalProvider image polling."""
    mock_client = MagicMock()
    mock_client.poll_until_complete = AsyncMock(return_value=["https://fal.media/image.png"])
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient", return_value=mock_client):
        provider = FalProvider()
        
        outputs = await provider.poll_image_generation(
            job_id="job-123",
            timeout_s=600,
            poll_interval_s=5.0
        )
        
        assert outputs == ["https://fal.media/image.png"]
        mock_client.poll_until_complete.assert_called_once()


@pytest.mark.asyncio
async def test_fal_provider_download_outputs(tmp_path):
    """Test FalProvider output download."""
    mock_client = MagicMock()
    mock_client.download_outputs = AsyncMock(return_value=[tmp_path / "000_test.png"])
    
    with patch("videomerge.services.media_providers.fal_provider.FalClient", return_value=mock_client):
        provider = FalProvider()
        
        paths = await provider.download_outputs(
            output_urls=["https://fal.media/image.png"],
            dest_dir=tmp_path,
            index=0
        )
        
        assert len(paths) == 1
        mock_client.download_outputs.assert_called_once()


@pytest.mark.asyncio
async def test_runpod_provider_submit_text_to_image():
    """Test RunpodProvider text-to-image submission."""
    # RunpodProvider uses asyncio.to_thread, so the underlying client method must be
    # a regular (sync) callable — not AsyncMock.
    mock_client = MagicMock()
    mock_client.submit_text_to_image = MagicMock(return_value="runpod-job-789")

    with patch("videomerge.services.media_providers.runpod_provider.get_image_client", return_value=mock_client):
        provider = RunpodProvider()

        job_id = await provider.submit_text_to_image(
            prompt="test prompt",
            model="z-image-turbo",
            width=720,
            height=1280
        )

        assert job_id == "runpod-job-789"
        mock_client.submit_text_to_image.assert_called_once()


@pytest.mark.asyncio
async def test_runpod_provider_poll_image_generation():
    """Test RunpodProvider image polling."""
    # The provider calls client.poll_until_complete via asyncio.to_thread (sync).
    mock_client = MagicMock()
    mock_client.poll_until_complete = MagicMock(return_value=["/data/shared/run/000_image.png"])

    with patch("videomerge.services.media_providers.runpod_provider.get_image_client", return_value=mock_client):
        provider = RunpodProvider()

        outputs = await provider.poll_image_generation(
            job_id="runpod-job-789",
            timeout_s=600,
            poll_interval_s=5.0
        )

        assert outputs == ["/data/shared/run/000_image.png"]
        mock_client.poll_until_complete.assert_called_once()


@pytest.mark.asyncio
async def test_runpod_provider_download_outputs():
    """Test RunpodProvider download (no-op)."""
    provider = RunpodProvider()
    
    # Runpod outputs are already local paths
    paths = await provider.download_outputs(
        output_urls=["/data/shared/run/000_image.png"],
        dest_dir=Path("/tmp"),
        index=0
    )
    
    assert len(paths) == 1
    assert paths[0] == Path("/data/shared/run/000_image.png")


def test_fal_provider_name():
    """Test FalProvider name property."""
    with patch("videomerge.services.media_providers.fal_provider.FalClient"):
        provider = FalProvider()
        assert provider.provider_name == "fal"


def test_runpod_provider_name():
    """Test RunpodProvider name property."""
    provider = RunpodProvider()
    assert provider.provider_name == "runpod"
