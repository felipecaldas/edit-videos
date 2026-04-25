"""
Integration tests for the orchestrate router endpoints.

These tests use FastAPI TestClient with mocked Temporal to verify:
- All three endpoints respond with 202 on success
- Brief-aware payloads correctly derive run_id, video_format, image_style
- Legacy payloads (no brief) continue to work unchanged
- Error cases return appropriate status codes
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from videomerge.main import create_app
from videomerge.models import (
    Brief,
    PlatformBriefModel,
    SceneBrief,
    VisualDirection,
)


@pytest.fixture
def mock_temporal_client():
    """Mock Temporal client to avoid actual workflow starts."""
    with patch("videomerge.routers.orchestrate.Client") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock(return_value=MagicMock())
        mock_client_cls.connect = AsyncMock(return_value=mock_client)
        yield mock_client


@pytest.fixture
def mock_metrics():
    """Mock the jobs_enqueued_total metric."""
    with patch("videomerge.routers.orchestrate.jobs_enqueued_total"):
        yield


@pytest.fixture
def mock_image_style_mapping():
    """Mock IMAGE_STYLE_TO_WORKFLOW_MAPPING."""
    with patch(
        "videomerge.routers.orchestrate.IMAGE_STYLE_TO_WORKFLOW_MAPPING",
        {"default": "default_workflow", "cinematic": "cinematic_workflow"},
    ):
        yield


@pytest.fixture
def mock_supabase_config():
    """Mock Supabase config to allow image/video generation tests to run."""
    with patch("videomerge.routers.orchestrate.SUPABASE_URL", "https://test.supabase.co"):
        with patch("videomerge.routers.orchestrate.SUPABASE_ANON_KEY", "test-key"):
            yield


@pytest.fixture
def app(mock_temporal_client, mock_metrics, mock_image_style_mapping, mock_supabase_config):
    """Create test app with all mocks applied."""
    app = create_app()
    return app


@pytest.fixture
def client(app):
    """Create FastAPI TestClient."""
    return TestClient(app)


def make_n8n_example_brief() -> Brief:
    """Create the N8N example brief payload from the plan."""
    return Brief(
        hook="Stop wasting money on video production.",
        title="Why Most Marketing Videos Fail",
        narrative_structure="problem-solution-CTA",
        music_sound_mood="upbeat acoustic",
        visual_direction=VisualDirection(
            mood="optimistic",
            color_feel="warm pastels",
            shot_style="clean studio",
            branding_elements="wordmark",
        ),
        platform_briefs=[
            PlatformBriefModel(
                platform="LinkedIn",
                hook="Hook for LinkedIn audience",
                tone="professional",
                aspect_ratio="1:1",
                scenes=[
                    SceneBrief(
                        scene_number=1,
                        spoken_line="Most marketing videos get zero views.",
                        caption_text="Zero views",
                        duration_seconds=2.0,
                        visual_description="Dark office, empty chairs",
                    ),
                    SceneBrief(
                        scene_number=2,
                        spoken_line="Not because the product is bad.",
                        caption_text="Not the product",
                        duration_seconds=2.0,
                        visual_description="Product on desk, nobody using it",
                    ),
                    SceneBrief(
                        scene_number=3,
                        spoken_line="But because the story is weak.",
                        caption_text="Weak story",
                        duration_seconds=2.0,
                        visual_description="Person writing on whiteboard, frustrated",
                    ),
                    SceneBrief(
                        scene_number=4,
                        spoken_line="Here's the framework that changed everything.",
                        caption_text="The framework",
                        duration_seconds=2.0,
                        visual_description="Light bulb moment, person smiling",
                    ),
                    SceneBrief(
                        scene_number=5,
                        spoken_line="First, know your audience's pain point.",
                        caption_text="Pain point",
                        duration_seconds=2.0,
                        visual_description="Person struggling with problem",
                    ),
                    SceneBrief(
                        scene_number=6,
                        spoken_line="Second, make it visual.",
                        caption_text="Make it visual",
                        duration_seconds=2.0,
                        visual_description="Colorful charts and graphics",
                    ),
                    SceneBrief(
                        scene_number=7,
                        spoken_line="Third, end with a clear CTA.",
                        caption_text="Clear CTA",
                        duration_seconds=1.5,
                        visual_description="Call to action on screen",
                    ),
                    SceneBrief(
                        scene_number=8,
                        spoken_line="Try this in your next video.",
                        caption_text="Try it now",
                        duration_seconds=1.5,
                        visual_description="Person ready to record",
                    ),
                ],
                call_to_action="Book a demo",
                platform_notes="LinkedIn professional context",
            ),
        ],
    )


class TestOrchestrateStartIntegration:
    """Integration tests for POST /orchestrate/start."""

    def test_brief_aware_returns_202(self, client):
        """Brief-aware request returns 202 with correct response structure."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "workflow_id" in data
        assert "run_id" in data
        assert data["run_id"] == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"

    def test_brief_aware_derives_video_format_from_aspect_ratio(self, client):
        """When video_format not provided, derive from platform_brief.aspect_ratio."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "video-123",
            "run_id": "existing-run-id",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 202

    def test_brief_aware_derives_image_style_to_default(self, client):
        """When image_style not provided, default to 'default'."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "video-123",
            "run_id": "existing-run-id",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 202

    def test_legacy_request_returns_202(self, client):
        """Legacy request without brief still works."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "image_style": "cinematic",
            "run_id": "legacy-run-id",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert data["run_id"] == "legacy-run-id"

    def test_style_alias_works(self, client):
        """The 'style' alias for 'image_style' works."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "style": "cinematic",
            "run_id": "alias-run-id",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 202

    def test_unknown_platform_returns_400(self, client):
        """Returns 400 when platform not in brief.platform_briefs."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "Instagram",
            "video_idea_id": "video-123",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 400
        assert "Platform 'Instagram' not found" in response.json()["detail"]
        assert "LinkedIn" in response.json()["detail"]

    def test_missing_video_idea_id_returns_400(self, client):
        """Returns 400 when video_idea_id missing and run_id not provided."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 400
        assert "video_idea_id is required" in response.json()["detail"]

    def test_unknown_image_style_returns_400(self, client):
        """Returns 400 for unknown image_style."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "image_style": "nonexistent-style",
            "run_id": "test-run-id",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 400
        assert "Unknown image_style" in response.json()["detail"]


class TestOrchestrateGenerateImagesIntegration:
    """Integration tests for POST /orchestrate/generate-images."""

    def test_brief_aware_returns_202(self, client):
        """Brief-aware request returns 202."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "language": "en",
            "user_access_token": "test-token",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
        }

        response = client.post("/orchestrate/generate-images", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "workflow_id" in data
        assert "run_id" in data
        assert data["run_id"] == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"

    def test_legacy_request_returns_202(self, client):
        """Legacy request without brief still works."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "language": "en",
            "user_access_token": "test-token",
            "run_id": "legacy-run-id",
        }

        response = client.post("/orchestrate/generate-images", json=payload)

        assert response.status_code == 202

    def test_missing_user_access_token_returns_422(self, client):
        """Returns 422 when user_access_token is missing (Pydantic validation)."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "language": "en",
            "run_id": "test-run-id",
        }

        response = client.post("/orchestrate/generate-images", json=payload)

        assert response.status_code == 422

    def test_unknown_platform_returns_400(self, client):
        """Returns 400 when platform not in brief.platform_briefs."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "language": "en",
            "user_access_token": "test-token",
            "brief": brief.model_dump(mode="json"),
            "platform": "TikTok",
        }

        response = client.post("/orchestrate/generate-images", json=payload)

        assert response.status_code == 400


class TestOrchestrateGenerateVideosIntegration:
    """Integration tests for POST /orchestrate/generate-videos."""

    def test_brief_aware_returns_202(self, client):
        """Brief-aware request returns 202."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "user_access_token": "test-token",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
        }

        response = client.post("/orchestrate/generate-videos", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert "workflow_id" in data
        assert "run_id" in data
        assert data["run_id"] == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"

    def test_brief_aware_derives_video_format(self, client):
        """Derives video_format from platform_brief.aspect_ratio."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "user_access_token": "test-token",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "video-123",
            "run_id": "existing-run-id",
        }

        response = client.post("/orchestrate/generate-videos", json=payload)

        assert response.status_code == 202

    def test_legacy_request_returns_202(self, client):
        """Legacy request without brief still works."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "user_access_token": "test-token",
            "run_id": "legacy-run-id",
        }

        response = client.post("/orchestrate/generate-videos", json=payload)

        assert response.status_code == 202

    def test_missing_user_access_token_returns_422(self, client):
        """Returns 422 when user_access_token is missing (Pydantic validation)."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "run_id": "test-run-id",
        }

        response = client.post("/orchestrate/generate-videos", json=payload)

        assert response.status_code == 422

    def test_unknown_platform_returns_400(self, client):
        """Returns 400 when platform not in brief.platform_briefs."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "user_access_token": "test-token",
            "brief": brief.model_dump(mode="json"),
            "platform": "YouTube",
        }

        response = client.post("/orchestrate/generate-videos", json=payload)

        assert response.status_code == 400


