"""Fal.ai provider implementation."""

from __future__ import annotations

from pathlib import Path
from typing import List

from videomerge.services.fal.fal_client import FalClient
from videomerge.services.media_providers.base import MediaProvider


class FalProvider(MediaProvider):
    """Fal.ai media generation provider."""

    def __init__(self, api_key: str | None = None):
        """Initialize Fal provider.
        
        Args:
            api_key: Fal.ai API key (optional, uses config default)
        """
        self._client = FalClient(api_key=api_key)

    async def submit_text_to_image(
        self,
        prompt: str,
        model: str,
        width: int,
        height: int,
        **kwargs
    ) -> str:
        """Submit text-to-image job to Fal."""
        return await self._client.submit_text_to_image(
            prompt=prompt,
            model=model,
            width=width,
            height=height,
            **kwargs
        )

    async def submit_image_to_video(
        self,
        prompt: str,
        image_input: str,
        model: str,
        width: int,
        height: int,
        **kwargs
    ) -> str:
        """Submit image-to-video job to Fal."""
        return await self._client.submit_image_to_video(
            prompt=prompt,
            image_input=image_input,
            model=model,
            width=width,
            height=height,
            **kwargs
        )

    async def poll_image_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float,
        model: str = ""
    ) -> List[str]:
        """Poll for image generation completion."""
        return await self._client.poll_until_complete(
            model=model,
            request_id=job_id,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            operation_type="image"
        )

    async def poll_video_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float,
        model: str = ""
    ) -> List[str]:
        """Poll for video generation completion."""
        return await self._client.poll_until_complete(
            model=model,
            request_id=job_id,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            operation_type="video"
        )

    async def download_outputs(
        self,
        output_urls: List[str],
        dest_dir: Path,
        index: int
    ) -> List[Path]:
        """Download outputs from Fal."""
        return await self._client.download_outputs(
            output_urls=output_urls,
            dest_dir=dest_dir,
            index=index
        )

    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "fal"
