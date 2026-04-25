import pytest
import requests
from unittest.mock import MagicMock

from videomerge.models import ImageGenerationStartRequest, OrchestrateStartRequest
from videomerge.services.supabase_client import SupabaseStorageClient


class TestOrchestrateStartRequest:
    """Test the OrchestrateStartRequest model with language field."""

    def test_orchestrate_request_with_language_field(self):
        """Test that OrchestrateStartRequest accepts language field."""
        request_data = {
            "user_id": "user-123",
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
        """Test that language defaults to 'en' when not provided."""
        request_data = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "run_id": "test-run-123",
            "prompts": [],
            "image_style": "default",
        }

        request = OrchestrateStartRequest(**request_data)

        assert request.language == "en"

    def test_orchestrate_request_with_standard_language_code(self):
        """Test that standard language codes work."""
        request_data = {
            "user_id": "user-123",
            "script": "Test script",
            "caption": "Test caption",
            "run_id": "test-run-123",
            "prompts": [],
            "language": "en-US",
            "image_style": "default",
        }

        request = OrchestrateStartRequest(**request_data)

        assert request.language == "en-US"

    def test_orchestrate_request_accepts_style_alias(self):
        """Test that the style alias populates image_style."""
        request = OrchestrateStartRequest(
            user_id="user-123",
            script="Test script",
            caption="Test caption",
            style="cinematic",
        )

        assert request.image_style == "cinematic"


class TestWorkerLanguageIntegration:
    """Test language mapping behavior used by subtitle generation."""

    def test_worker_processes_language_from_payload(self):
        """Test that payload language values map correctly for Whisper."""
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
        assert whisper_code == "en"


class TestImageGenerationStartRequest:
    """Test the ImageGenerationStartRequest model."""

    def test_image_generation_request_defaults(self):
        """Test that image generation request applies expected defaults."""
        request = ImageGenerationStartRequest(
            user_id="user-123",
            script="Generate a short image sequence",
            user_access_token="token",
        )

        assert request.user_id == "user-123"
        assert request.script == "Generate a short image sequence"
        assert request.language == "en"
        assert request.image_style == "default"
        assert request.run_id is None
        assert request.workflow_id is None

    def test_image_generation_request_accepts_style_alias(self):
        """Test that the style alias populates image_style."""
        request = ImageGenerationStartRequest(
            user_id="user-123",
            script="Generate a short image sequence",
            user_access_token="token",
            style="disney",
        )

        assert request.image_style == "disney"


class TestSupabaseStorageClient:
    """Test Supabase storage client helpers."""

    def test_upload_file_returns_object_path(self, monkeypatch):
        """Upload should target the expected storage API path and return it."""
        response = MagicMock()
        post = MagicMock(return_value=response)
        monkeypatch.setattr("videomerge.services.supabase_client.requests.post", post)

        supabase_client = SupabaseStorageClient(
            url="https://example.supabase.co",
            anon_key="anon-key",
            bucket_name="user-videos",
            user_jwt="user-jwt",
        )

        object_path = supabase_client.upload_file(
            user_id="user-1",
            run_id="abc123",
            file_name="image_001.png",
            file_bytes=b"png-bytes",
        )

        post.assert_called_once_with(
            "https://example.supabase.co/storage/v1/object/user-videos/user-1/abc123/image_001.png",
            headers={
                "apikey": "anon-key",
                "Authorization": "Bearer user-jwt",
                "x-upsert": "true",
            },
            files={"file": ("image_001.png", b"png-bytes", "image/png")},
            timeout=60,
        )
        response.raise_for_status.assert_called_once_with()
        assert object_path == "user-1/abc123/image_001.png"

    def test_list_files_returns_sorted_file_names(self, monkeypatch):
        """List should return sorted file names from the configured prefix."""
        response = MagicMock()
        response.json.return_value = [{"name": "image_002.png"}, {"name": "image_001.png"}]
        post = MagicMock(return_value=response)
        monkeypatch.setattr("videomerge.services.supabase_client.requests.post", post)

        supabase_client = SupabaseStorageClient(
            url="https://example.supabase.co",
            anon_key="anon-key",
            bucket_name="user-videos",
        )

        file_names = supabase_client.list_files(user_id="user-1", run_id="abc123")

        post.assert_called_once_with(
            "https://example.supabase.co/storage/v1/object/list/user-videos",
            headers={
                "apikey": "anon-key",
                "Authorization": "Bearer anon-key",
                "Content-Type": "application/json",
            },
            json={"prefix": "user-1/abc123"},
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()
        assert file_names == ["image_001.png", "image_002.png"]

    def test_upload_file_raises_detailed_runtime_error(self, monkeypatch):
        """Upload failures should include the Supabase response body for diagnostics."""
        response = MagicMock()
        response.status_code = 400
        response.text = '{"message":"Bucket not found"}'
        response.raise_for_status.side_effect = requests.HTTPError("400 Client Error")
        post = MagicMock(return_value=response)
        monkeypatch.setattr("videomerge.services.supabase_client.requests.post", post)

        supabase_client = SupabaseStorageClient(
            url="https://example.supabase.co",
            anon_key="anon-key",
            bucket_name="user-videos",
            user_jwt="user-jwt",
        )

        with pytest.raises(RuntimeError, match='Supabase Storage request failed with status=400:'):
            supabase_client.upload_file(
                user_id="user-1",
                run_id="abc123",
                file_name="image_001.png",
                file_bytes=b"png-bytes",
            )

    def test_upload_file_requires_user_jwt(self):
        """Upload should fail fast when no authenticated user JWT is provided."""
        supabase_client = SupabaseStorageClient(
            url="https://example.supabase.co",
            anon_key="anon-key",
            bucket_name="user-videos",
        )

        with pytest.raises(RuntimeError, match="User JWT is required for uploads"):
            supabase_client.upload_file(
                user_id="user-1",
                run_id="abc123",
                file_name="image_001.png",
                file_bytes=b"png-bytes",
            )
