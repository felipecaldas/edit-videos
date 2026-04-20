import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from videomerge.routers.orchestrate import (
    aspect_ratio_to_video_format,
    _derive_run_id,
)
from videomerge.models import (
    Brief,
    PlatformBriefModel,
    OrchestrateStartRequest,
    ImageGenerationStartRequest,
    StoryboardVideoGenerationRequest,
    SceneBrief,
)


@pytest.fixture(autouse=True)
def mock_image_style_mapping(monkeypatch):
    """Mock IMAGE_STYLE_TO_WORKFLOW_MAPPING to include 'default'."""
    monkeypatch.setattr(
        "videomerge.routers.orchestrate.IMAGE_STYLE_TO_WORKFLOW_MAPPING",
        {"default": "default_workflow", "cinematic": "cinematic_workflow"},
    )


@pytest.fixture(autouse=True)
def mock_supabase_config(monkeypatch):
    """Mock Supabase config to allow tests to run without actual Supabase."""
    monkeypatch.setattr(
        "videomerge.routers.orchestrate.SUPABASE_URL",
        "https://test.supabase.co",
    )
    monkeypatch.setattr(
        "videomerge.routers.orchestrate.SUPABASE_ANON_KEY",
        "test-key",
    )


class TestAspectRatioToVideoFormat:
    """Test the aspect_ratio_to_video_format helper function."""

    def test_valid_1_1_ratio(self):
        assert aspect_ratio_to_video_format("1:1") == "1:1"

    def test_valid_9_16_ratio(self):
        assert aspect_ratio_to_video_format("9:16") == "9:16"

    def test_valid_16_9_ratio(self):
        assert aspect_ratio_to_video_format("16:9") == "16:9"

    def test_invalid_ratio_defaults_to_9_16(self):
        assert aspect_ratio_to_video_format("4:3") == "9:16"
        assert aspect_ratio_to_video_format("invalid") == "9:16"
        assert aspect_ratio_to_video_format("") == "9:16"


class TestDeriveRunId:
    """Test the _derive_run_id helper function."""

    def test_derives_run_id_correctly(self):
        run_id = _derive_run_id("video-123", "LinkedIn")
        assert run_id == "video-123-linkedin"

    def test_derives_run_id_with_lowercase_platform(self):
        run_id = _derive_run_id("video-123", "INSTAGRAM")
        assert run_id == "video-123-instagram"

    def test_raises_when_video_idea_id_missing(self):
        with pytest.raises(ValueError, match="video_idea_id is required"):
            _derive_run_id(None, "LinkedIn")

    def test_raises_when_platform_missing(self):
        with pytest.raises(ValueError, match="platform is required"):
            _derive_run_id("video-123", None)


def make_brief_with_platform(platform: str, aspect_ratio: str = "9:16") -> Brief:
    """Helper to create a Brief with a single platform."""
    return Brief(
        title="Test Video",
        hook="Test hook",
        platform_briefs=[
            PlatformBriefModel(
                platform=platform,
                aspect_ratio=aspect_ratio,
                tone="professional",
                scenes=[
                    SceneBrief(
                        scene_number=1,
                        spoken_line="Hello world",
                        caption_text="Hello caption",
                        duration_seconds=5,
                        visual_description="A test scene",
                    )
                ],
            )
        ],
    )


