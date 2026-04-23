"""Runpod provider implementation (adapter for existing RunPodComfyUIClient)."""

from __future__ import annotations

import asyncio
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

        # model is the comfyui_workflow_name for RunPod
        comfyui_workflow_name = kwargs.pop("workflow_name", model)

        logger.info(
            "[runpod-provider] Submitting text-to-image: workflow=%s, size=%dx%d",
            comfyui_workflow_name, width, height
        )

        job_id = await asyncio.to_thread(
            client.submit_text_to_image,
            prompt,
            comfyui_workflow_name=comfyui_workflow_name,
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

        comfyui_workflow_name = kwargs.pop("workflow_name", model)

        logger.info(
            "[runpod-provider] Submitting image-to-video: workflow=%s, size=%dx%d",
            comfyui_workflow_name, width, height
        )

        job_id = await asyncio.to_thread(
            client.submit_image_to_video,
            prompt,
            image_input,
            comfyui_workflow_name=comfyui_workflow_name,
            video_width=width,
            video_height=height,
            **kwargs
        )

        return job_id

    async def poll_image_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float,
        model: str = ""
    ) -> List[str]:
        """Poll for image generation completion."""
        client = self._get_image_client()

        logger.info("[runpod-provider] Polling image job: %s", job_id)

        outputs = await asyncio.to_thread(
            client.poll_until_complete,
            job_id,
            poll_interval_s,
            timeout_s,
        )

        return outputs

    async def poll_video_generation(
        self,
        job_id: str,
        timeout_s: int,
        poll_interval_s: float,
        model: str = ""
    ) -> List[str]:
        """Poll for video generation completion."""
        client = self._get_video_client()

        logger.info("[runpod-provider] Polling video job: %s", job_id)

        outputs = await asyncio.to_thread(
            client.poll_until_complete,
            job_id,
            poll_interval_s,
            timeout_s,
        )

        return outputs

    async def download_outputs(
        self,
        output_urls: List[str],
        dest_dir: Path,
        index: int
    ) -> List[Path]:
        """No-op for Runpod — outputs are already local paths from polling."""
        return [Path(url) for url in output_urls]

    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "runpod"
