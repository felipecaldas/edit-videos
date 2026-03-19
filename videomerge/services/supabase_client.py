from pathlib import Path
from typing import List

import requests
from requests import Response

from videomerge.config import SUPABASE_ANON_KEY, SUPABASE_STORAGE_BUCKET, SUPABASE_URL


class SupabaseStorageClient:
    """Wrapper for Supabase Storage operations used by image orchestration."""

    def __init__(self, url: str | None = None, anon_key: str | None = None, bucket_name: str | None = None, user_jwt: str | None = None) -> None:
        self._url = url or SUPABASE_URL
        self._anon_key = anon_key or SUPABASE_ANON_KEY
        self._bucket_name = bucket_name or SUPABASE_STORAGE_BUCKET
        self._user_jwt = user_jwt

    def _build_headers(self, content_type: str | None = None) -> dict[str, str]:
        """Build authenticated headers for Supabase Storage requests.
        
        Uses the user JWT (if provided) for authenticated requests that respect RLS policies.
        Falls back to anon key for unauthenticated requests.
        
        Args:
            content_type: Optional content type header
        """
        if not self._url:
            raise RuntimeError("SUPABASE_URL must be configured")
        
        if not self._anon_key:
            raise RuntimeError("SUPABASE_ANON_KEY must be configured")
        
        # Use user JWT if available (respects RLS), otherwise use anon key
        auth_token = self._user_jwt if self._user_jwt else self._anon_key
        
        headers: dict[str, str] = {
            "apikey": self._anon_key,  # apikey is always the anon key
            "Authorization": f"Bearer {auth_token}",  # Authorization uses user JWT or anon key
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _storage_url(self, object_path: str | None = None) -> str:
        """Build the Supabase Storage API URL for an object or bucket endpoint."""
        if not self._url:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be configured")
        base_url = self._url.rstrip("/")
        storage_base = f"{base_url}/storage/v1/object/{self._bucket_name}"
        if object_path is None:
            return storage_base
        normalized_path = object_path.lstrip("/")
        return f"{storage_base}/{normalized_path}"

    @staticmethod
    def _raise_for_status(response: Response) -> None:
        """Raise a detailed error when a Supabase Storage request fails."""
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            response_text = response.text.strip()
            detail = response_text or "<empty response body>"
            raise RuntimeError(
                f"Supabase Storage request failed with status={response.status_code}: {detail}"
            ) from exc

    def upload_file(self, user_id: str, run_id: str, file_name: str, file_bytes: bytes, content_type: str = "image/png") -> str:
        """Upload a file to Supabase Storage and return its object path.
        
        Requires a user JWT to be set during client initialization for authenticated uploads.
        The upload will respect Storage RLS policies.
        """
        if not self._user_jwt:
            raise RuntimeError(
                "User JWT is required for uploads. Initialize SupabaseStorageClient with user_jwt parameter."
            )
        
        object_path = f"{user_id}/{run_id}/{file_name}"
        response = requests.post(
            self._storage_url(object_path),
            headers={
                **self._build_headers(),
                "x-upsert": "true",
            },
            files={"file": (file_name, file_bytes, content_type)},
            timeout=60,
        )
        self._raise_for_status(response)
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
        response = requests.post(
            f"{self._url.rstrip('/')}/storage/v1/object/list/{self._bucket_name}",
            headers=self._build_headers("application/json"),
            json={"prefix": f"{user_id}/{run_id}"},
            timeout=30,
        )
        self._raise_for_status(response)
        payload = response.json()
        if not isinstance(payload, list):
            return []
        file_names = [item.get("name") for item in payload if isinstance(item, dict) and item.get("name")]
        return sorted(file_names)


supabase_storage_client = SupabaseStorageClient()
