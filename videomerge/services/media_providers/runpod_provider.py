"""Runpod provider implementation (adapter for existing RunPodComfyUIClient)."""

from __future__ import annotations

from pathlib import Path
from typing import List

from videomerge.services.comfyui.factory import get_image_client, get_video_client
from videomerge.services.media_providers.base import MediaProvider
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class RunpodProvider(MediaProvider):
    """Runpod ComfyUI media generation provider (adapter)."""

    def __init__(self):
        """Initialize Runpod provider using existing client factory."""
        self._image_client = None
        self._video_client = None

    def _get_image_client(self):
        """Lazy-load image client."""
        if self._image_client is None:
            self._image_client = get_image_client()
        return self._image_client

    def _get_video_client(self):
        """Lazy-load video client."""
        if self._video_client is None:
            self._video_client = get_video_client()
        return self._video_client

    async def submit_text_to_image(
        self,
        prompt: str,
        model: str,
        width: int,
        height: int,
        **kwargs
    ) -> str:
        """Submit text-to-image job to Runpod.
        
        Note: For Runpod, 'model' is the workflow name (e.g., 'z-image-photo').
        """
        client = self._get_image_client()
        
        # Extract workflow path from kwargs or derive from model
        workflow_name = kwargs.get("workflow_name", model)
        
        logger.info(
            "[runpod-provider] Submitting text-to-image: workflow=%s, size=%dx%d",
            workflow_name, width, height
        )
        
        # RunPodComfyUIClient.submit_text_to_image returns job_id
        job_id = await client.submit_text_to_image(
            prompt_text=prompt,
            workflow_name=workflow_name,
            image_width=width,
            image_height=height,
            **kwargs
        )
        
        return job_id

    async def submit_image_to_video(
        self,
        prompt: str,
        image_input: str,
        model: str,
        width: int,
        height: int,
        **kwargs
    ) -> str:
        """Submit image-to-video job to Runpod.
        
        Note: For Runpod, 'model' is the workflow name.
        """
        client = self._get_video_client()
        
        workflow_name = kwargs.get("workflow_name", model)
        
        logger.info(
            "[runpod-provider] Submitting image-to-video: workflow=%s, size=%dx%d",
            workflow_name, width, height
        )
        
        # RunPodComfyUIClient.submit_image_to_video returns job_id
        job_id = await client.submit_image_to_video(
            prompt_text=prompt,
            image_data=image_input,
            template_path=Path(f"/app/videomerge/services/comfyui/workflows/{workflow_name}.json"),
            video_width=width,
            video_height=height,
            **kwargs
        )
        
        return job_id

    async def poll_image_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float
    ) -> List[str]:
        """Poll for image generation completion.
        
        Returns:
            List of local file paths (Runpod client downloads automatically)
        """
        client = self._get_image_client()
        
        logger.info("[runpod-provider] Polling image job: %s", job_id)
        
        # RunPodComfyUIClient.poll_for_completion returns list of local paths
        outputs = await client.poll_for_completion(
            job_id=job_id,
            timeout_seconds=timeout_s,
            poll_interval=poll_interval_s
        )
        
        return outputs

    async def poll_video_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float
    ) -> List[str]:
        """Poll for video generation completion.
        
        Returns:
            List of local file paths (Runpod client downloads automatically)
        """
        client = self._get_video_client()
        
        logger.info("[runpod-provider] Polling video job: %s", job_id)
        
        # RunPodComfyUIClient.poll_for_completion returns list of local paths
        outputs = await client.poll_for_completion(
            job_id=job_id,
            timeout_seconds=timeout_s,
            poll_interval=poll_interval_s
        )
        
        return outputs

    async def download_outputs(
        self,
        output_urls: List[str],
        dest_dir: Path,
        index: int
    ) -> List[Path]:
        """Download outputs (no-op for Runpod - already downloaded during polling).
        
        Args:
            output_urls: List of local file paths (already downloaded)
            dest_dir: Destination directory (ignored)
            index: Scene index (ignored)
        
        Returns:
            List of file paths (same as input)
        """
        # Runpod client downloads during polling, so outputs are already local paths
        return [Path(url) for url in output_urls]

    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "runpod"
