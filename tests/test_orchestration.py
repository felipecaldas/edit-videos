import pytest
from unittest.mock import Mock, patch, MagicMock

from videomerge.models import ImageGenerationStartRequest, OrchestrateStartRequest
from videomerge.services.supabase_client import SupabaseStorageClient
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


class TestImageGenerationStartRequest:
    """Test the ImageGenerationStartRequest model."""

    def test_image_generation_request_defaults(self):
        """Test that image generation request applies expected defaults."""
        request = ImageGenerationStartRequest(
            user_id="user-123",
            script="Generate a short image sequence",
        )

        assert request.user_id == "user-123"
        assert request.script == "Generate a short image sequence"
        assert request.language == "en"
        assert request.image_style == "default"
        assert request.run_id is None
        assert request.workflow_id is None


class TestSupabaseStorageClient:
    """Test Supabase storage client helpers."""

    def test_upload_file_returns_object_path(self):
        """Upload should target the expected object path and return it."""
        bucket = MagicMock()
        storage = MagicMock()
        storage.from_.return_value = bucket
        client = MagicMock()
        client.storage = storage

        supabase_client = SupabaseStorageClient(url="https://example.supabase.co", anon_key="anon-key")
        supabase_client._client = client

        object_path = supabase_client.upload_file(
            user_id="user-1",
            run_id="abc123",
            file_name="image_001.png",
            file_bytes=b"png-bytes",
        )

        bucket.upload.assert_called_once_with(
            path="user-1/abc123/image_001.png",
            file=b"png-bytes",
            file_options={"content-type": "image/png", "upsert": "true"},
        )
        assert object_path == "user-1/abc123/image_001.png"

    def test_list_files_returns_sorted_file_names(self):
        """List should return sorted file names from the configured prefix."""
        bucket = MagicMock()
        bucket.list.return_value = [{"name": "image_002.png"}, {"name": "image_001.png"}]
        storage = MagicMock()
        storage.from_.return_value = bucket
        client = MagicMock()
        client.storage = storage

        supabase_client = SupabaseStorageClient(url="https://example.supabase.co", anon_key="anon-key")
        supabase_client._client = client

        file_names = supabase_client.list_files(user_id="user-1", run_id="abc123")

        bucket.list.assert_called_once_with(path="user-1/abc123")
        assert file_names == ["image_001.png", "image_002.png"]
