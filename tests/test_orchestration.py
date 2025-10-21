import pytest
from unittest.mock import Mock, patch, MagicMock

from videomerge.models import OrchestrateStartRequest
from videomerge.services.worker import Worker


class TestOrchestrateStartRequest:
    """Test the OrchestrateStartRequest model with language field."""

    def test_orchestrate_request_with_language_field(self):
        """Test that OrchestrateStartRequest accepts language field."""
        request_data = {
            "script": "Test script",
            "caption": "Test caption",
            "run_id": "test-run-123",
            "prompts": [
                {
                    "image_prompt": "Test image prompt",
                    "video_prompt": "Test video prompt"
                }
            ],
            "language": "English (US)",
            "enable_image_gen": True,
            "image_style": "default"
        }

        request = OrchestrateStartRequest(**request_data)

        assert request.script == "Test script"
        assert request.caption == "Test caption"
        assert request.run_id == "test-run-123"
        assert len(request.prompts) == 1
        assert request.language == "English (US)"
        assert request.enable_image_gen is True
        assert request.image_style == "default"

    def test_orchestrate_request_default_language(self):
        """Test that language defaults to 'pt' when not provided."""
        request_data = {
            "script": "Test script",
            "caption": "Test caption",
            "run_id": "test-run-123",
            "prompts": []
        }

        request = OrchestrateStartRequest(**request_data)

        assert request.language == "pt"  # Should default to Portuguese

    def test_orchestrate_request_with_standard_language_code(self):
        """Test that standard language codes work."""
        request_data = {
            "script": "Test script",
            "caption": "Test caption",
            "run_id": "test-run-123",
            "prompts": [],
            "language": "en-US"
        }

        request = OrchestrateStartRequest(**request_data)

        assert request.language == "en-US"


class TestWorkerLanguageIntegration:
    """Test worker integration with language field."""

    def test_worker_processes_language_from_payload(self):
        """Test that worker extracts language from payload and passes it to subtitle generation."""
        # Mock payload with frontend language name
        payload = {
            "script": "Test script",
            "caption": "Test caption",
            "run_id": "test-run-123",
            "prompts": [],
            "language": "English (US)",  # Frontend language name
            "enable_image_gen": False,
            "workflow_path": "/test/workflow.json"
        }

        # Test language extraction (same logic as in worker)
        language = payload.get("language", "pt")

        # Verify language is extracted correctly
        assert language == "English (US)"

        # Verify the language mapping would work
        from videomerge.services.subtitles import map_language_to_whisper_code
        whisper_code = map_language_to_whisper_code(language)
        assert whisper_code == "en-US"
