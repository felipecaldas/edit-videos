"""Base interface for media generation providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List


class MediaProvider(ABC):
    """Abstract base class for media generation providers (Fal, Runpod, etc.)."""

    @abstractmethod
    async def submit_text_to_image(
        self,
        prompt: str,
        model: str,
        width: int,
        height: int,
        **kwargs
    ) -> str:
        """Submit a text-to-image generation job.
        
        Args:
            prompt: Image generation prompt
            model: Model identifier (provider-specific)
            width: Image width in pixels
            height: Image height in pixels
            **kwargs: Additional provider-specific parameters
        
        Returns:
            Job ID for polling
        """
        pass

    @abstractmethod
    async def submit_image_to_video(
        self,
        prompt: str,
        image_input: str,
        model: str,
        width: int,
        height: int,
        **kwargs
    ) -> str:
        """Submit an image-to-video generation job.
        
        Args:
            prompt: Video motion/camera prompt
            image_input: Local file path or data URL
            model: Model identifier (provider-specific)
            width: Video width in pixels
            height: Video height in pixels
            **kwargs: Additional provider-specific parameters
        
        Returns:
            Job ID for polling
        """
        pass

    @abstractmethod
    async def poll_image_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float,
        model: str = ""
    ) -> List[str]:
        """Poll for image generation completion.
        
        Args:
            job_id: Job ID from submit_text_to_image
            timeout_s: Maximum time to wait in seconds
            poll_interval_s: Seconds between poll attempts
            model: Model identifier (optional, for providers that need it)
        
        Returns:
            List of output file paths or data URLs
        
        Raises:
            TimeoutError: If job doesn't complete within timeout
            RuntimeError: If job fails
        """
        pass

    @abstractmethod
    async def poll_video_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float
    ) -> List[str]:
        """Poll for video generation completion.
        
        Args:
            job_id: Job ID from submit_image_to_video
            timeout_s: Maximum time to wait in seconds
            poll_interval_s: Seconds between poll attempts
        
        Returns:
            List of output file paths
        
        Raises:
            TimeoutError: If job doesn't complete within timeout
            RuntimeError: If job fails
        """
        pass

    @abstractmethod
    async def download_outputs(
        self,
        output_urls: List[str],
        dest_dir: Path,
        index: int
    ) -> List[Path]:
        """Download output files to local storage.
        
        Args:
            output_urls: List of URLs or data URLs
            dest_dir: Destination directory
            index: Scene index for filename generation
        
        Returns:
            List of saved file paths
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'fal', 'runpod')."""
        pass