class TestOrchestrateStartBriefAware:
    """Test OrchestrateStartRequest with brief-aware payloads."""

    @pytest.mark.asyncio
    async def test_derives_run_id_from_video_idea_id_and_platform(self):
        """When brief+platform provided without run_id, derive from video_idea_id+platform."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("LinkedIn")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="LinkedIn",
            video_idea_id="video-123",
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_start(req)

        assert req.run_id == "video-123-linkedin"

    @pytest.mark.asyncio
    async def test_derives_video_format_from_platform_brief_aspect_ratio(self):
        """When video_format not provided, derive from platform_brief.aspect_ratio."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("Instagram", aspect_ratio="1:1")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="Instagram",
            video_idea_id="video-123",
            run_id="existing-run",
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_start(req)

        assert req.video_format == "1:1"

    @pytest.mark.asyncio
    async def test_derives_image_style_to_default_when_not_provided(self):
        """When image_style not provided, default to 'default'."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("LinkedIn")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="LinkedIn",
            video_idea_id="video-123",
            run_id="existing-run",
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_start(req)

        assert req.image_style == "default"

    @pytest.mark.asyncio
    async def test_raises_400_when_platform_not_in_brief(self):
        """Return 400 when platform does not match any entry in platform_briefs."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("LinkedIn")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="Instagram",  # Not in brief
        )

        with pytest.raises(HTTPException) as exc_info:
            await orchestrate_start(req)

        assert exc_info.value.status_code == 400
        assert "Platform 'Instagram' not found" in exc_info.value.detail
        assert "LinkedIn" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_400_when_video_idea_id_missing_for_derivation(self):
        """Return 400 when video_idea_id missing and run_id not supplied."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("LinkedIn")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="LinkedIn",
            # No run_id, no video_idea_id
        )

        with pytest.raises(HTTPException) as exc_info:
            await orchestrate_start(req)

        assert exc_info.value.status_code == 400
        assert "video_idea_id is required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_uses_provided_run_id_when_present(self):
        """When run_id is explicitly provided, use it instead of deriving."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("LinkedIn")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="LinkedIn",
            video_idea_id="video-123",
            run_id="my-custom-run-id",
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_start(req)

        assert req.run_id == "my-custom-run-id"

    @pytest.mark.asyncio
    async def test_uses_provided_video_format_when_present(self):
        """When video_format is explicitly provided, don't override."""
        from videomerge.routers.orchestrate import orchestrate_start

        brief = make_brief_with_platform("Instagram", aspect_ratio="1:1")
        req = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            brief=brief,
            platform="Instagram",
            video_idea_id="video-123",
            run_id="existing-run",
            video_format="16:9",  # Explicit override
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_start(req)

        assert req.video_format == "16:9"


class TestImageGenerationStartBriefAware:
    """Test ImageGenerationStartRequest with brief-aware payloads."""

    @pytest.mark.asyncio
    async def test_derives_run_id_from_video_idea_id_and_platform(self):
        """When brief+platform provided without run_id, derive from video_idea_id+platform."""
        from videomerge.routers.orchestrate import orchestrate_generate_images

        brief = make_brief_with_platform("TikTok")
        req = ImageGenerationStartRequest(
            user_id="user-123",
            script="Test script",
            user_access_token="token",
            brief=brief,
            platform="TikTok",
            video_idea_id="video-456",
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_generate_images(req)

        assert req.run_id == "video-456-tiktok"

    @pytest.mark.asyncio
    async def test_raises_400_when_platform_not_in_brief(self):
        """Return 400 when platform does not match any entry in platform_briefs."""
        from videomerge.routers.orchestrate import orchestrate_generate_images

        brief = make_brief_with_platform("LinkedIn")
        req = ImageGenerationStartRequest(
            user_id="user-123",
            script="Test script",
            user_access_token="token",
            brief=brief,
            platform="X",
        )

        with pytest.raises(HTTPException) as exc_info:
            await orchestrate_generate_images(req)

        assert exc_info.value.status_code == 400
        assert "Platform 'X' not found" in exc_info.value.detail


class TestStoryboardVideoGenerationBriefAware:
    """Test StoryboardVideoGenerationRequest with brief-aware payloads."""

    @pytest.mark.asyncio
    async def test_derives_run_id_and_video_format(self):
        """When brief+platform provided, derive run_id and video_format."""
        from videomerge.routers.orchestrate import orchestrate_generate_videos

        brief = make_brief_with_platform("YouTubeShorts", aspect_ratio="9:16")
        req = StoryboardVideoGenerationRequest(
            user_id="user-123",
            script="Test script",
            user_access_token="token",
            brief=brief,
            platform="YouTubeShorts",
            video_idea_id="video-789",
        )

        with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.start_workflow = AsyncMock(return_value=MagicMock())
            mock_client_cls.connect = AsyncMock(return_value=mock_client)

            with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
                await orchestrate_generate_videos(req)

        assert req.run_id == "video-789-youtubeshorts"
        assert req.video_format == "9:16"

    @pytest.mark.asyncio
    async def test_raises_400_when_platform_not_in_brief(self):
        """Return 400 when platform does not match any entry in platform_briefs."""
        from videomerge.routers.orchestrate import orchestrate_generate_videos

        brief = make_brief_with_platform("LinkedIn")
        req = StoryboardVideoGenerationRequest(
            user_id="user-123",
            script="Test script",
            user_access_token="token",
            brief=brief,
            platform="Instagram",
        )

        with pytest.raises(HTTPException) as exc_info:
            await orchestrate_generate_videos(req)

        assert exc_info.value.status_code == 400
        assert "Platform 'Instagram' not found" in exc_info.value.detail
