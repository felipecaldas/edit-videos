from pathlib import Path
from typing import List

from supabase import Client, create_client

from videomerge.config import SUPABASE_ANON_KEY, SUPABASE_URL


class SupabaseStorageClient:
    """Wrapper for Supabase Storage operations used by image orchestration."""

    def __init__(self, url: str | None = None, anon_key: str | None = None, bucket_name: str = "storage") -> None:
        self._url = url or SUPABASE_URL
        self._anon_key = anon_key or SUPABASE_ANON_KEY
        self._bucket_name = bucket_name
        self._client: Client | None = None

    def _get_client(self) -> Client:
        """Return a configured Supabase client."""
        if self._client is not None:
            return self._client
        if not self._url or not self._anon_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be configured")
        self._client = create_client(self._url, self._anon_key)
        return self._client

    def upload_file(self, user_id: str, run_id: str, file_name: str, file_bytes: bytes, content_type: str = "image/png") -> str:
        """Upload a file to Supabase Storage and return its object path."""
        client = self._get_client()
        object_path = f"{user_id}/{run_id}/{file_name}"
        client.storage.from_(self._bucket_name).upload(
            path=object_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return object_path

    def upload_local_file(self, user_id: str, run_id: str, file_path: str | Path, content_type: str = "image/png") -> str:
        """Upload a local file to Supabase Storage and return its object path."""
        path_obj = Path(file_path)
        return self.upload_file(
            user_id=user_id,
            run_id=run_id,
            file_name=path_obj.name,
            file_bytes=path_obj.read_bytes(),
            content_type=content_type,
        )

    def list_files(self, user_id: str, run_id: str) -> List[str]:
        """List files stored for a given user and run."""
        client = self._get_client()
        response = client.storage.from_(self._bucket_name).list(path=f"{user_id}/{run_id}")
        if not isinstance(response, list):
            return []
        file_names = [item.get("name") for item in response if isinstance(item, dict) and item.get("name")]
        return sorted(file_names)


supabase_storage_client = SupabaseStorageClient()
