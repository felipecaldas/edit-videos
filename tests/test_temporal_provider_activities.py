"""Unit tests for new Temporal provider-based activities."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from videomerge.models import Brief, PlatformBriefModel, SceneBrief, VisualDirection


@pytest.fixture
def sample_brief():
    """Create a sample brief for testing."""
    return Brief(
        visual_direction=VisualDirection(
            tone="professional",
            mood="inspiring",
            color_feel="vibrant",
            shot_style="cinematic"
        ),
        platform_briefs=[
            PlatformBriefModel(
                platform="LinkedIn",
                aspect_ratio="9:16",
                scenes=[
                    SceneBrief(
                        scene_number=1,
                        spoken_line="Test scene",
                        caption_text="Test",
                        duration_seconds=3.0,
                        visual_description="Test visual"
                    )
                ]
            )
        ]
    )


@pytest.mark.asyncio
async def test_classify_scenes_activity(sample_brief):
    """Test classify_scenes_activity."""
    from videomerge.temporal.activities import classify_scenes_activity
    from videomerge.services.scene_classifier import SceneClassification
    
    mock_classifications = [
        SceneClassification(
            scene_index=0,
            is_text_heavy=False,
            image_provider="runpod",
            image_model="z-image-turbo",
            reasoning="Test"
        )
    ]
    
    with patch("videomerge.services.scene_classifier.classify_scenes", return_value=mock_classifications):
        result = await classify_scenes_activity(
            brief_json=sample_brief.model_dump_json(),
            platform="LinkedIn"
        )
        
        assert len(result) == 1
        assert result[0]["image_model"] == "z-image-turbo"
        assert result[0]["image_provider"] == "runpod"


@pytest.mark.asyncio
async def test_start_image_generation_provider():
    """Test start_image_generation_provider activity."""
    from videomerge.temporal.activities import start_image_generation_provider
    
    mock_provider = MagicMock()
    mock_provider.submit_text_to_image = AsyncMock(return_value="job-123")
    
    with patch("videomerge.services.media_providers.registry.get_image_provider", return_value=mock_provider):
        job_id = await start_image_generation_provider(
            provider="fal",
            prompt_text="test prompt",
            model="fal-ai/flux/dev",
            width=720,
            height=1280,
            index=0
        )
        
        assert job_id == "job-123"
        mock_provider.submit_text_to_image.assert_called_once()


@pytest.mark.asyncio
async def test_poll_image_generation_provider(tmp_path):
    """Test poll_image_generation_provider activity."""
    from videomerge.temporal.activities import poll_image_generation_provider
    
    mock_provider = MagicMock()
    mock_provider.poll_image_generation = AsyncMock(return_value=["https://fal.media/image.png"])
    mock_provider.download_outputs = AsyncMock(return_value=[tmp_path / "000_test.png"])
    
    with patch("videomerge.temporal.activities.get_image_provider", return_value=mock_provider), \
         patch("videomerge.temporal.activities.DATA_SHARED_BASE", tmp_path), \
         patch("videomerge.temporal.activities._run_in_thread_with_heartbeats", new_callable=AsyncMock) as mock_run:
        
        mock_run.return_value = ["https://fal.media/image.png"]
        
        result = await poll_image_generation_provider(
            provider="fal",
            job_id="job-123",
            run_id="test-run",
            index=0,
            timeout_s=600,
            poll_interval_s=5.0
        )
        
        assert result == str(tmp_path / "000_test.png")


@pytest.mark.asyncio
async def test_start_video_generation_provider():
    """Test start_video_generation_provider activity."""
    from videomerge.temporal.activities import start_video_generation_provider
    
    mock_provider = MagicMock()
    mock_provider.submit_image_to_video = AsyncMock(return_value="video-job-456")
    
    with patch("videomerge.services.media_providers.registry.get_video_provider", return_value=mock_provider):
        job_id = await start_video_generation_provider(
            provider="fal",
            prompt_text="zoom in",
            image_input="/path/to/image.png",
            model="bytedance/seedance-2.0/image-to-video",
            width=720,
            height=1280,
            index=0,
            length=81
        )
        
        assert job_id == "video-job-456"
        mock_provider.submit_image_to_video.assert_called_once()


@pytest.mark.asyncio
async def test_poll_video_generation_provider_fal(tmp_path):
    """Test poll_video_generation_provider activity with Fal."""
    from videomerge.temporal.activities import poll_video_generation_provider
    
    mock_provider = MagicMock()
    mock_provider.poll_video_generation = AsyncMock(return_value=["https://fal.media/video.mp4"])
    mock_provider.download_outputs = AsyncMock(return_value=[tmp_path / "000_video.mp4"])
    
    with patch("videomerge.temporal.activities.get_video_provider", return_value=mock_provider), \
         patch("videomerge.temporal.activities.DATA_SHARED_BASE", tmp_path), \
         patch("videomerge.temporal.activities._run_in_thread_with_heartbeats", new_callable=AsyncMock) as mock_run:
        
        mock_run.return_value = ["https://fal.media/video.mp4"]
        
        result = await poll_video_generation_provider(
            provider="fal",
            job_id="video-job-456",
            run_id="test-run",
            index=0,
            timeout_s=600,
            poll_interval_s=5.0
        )
        
        assert len(result) == 1
        assert result[0] == str(tmp_path / "000_video.mp4")


@pytest.mark.asyncio
async def test_poll_video_generation_provider_runpod(tmp_path):
    """Test poll_video_generation_provider activity with Runpod."""
    from videomerge.temporal.activities import poll_video_generation_provider
    
    mock_provider = MagicMock()
    mock_provider.poll_video_generation = AsyncMock(return_value=["/data/shared/run/000_video.mp4"])
    
    with patch("videomerge.temporal.activities.get_video_provider", return_value=mock_provider), \
         patch("videomerge.temporal.activities.DATA_SHARED_BASE", tmp_path), \
         patch("videomerge.temporal.activities._run_in_thread_with_heartbeats", new_callable=AsyncMock) as mock_run:
        
        mock_run.return_value = ["/data/shared/run/000_video.mp4"]
        
        result = await poll_video_generation_provider(
            provider="runpod",
            job_id="runpod-job-789",
            run_id="test-run",
            index=0,
            timeout_s=600,
            poll_interval_s=5.0
        )
        
        assert len(result) == 1
        assert result[0] == "/data/shared/run/000_video.mp4"
