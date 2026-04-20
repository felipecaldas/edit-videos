"""Unit tests for orchestrate request models with N8N payload round-trip.

Tests that the Pydantic request models correctly parse the exact N8N example payloads
for both V-CaaS brief-aware flow and legacy flow.
"""

import json
from pathlib import Path

import pytest

from videomerge.models import (
    ImageGenerationStartRequest,
    OrchestrateStartRequest,
    StoryboardVideoGenerationRequest,
)


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def n8n_linkedin_example():
    """Load the N8N LinkedIn example payload."""
    fixture_path = FIXTURES_DIR / "n8n_linkedin_example.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def n8n_example_with_run_id(n8n_linkedin_example):
    """Create a payload with explicit run_id for storyboard video generation."""
    payload = n8n_linkedin_example.copy()
    payload["run_id"] = "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"
    return payload


@pytest.fixture
def legacy_payload():
    """Create a legacy payload without brief (for backward compatibility test)."""
    return {
        "user_id": "user-123",
        "script": "Test script",
        "caption": "Test caption",
        "image_style": "cinematic",
        "run_id": "legacy-run-id",
    }


@pytest.fixture
def legacy_payload_with_style_alias():
    """Create a legacy payload using 'style' instead of 'image_style'."""
    return {
        "user_id": "user-123",
        "script": "Test script",
        "caption": "Test caption",
        "style": "cinematic",
        "run_id": "alias-run-id",
    }


class TestOrchestrateStartRequest:
    """Tests for OrchestrateStartRequest model validation."""

    def test_validates_n8n_example(self, n8n_linkedin_example):
        """N8N example payload parses successfully."""
        req = OrchestrateStartRequest.model_validate(n8n_linkedin_example)
        assert req.user_id == "user-123"
        assert req.script == "Stop wasting money on video production."
        assert req.brief is not None
        assert req.platform == "LinkedIn"
        assert req.video_idea_id == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"

    def test_preserves_brief_platform_briefs_scenes(self, n8n_linkedin_example):
        """Brief.platform_briefs[].scenes[].visual_description is preserved."""
        req = OrchestrateStartRequest.model_validate(n8n_linkedin_example)
        assert req.brief is not None
        assert len(req.brief.platform_briefs) == 1
        pb = req.brief.platform_briefs[0]
        assert pb.platform == "LinkedIn"
        assert len(pb.scenes) == 8
        # Verify the first scene's visual_description is preserved
        assert pb.scenes[0].visual_description == "Dark office, empty chairs"
        assert pb.scenes[0].spoken_line == "Most marketing videos get zero views."
        assert pb.scenes[0].duration_seconds == 2.0

    def test_validates_legacy_payload(self, legacy_payload):
        """Legacy payload (no brief) validates successfully."""
        req = OrchestrateStartRequest.model_validate(legacy_payload)
        assert req.user_id == "user-123"
        assert req.script == "Test script"
        assert req.image_style == "cinematic"
        assert req.run_id == "legacy-run-id"
        assert req.brief is None

    def test_style_alias_populates_image_style(self, legacy_payload_with_style_alias):
        """The 'style' field populates the 'image_style' attribute."""
        req = OrchestrateStartRequest.model_validate(legacy_payload_with_style_alias)
        assert req.image_style == "cinematic"
        assert req.run_id == "alias-run-id"


class TestImageGenerationStartRequest:
    """Tests for ImageGenerationStartRequest model validation."""

    def test_validates_n8n_example(self, n8n_linkedin_example):
        """N8N example payload parses successfully."""
        # Add required field for ImageGenerationStartRequest
        payload = n8n_linkedin_example.copy()
        payload["user_access_token"] = "test-token"
        payload["language"] = "en"

        req = ImageGenerationStartRequest.model_validate(payload)
        assert req.user_id == "user-123"
        assert req.script == "Stop wasting money on video production."
        assert req.brief is not None
        assert req.platform == "LinkedIn"
        assert req.video_idea_id == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"
        assert req.user_access_token == "test-token"

    def test_preserves_nested_brief_structure(self, n8n_linkedin_example):
        """Nested Brief and PlatformBriefModel structures are preserved."""
        payload = n8n_linkedin_example.copy()
        payload["user_access_token"] = "test-token"
        payload["language"] = "en"

        req = ImageGenerationStartRequest.model_validate(payload)
        assert req.brief is not None
        assert req.brief.title == "Why Most Marketing Videos Fail"
        assert req.brief.visual_direction is not None
        assert req.brief.visual_direction.mood == "optimistic"
        assert req.brief.visual_direction.color_feel == "warm pastels"

    def test_validates_legacy_payload(self):
        """Legacy payload (no brief) validates successfully."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "language": "en",
            "user_access_token": "test-token",
            "run_id": "legacy-run-id",
        }
        req = ImageGenerationStartRequest.model_validate(payload)
        assert req.user_id == "user-123"
        assert req.run_id == "legacy-run-id"
        assert req.brief is None


class TestStoryboardVideoGenerationRequest:
    """Tests for StoryboardVideoGenerationRequest model validation."""

    def test_validates_n8n_example_with_run_id(self, n8n_example_with_run_id):
        """N8N example with explicit run_id parses successfully."""
        # Add required field for StoryboardVideoGenerationRequest
        payload = n8n_example_with_run_id.copy()
        payload["user_access_token"] = "test-token"

        req = StoryboardVideoGenerationRequest.model_validate(payload)
        assert req.user_id == "user-123"
        assert req.script == "Stop wasting money on video production."
        assert req.run_id == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11-linkedin"
        assert req.brief is not None
        assert req.platform == "LinkedIn"
        assert req.video_idea_id == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"
        assert req.user_access_token == "test-token"

    def test_preserves_scene_details(self, n8n_example_with_run_id):
        """Scene details including duration_seconds are preserved."""
        payload = n8n_example_with_run_id.copy()
        payload["user_access_token"] = "test-token"

        req = StoryboardVideoGenerationRequest.model_validate(payload)
        pb = req.brief.platform_briefs[0]
        assert len(pb.scenes) == 8
        # Verify specific scene details
        scene_5 = pb.scenes[4]  # 0-indexed
        assert scene_5.scene_number == 5
        assert scene_5.spoken_line == "First, know your audience's pain point."
        assert scene_5.duration_seconds == 2.0
        assert scene_5.visual_description == "Person struggling with problem"

    def test_validates_legacy_payload(self):
        """Legacy payload (no brief) validates successfully."""
        payload = {
            "user_id": "user-123",
            "script": "Test script",
            "user_access_token": "test-token",
            "run_id": "legacy-run-id",
        }
        req = StoryboardVideoGenerationRequest.model_validate(payload)
        assert req.user_id == "user-123"
        assert req.run_id == "legacy-run-id"
        assert req.brief is None

    def test_derives_run_id_from_video_idea_id_and_platform(self, n8n_linkedin_example):
        """When run_id is omitted, it can be derived from video_idea_id + platform."""
        payload = n8n_linkedin_example.copy()
        payload["user_access_token"] = "test-token"
        # Explicitly omit run_id to test derivation (use pop to avoid KeyError)
        payload.pop("run_id", None)

        req = StoryboardVideoGenerationRequest.model_validate(payload)
        # The model accepts it; derivation happens in the router
        assert req.video_idea_id == "fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"
        assert req.platform == "LinkedIn"
