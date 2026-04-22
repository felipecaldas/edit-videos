"""Fal.ai client for image and video generation.

This module provides a thin wrapper around the fal-client SDK for:
- Text-to-image generation (multiple models)
- Image-to-video generation (Seedance 2.0)
- Polling and output download

All operations are async-friendly and integrate with existing Prometheus metrics.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import time
from pathlib import Path
from typing import List, Optional, Tuple
from uuid import uuid4

import fal_client

from videomerge.config import (
    FAL_AI_API_KEY,
    IMAGE_JOB_TIMEOUT_SECONDS,
    IMAGE_POLL_INTERVAL_SECONDS,
    VIDEO_JOB_TIMEOUT_SECONDS,
    VIDEO_POLL_INTERVAL_SECONDS,
)
from videomerge.services.metrics import (
    image_generation_seconds,
    image_generation_failures_total,
    images_generated_total,
    video_generation_seconds,
    videos_generated_total,
)
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class FalClient:
    """Client for Fal.ai image and video generation."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Fal client.
        
        Args:
            api_key: Fal.ai API key. If None, uses FAL_AI_API_KEY from config.
        """
        self.api_key = api_key or FAL_AI_API_KEY
        if not self.api_key:
            raise ValueError("FAL_AI_API_KEY is required for Fal.ai client")
        
        fal_client.api_key = self.api_key

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
            model: Fal model ID (e.g., "fal-ai/flux/dev")
            width: Image width in pixels (must be multiple of 8)
            height: Image height in pixels (must be multiple of 8)
            **kwargs: Additional model-specific parameters
        
        Returns:
            Request ID for polling
        """
        start_time = time.time()
        
        try:
            arguments = {
                "prompt": prompt,
                "image_size": {"width": width, "height": height},
                **kwargs
            }
            
            logger.info(
                "[fal] Submitting text-to-image: model=%s, size=%dx%d",
                model, width, height
            )
            
            handler = await fal_client.submit_async(model, arguments=arguments)
            request_id = handler.request_id
            
            images_generated_total.labels(workflow=model).inc()
            logger.info("[fal] Text-to-image job submitted: request_id=%s", request_id)
            
            return request_id
            
        except Exception as e:
            image_generation_failures_total.labels(
                reason=type(e).__name__,
                workflow=model
            ).inc()
            logger.error("[fal] Text-to-image submission failed: %s", e)
            raise
        finally:
            duration = time.time() - start_time
            image_generation_seconds.labels(step='submit', workflow=model).observe(duration)

    async def submit_image_to_video(
        self,
        prompt: str,
        image_input: str,
        model: str,
        width: int,
        height: int,
        length: int = 81,
        **kwargs
    ) -> str:
        """Submit an image-to-video generation job.
        
        Args:
            prompt: Video motion/camera prompt
            image_input: Local file path, base64 data URL, or HTTP URL
            model: Fal model ID (e.g., "bytedance/seedance-2.0/image-to-video")
            width: Video width in pixels
            height: Video height in pixels
            length: Number of frames (default 81 = ~3s at 30fps)
            **kwargs: Additional model-specific parameters
        
        Returns:
            Request ID for polling
        """
        start_time = time.time()
        
        try:
            # Handle different image input formats
            if image_input.startswith("data:image/"):
                # Base64 data URL - strip filename metadata if present
                if "#filename=" in image_input:
                    image_url = image_input.split("#filename=")[0]
                else:
                    image_url = image_input
            elif image_input.startswith("http://") or image_input.startswith("https://"):
                # HTTP URL - use as-is (e.g., from user's Supabase bucket)
                logger.info("[fal] Using HTTP URL for image: %s", image_input)
                image_url = image_input
            else:
                # Local file path - convert to data URL
                logger.info("[fal] Converting local image to data URL: %s", image_input)
                image_url = await self._file_to_data_url(image_input)
            
            # Seedance 2.0 expects resolution and aspect_ratio as strings
            is_seedance = "seedance" in model.lower()
            
            if is_seedance:
                # Convert pixel dimensions to resolution string
                resolution = self._pixels_to_resolution(height)
                aspect_ratio = self._pixels_to_aspect_ratio(width, height)
                
                arguments = {
                    "prompt": prompt,
                    "image_url": image_url,
                    "resolution": resolution,
                    "aspect_ratio": aspect_ratio,
                    "length": str(length),
                    "generate_audio": False,
                    **kwargs
                }
                
                logger.info(
                    "[fal] Submitting image-to-video: model=%s, resolution=%s, aspect_ratio=%s, length=%s",
                    model, resolution, aspect_ratio, length
                )
            else:
                # Other models use width/height
                arguments = {
                    "prompt": prompt,
                    "image_url": image_url,
                    "width": width,
                    "height": height,
                    "length": length,
                    **kwargs
                }
                
                logger.info(
                    "[fal] Submitting image-to-video: model=%s, size=%dx%d, length=%d",
                    model, width, height, length
                )
            
            handler = await fal_client.submit_async(model, arguments=arguments)
            request_id = handler.request_id
            
            videos_generated_total.labels(workflow=model).inc()
            logger.info("[fal] Image-to-video job submitted: request_id=%s", request_id)
            
            return request_id
            
        except Exception as e:
            image_generation_failures_total.labels(
                reason=type(e).__name__,
                workflow=f"{model}_video"
            ).inc()
            logger.error("[fal] Image-to-video submission failed: %s", e)
            raise
        finally:
            duration = time.time() - start_time
            video_generation_seconds.labels(workflow=model).observe(duration)

    async def poll_until_complete(
        self,
        model: str,
        request_id: str,
        timeout_s: int,
        poll_interval_s: float,
        operation_type: str = "image"
    ) -> List[str]:
        """Poll until job completes and return output URLs or data URLs.
        
        Args:
            model: Fal model ID
            request_id: Request ID from submit call
            timeout_s: Maximum time to wait in seconds
            poll_interval_s: Seconds between poll attempts
            operation_type: "image" or "video" for logging
        
        Returns:
            List of output URLs or base64 data URLs
        
        Raises:
            TimeoutError: If job doesn't complete within timeout
            RuntimeError: If job fails
        """
        start_time = time.time()
        attempts = 0
        
        while time.time() - start_time < timeout_s:
            try:
                status = fal_client.status(model, request_id, with_logs=False)
                status_str = status.get("status", "UNKNOWN")
                
                logger.debug(
                    "[fal] Poll attempt %d: status=%s, request_id=%s",
                    attempts + 1, status_str, request_id
                )
                
                if status_str == "COMPLETED":
                    result = fal_client.result(model, request_id)
                    outputs = self._extract_outputs(result, operation_type)
                    
                    logger.info(
                        "[fal] Job completed with %d outputs: request_id=%s",
                        len(outputs), request_id
                    )
                    return outputs
                
                elif status_str in ("FAILED", "ERROR"):
                    error_msg = status.get("error", "Unknown Fal error")
                    logger.error("[fal] Job FAILED: request_id=%s, error=%s", request_id, error_msg)
                    raise RuntimeError(f"Fal job failed: {error_msg}")
                
                elif status_str in ("IN_QUEUE", "IN_PROGRESS"):
                    attempts += 1
                    await asyncio.sleep(poll_interval_s)
                    continue
                
                else:
                    attempts += 1
                    logger.warning(
                        "[fal] Unknown status '%s', continuing to poll: request_id=%s",
                        status_str, request_id
                    )
                    await asyncio.sleep(poll_interval_s)
                    continue
                    
            except Exception as e:
                # Check for HTTP errors that shouldn't be retried
                error_str = str(e)
                is_http_error = any(x in error_str for x in ["HTTPError", "422", "400", "401", "403", "404", "500", "502", "503", "504"])
                
                if is_http_error:
                    # HTTP errors should fail immediately - don't retry
                    logger.error("[fal] HTTP error during poll (not retrying): %s, request_id=%s", e, request_id)
                    raise RuntimeError(f"Fal API error (HTTP): {e}")
                
                if isinstance(e, RuntimeError):
                    raise
                    
                attempts += 1
                logger.warning(
                    "[fal] Poll error: %s, attempt=%d, request_id=%s",
                    e, attempts, request_id
                )
                await asyncio.sleep(poll_interval_s)
        
        raise TimeoutError(
            f"Timed out waiting for Fal results: request_id={request_id}, "
            f"timeout={timeout_s}s"
        )

    async def download_outputs(
        self,
        output_urls: List[str],
        dest_dir: Path,
        index: int = 0
    ) -> List[Path]:
        """Download output files from URLs or decode base64 data URLs.
        
        Args:
            output_urls: List of URLs or base64 data URLs
            dest_dir: Destination directory
            index: Scene index for filename generation
        
        Returns:
            List of saved file paths
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved_files: List[Path] = []
        
        for url_idx, url in enumerate(output_urls):
            if url.startswith("data:"):
                # Decode base64 data URL
                path = await self._save_data_url(url, dest_dir, index, url_idx)
                saved_files.append(path)
            else:
                # Download from HTTP URL
                path = await self._download_url(url, dest_dir, index, url_idx)
                saved_files.append(path)
        
        return saved_files

    def _extract_outputs(self, result: dict, operation_type: str) -> List[str]:
        """Extract output URLs from Fal result.
        
        Args:
            result: Result dict from fal_client.result()
            operation_type: "image" or "video"
        
        Returns:
            List of URLs or data URLs
        """
        if operation_type == "image":
            images = result.get("images", [])
            return [img["url"] for img in images if "url" in img]
        else:
            video = result.get("video", {})
            if "url" in video:
                return [video["url"]]
            return []

    async def _file_to_data_url(self, file_path: str) -> str:
        """Convert local file to base64 data URL.
        
        Args:
            file_path: Path to local file
        
        Returns:
            Base64 data URL
        """
        path = Path(file_path)
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/png"
        
        content = await asyncio.to_thread(path.read_bytes)
        b64_data = base64.b64encode(content).decode("utf-8")
        
        return f"data:{mime_type};base64,{b64_data}"

    async def _save_data_url(
        self,
        data_url: str,
        dest_dir: Path,
        index: int,
        url_idx: int
    ) -> Path:
        """Save base64 data URL to file.
        
        Args:
            data_url: Base64 data URL
            dest_dir: Destination directory
            index: Scene index
            url_idx: Output index within scene
        
        Returns:
            Path to saved file
        """
        header, _, remainder = data_url.partition(",")
        if not remainder:
            raise ValueError("Malformed data URL")
        
        # Extract media type
        media_type = header[5:]  # Strip "data:"
        if ";" in media_type:
            media_type = media_type.split(";", 1)[0]
        
        # Decode base64
        decoded = base64.b64decode(remainder.strip())
        
        # Determine extension
        ext = mimetypes.guess_extension(media_type) or ".bin"
        if ext == ".jpe":
            ext = ".jpg"
        
        # Generate filename
        unique_id = str(uuid4())[:8]
        filename = f"{index:03d}_{unique_id}{ext}"
        
        # Save
        out_path = dest_dir / filename
        await asyncio.to_thread(out_path.write_bytes, decoded)
        
        logger.info("[fal] Saved data URL to %s", out_path)
        return out_path

    async def _download_url(
        self,
        url: str,
        dest_dir: Path,
        index: int,
        url_idx: int
    ) -> Path:
        """Download file from HTTP URL.
        
        Args:
            url: HTTP URL
            dest_dir: Destination directory
            index: Scene index
            url_idx: Output index within scene
        
        Returns:
            Path to downloaded file
        """
        import httpx
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            # Determine extension from Content-Type
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            ext = mimetypes.guess_extension(content_type) or ".bin"
            if ext == ".jpe":
                ext = ".jpg"
            
            # Generate filename
            unique_id = str(uuid4())[:8]
            filename = f"{index:03d}_{unique_id}{ext}"
            
            # Save
            out_path = dest_dir / filename
            await asyncio.to_thread(out_path.write_bytes, response.content)
            
            # Convert WebP to PNG if needed
            if ext == ".webp":
                png_path = out_path.with_suffix(".png")
                import subprocess
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(out_path), str(png_path)],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    out_path.unlink()  # Remove original WebP
                    out_path = png_path
                    logger.info("[fal] Converted WebP to PNG: %s", out_path)
                else:
                    logger.warning("[fal] WebP conversion failed: %s", result.stderr)
            
            logger.info("[fal] Downloaded %s to %s", url, out_path)
            return out_path

    def _pixels_to_resolution(self, height: int) -> str:
        """Convert pixel height to Fal resolution string.
        
        Args:
            height: Video height in pixels
            
        Returns:
            Fal resolution string (e.g., "480p", "720p", "1080p")
        """
        if height >= 1080:
            return "1080p"
        elif height >= 720:
            return "720p"
        else:
            return "480p"

    def _pixels_to_aspect_ratio(self, width: int, height: int) -> str:
        """Convert pixel dimensions to Fal aspect_ratio string.
        
        Args:
            width: Video width in pixels
            height: Video height in pixels
            
        Returns:
            Fal aspect_ratio string (e.g., "16:9", "9:16", "1:1")
        """
        # Calculate approximate aspect ratio
        ratio = width / height
        
        if ratio > 1.5:
            return "16:9"
        elif ratio < 0.7:
            return "9:16"
        else:
            return "1:1"