class TestDeterministicRunIdDerivation:
    """Test that run_id derivation is deterministic for retries."""

    def test_same_inputs_produce_same_run_id(self, client):
        """Same video_idea_id + platform always produces same run_id."""
        brief = make_n8n_example_brief()
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "LinkedIn",
            "video_idea_id": "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11",
        }

        response1 = client.post("/orchestrate/start", json=payload)
        response2 = client.post("/orchestrate/start", json=payload)

        assert response1.status_code == 202
        assert response2.status_code == 202
        assert response1.json()["run_id"] == response2.json()["run_id"]
        assert response1.json()["run_id"] == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"

    def test_case_insensitive_platform_match(self, client):
        """Platform matching is case-insensitive."""
        brief = Brief(
            title="Test",
            platform_briefs=[
                PlatformBriefModel(
                    platform="LinkedIn",
                    scenes=[
                        SceneBrief(
                            scene_number=1,
                            spoken_line="Test",
                            caption_text="Test",
                            duration_seconds=1.0,
                            visual_description="Test",
                        )
                    ],
                )
            ],
        )
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "brief": brief.model_dump(mode="json"),
            "platform": "linkedin",
            "video_idea_id": "video-123",
        }

        response = client.post("/orchestrate/start", json=payload)

        assert response.status_code == 202
        assert response.json()["run_id"] == "video-123-linkedin"
