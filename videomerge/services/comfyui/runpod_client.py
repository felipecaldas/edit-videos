from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from videomerge.config import (
    COMFYUI_TIMEOUT_SECONDS,
    COMFYUI_POLL_INTERVAL_SECONDS,
    RUNPOD_API_KEY,
)
from videomerge.services.comfyui.base import ComfyUIClient, ClientType
from videomerge.services.comfyui.utils import (
    extract_runpod_outputs,
    output_filename_for_index,
)
from videomerge.services.metrics import (
    image_generation_seconds,
    image_generation_failures_total,
    images_generated_total,
    video_generation_seconds,
    videos_generated_total,
)
from videomerge.utils.logging import get_logger
from videomerge.utils.video_frames import extract_first_and_last_frames

logger = get_logger(__name__)


class RunPodComfyUIClient(ComfyUIClient):
    """ComfyUI client for RunPod serverless environment."""

    def __init__(self, base_url: str, instance_id: str, client_type: ClientType = ClientType.IMAGE):
        super().__init__(base_url)
        self.instance_id = instance_id
        self.client_type = client_type
        self.api_key = RUNPOD_API_KEY
        
        from videomerge.config import COMFY_ORG_API_KEY
        self.comfy_org_api_key = COMFY_ORG_API_KEY
        
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY is required for RunPod serverless API. Please set the environment variable.")

    def _default_headers(self) -> Dict[str, str]:
        """Headers that mimic browser requests to satisfy certain proxies."""
        try:
            parsed = urlparse(self.base_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            origin = self.base_url.rstrip("/")
        
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Origin": origin,
            "Referer": origin + "/",
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        return headers

    def submit_text_to_image(
        self,
        prompt_text: str,
        *,
        template_path: Optional[Path] = None,
        comfyui_workflow_name: Optional[str] = None,
        client_id: Optional[str] = None,
        image_width: Optional[int] = None,
        image_height: Optional[int] = None,
    ) -> str:
        """Submit a text-to-image workflow to RunPod serverless ComfyUI.
        
        Args:
            prompt_text: The text prompt for image generation
            template_path: Deprecated for RunPod, kept for backward compatibility
            comfyui_workflow_name: The workflow name to use (required for RunPod)
            client_id: Optional client ID
            image_width: Image width in pixels
            image_height: Image height in pixels
            
        Returns:
            Job ID from RunPod
        """
        if not comfyui_workflow_name:
            raise ValueError(
                "comfyui_workflow_name is required for RunPod text-to-image generation. "
                "Use IMAGE_STYLE_TO_WORKFLOW_MAPPING to map image_style to comfyui_workflow_name."
            )
        
        workflow_name = comfyui_workflow_name
        start_time = time.time()
        
        try:
            from uuid import uuid4
            client_id = client_id or str(uuid4())

            width = int(image_width) if image_width is not None else 720
            height = int(image_height) if image_height is not None else 1024

            if not self.comfy_org_api_key:
                logger.warning("[comfyui] COMFY_ORG_API_KEY is not configured; RunPod may reject the request")

            payload = {
                "input": {
                    "prompt": prompt_text,
                    "width": width,
                    "height": height,
                    "comfyui_workflow_name": comfyui_workflow_name,
                    "comfy_org_api_key": self.comfy_org_api_key,
                }
            }
            
            logger.info(
                "[comfyui] Submitting text->image to RunPod: workflow=%s, size=%dx%d",
                comfyui_workflow_name, width, height
            )

            url = f"{self.base_url}/v2/{self.instance_id}/run"
            headers = self._default_headers()
            logger.debug("[comfyui] RunPod T2I payload: %s", json.dumps(payload, indent=2))
            
            resp = self._make_request("POST", url, json=payload, timeout=30, headers=headers)
            if not resp.ok:
                try:
                    logger.error("[comfyui] RunPod /run error: status=%s body=%s", resp.status_code, resp.text)
                except Exception:
                    pass
                resp.raise_for_status()
            
            data = resp.json()
            job_id = data.get("id")
            if not job_id:
                raise ValueError(f"Unexpected response from RunPod: {data}")
            
            images_generated_total.labels(workflow=workflow_name).inc()
            logger.info("[comfyui] RunPod T2I job submitted: job_id=%s", job_id)
            return job_id
            
        except Exception as e:
            image_generation_failures_total.labels(reason=type(e).__name__, workflow=workflow_name).inc()
            raise
        finally:
            duration = time.time() - start_time
            image_generation_seconds.labels(step='submit', workflow=workflow_name).observe(duration)

    def submit_image_to_video(
        self,
        prompt_text: str,
        image_data: str,
        *,
        template_path: Path,
        client_id: Optional[str] = None,
        run_id: Optional[str] = None,
        comfyui_workflow_name: Optional[str] = None,
    ) -> str:
        """Submit an image-to-video workflow to RunPod serverless ComfyUI.
        
        Args:
            prompt_text: The video generation prompt
            image_data: Base64 image data URL (e.g., "data:image/png;base64,iVBORw0KGgo...")
            template_path: Deprecated for RunPod, kept for backward compatibility
            client_id: Optional client ID
            run_id: Optional run ID for debugging purposes
            comfyui_workflow_name: The workflow name to use (defaults to video_wan2_2_14B_i2v)
            
        Returns:
            Job ID from RunPod
        """
        from videomerge.config import DEFAULT_I2V_WORKFLOW_NAME
        from uuid import uuid4
        
        workflow_name = comfyui_workflow_name or DEFAULT_I2V_WORKFLOW_NAME
        start_time = time.time()
        
        try:
            client_id = client_id or str(uuid4())
            
            if not image_data.startswith("data:image/"):
                logger.error("[comfyui] Received filename instead of base64 image data - this indicates a workflow error for RunPod")
                raise ValueError("Expected base64 image data URL, but received filename")
            
            logger.info("[comfyui] Using base64 image data for video generation: %s...", image_data[:50])
            
            if "#filename=" in image_data:
                clean_image_data = image_data.split("#filename=")[0]
                logger.debug("[comfyui] Stripped filename metadata from data URL for RunPod payload")
            else:
                clean_image_data = image_data

            if not self.comfy_org_api_key:
                logger.warning("[comfyui] COMFY_ORG_API_KEY is not configured; RunPod may reject the request")

            width = 480
            height = 640
            output_resolution = max(width, height)

            payload = {
                "input": {
                    "prompt": prompt_text,
                    "image": clean_image_data,
                    "width": width,
                    "height": height,
                    "length": 81,
                    "output_resolution": output_resolution,
                    "comfyui_workflow_name": workflow_name,
                    "comfy_org_api_key": self.comfy_org_api_key,
                }
            }
            
            logger.info(
                "[comfyui] Submitting image->video to RunPod: workflow=%s, size=%dx%d, length=%d",
                workflow_name, width, height, 81
            )

            url = f"{self.base_url}/v2/{self.instance_id}/run"
            headers = self._default_headers()
            logger.debug("[comfyui] RunPod I2V payload: %s", json.dumps(payload, indent=2))
            
            resp = self._make_request("POST", url, json=payload, timeout=30, headers=headers)
            if not resp.ok:
                try:
                    logger.error("[comfyui] RunPod /run error: status=%s body=%s", resp.status_code, resp.text)
                except Exception:
                    pass
                resp.raise_for_status()
            
            data = resp.json()
            job_id = data.get("id")
            if not job_id:
                raise ValueError(f"Unexpected response from RunPod: {data}")
            
            videos_generated_total.labels(workflow=workflow_name).inc()
            logger.info("[comfyui] RunPod I2V job submitted: job_id=%s", job_id)
            return job_id
            
        except Exception as e:
            image_generation_failures_total.labels(reason=type(e).__name__, workflow=f"{workflow_name}_video").inc()
            raise
        finally:
            duration = time.time() - start_time
            video_generation_seconds.labels(workflow=workflow_name).observe(duration)

    def poll_until_complete(
        self, prompt_id: str, poll_interval_s: float = COMFYUI_POLL_INTERVAL_SECONDS, timeout_s: int = COMFYUI_TIMEOUT_SECONDS
    ) -> List[str]:
        """Poll RunPod until job completion and return list of output filenames or base64 data URLs."""
        start_time = time.time()
        attempts = 0
        last_error = None
        
        while time.time() - start_time < timeout_s:
            try:
                status_url = f"{self.base_url}/v2/{self.instance_id}/status/{prompt_id}"
                logger.debug("[comfyui] Polling RunPod status at %s", status_url)
                
                resp = self._make_request("GET", status_url, timeout=15, headers=self._default_headers())
                resp.raise_for_status()
                data = resp.json()
                
                logger.debug("[comfyui] RunPod status response: %s", json.dumps(data, indent=2))
                
                raw_status = data.get("status", "")
                status = raw_status.upper()
                logger.debug("[comfyui] RunPod job status='%s' (raw='%s') for prompt_id=%s", status, raw_status, prompt_id)
                
                if status == "COMPLETED":
                    outputs = data.get("output")
                    result_files = extract_runpod_outputs(outputs)

                    if result_files:
                        logger.info("[comfyui] RunPod job completed with %d outputs", len(result_files))
                        return result_files

                    logger.info("[comfyui] RunPod job completed but no outputs found")
                    return []
                elif status in ("FAILED", "ERROR"):
                    error_msg = data.get("error", "Unknown RunPod error")
                    logger.error("[comfyui] RunPod job FAILED for prompt_id=%s: %s", prompt_id, error_msg)
                    logger.error("[comfyui] About to raise RuntimeError to stop temporal workflow")
                    raise RuntimeError(f"RunPod job failed: {error_msg}")
                elif status in ("IN_QUEUE", "RUNNING", "IN_PROGRESS"):
                    attempts += 1
                    logger.debug("[comfyui] RunPod job status=%s. attempt=%d, sleep %.1fs", status, attempts, poll_interval_s)
                    time.sleep(poll_interval_s)
                    continue
                else:
                    attempts += 1
                    logger.warning("[comfyui] RunPod UNKNOWN status='%s'. attempt=%d, sleep %.1fs", status, attempts, poll_interval_s)
                    time.sleep(poll_interval_s)
                    continue
                    
            except requests.exceptions.Timeout as e:
                last_error = e
                attempts += 1
                logger.warning("[comfyui] RunPod polling timeout: %s. attempt=%d, sleep %.1fs", e, attempts, poll_interval_s)
                time.sleep(poll_interval_s)
            except RuntimeError:
                raise
            except requests.exceptions.HTTPError as e:
                last_error = e
                attempts += 1
                logger.warning("[comfyui] RunPod polling HTTP error: %s. attempt=%d, sleep %.1fs", e, attempts, poll_interval_s)
                time.sleep(poll_interval_s)
            except Exception as e:
                last_error = e
                attempts += 1
                logger.warning("[comfyui] RunPod polling error: %s. attempt=%d, sleep %.1fs", e, attempts, poll_interval_s)
                time.sleep(poll_interval_s)
                
        raise TimeoutError(f"Timed out waiting for RunPod results for {prompt_id}. Last error: {last_error}")

    def _extract_video_frames_if_needed(self, video_path: Path, media_type: str, dest_dir: Path) -> None:
        """Extract first and last frames from video files if applicable.
        
        Args:
            video_path: Path to the saved video file
            media_type: MIME type of the file (e.g., "video/mp4")
            dest_dir: Base directory where video was saved (e.g., /data/shared/{run_id})
        """
        media_type_lower = media_type.lower()
        is_video = media_type_lower.startswith("video/") or video_path.suffix.lower() == ".mp4"
        
        if not is_video:
            return
        
        try:
            frames_dir = dest_dir / "first_last"
            frames_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"[comfyui] Extracting first and last frames from {video_path.name}")
            first_frame, last_frame = extract_first_and_last_frames(video_path, frames_dir)
            logger.info(f"[comfyui] Extracted frames: {first_frame.name}, {last_frame.name}")
        except Exception as e:
            logger.warning(f"[comfyui] Failed to extract frames from {video_path.name}: {e}")

    def download_outputs(self, file_hints: List[str], dest_dir: Path) -> List[Path]:
        """Download output files from RunPod by fetching the final status and decoding base64 data.
        
        For video files, also extracts the first and last frames as PNG files to
        /data/shared/{run_id}/first_last/ directory.
        """
        saved: List[Path] = []
        
        for index, hint in enumerate(file_hints):
            if hint.startswith("data:"):
                header, _, remainder = hint.partition(",")
                if not remainder:
                    logger.warning("[comfyui] Skipping malformed data URL output")
                    continue

                data_part, _, filename_meta = remainder.partition("#filename=")
                media_type = header[5:]
                if ";" in media_type:
                    media_type = media_type.split(";", 1)[0]

                try:
                    decoded = base64.b64decode(data_part.strip())
                except Exception as exc:
                    logger.warning("[comfyui] Failed to decode base64 output: %s", exc)
                    continue

                filename = output_filename_for_index(
                    media_type=media_type,
                    provided=filename_meta,
                    index=index,
                )

                dest_dir.mkdir(parents=True, exist_ok=True)
                out_path = dest_dir / filename
                out_path.write_bytes(decoded)
                saved.append(out_path)
                
                self._extract_video_frames_if_needed(out_path, media_type, dest_dir)
                continue

            url = f"{self.base_url}/output/{hint}"
            logger.info("[comfyui] Downloading RunPod output %s from %s", hint, url)
            
            try:
                r = self._make_request("GET", url, stream=True, timeout=60, headers=self._default_headers())
                r.raise_for_status()
                dest_dir.mkdir(parents=True, exist_ok=True)
                content_type = r.headers.get("Content-Type", "application/octet-stream")
                filename = output_filename_for_index(
                    media_type=content_type,
                    provided=hint,
                    index=index,
                )
                out_path = dest_dir / filename
                with out_path.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                saved.append(out_path)
                
                self._extract_video_frames_if_needed(out_path, content_type, dest_dir)
            except Exception as e:
                logger.warning("[comfyui] Failed to download %s from generic endpoint: %s", hint, e)
                continue
                
        return saved

    def fetch_output_bytes(self, hint: str) -> Tuple[str, bytes]:
        """Fetch a single output file from RunPod."""
        if hint.startswith("data:"):
            try:
                header, _, remainder = hint.partition(",")
                if not remainder:
                    raise ValueError("Malformed data URL")

                data_part, _, filename_meta = remainder.partition("#filename=")
                media_type = header[5:]
                if ";" in media_type:
                    media_type = media_type.split(";", 1)[0]

                decoded_data = base64.b64decode(data_part.strip())
                filename = output_filename_for_index(
                    media_type=media_type,
                    provided=filename_meta,
                    index=0,
                )

                logger.info("[comfyui] Decoded base64 data for %s", filename)
                return filename, decoded_data

            except Exception as e:
                logger.error("[comfyui] Failed to decode base64 data: %s", e)
                raise ValueError(f"Failed to decode base64 data: {e}")
        
        url = f"{self.base_url}/output/{hint}"
        try:
            r = self._make_request("GET", url, timeout=60, headers=self._default_headers())
            r.raise_for_status()
            return hint, r.content
        except Exception as e:
            logger.warning("[comfyui] Failed to fetch %s from generic endpoint: %s", hint, e)
            raise

    def upload_image_to_input(self, filename: str, content: bytes, overwrite: bool = True) -> str:
        """Upload image to RunPod for processing."""
        url = f"{self.base_url}/upload"
        files = {"file": (filename, content, "application/octet-stream")}
        data = {"overwrite": "true" if overwrite else "false"}
        logger.info("[comfyui] Uploading image to RunPod: %s", filename)
        resp = self._make_request("POST", url, files=files, data=data, timeout=60, headers=self._default_headers())
        if not resp.ok:
            try:
                logger.error("[comfyui] RunPod upload error: status=%s body=%s", resp.status_code, resp.text)
            except Exception:
                pass
            resp.raise_for_status()
        
        try:
            data = resp.json()
            uploaded_name = data.get("name") or data.get("filename") or filename
        except Exception:
            uploaded_name = filename
        return uploaded_name

    def update_instance_id(self, new_instance_id: str):
        """Update the instance ID for this client."""
        logger.info(
            "Updating RunPodComfyUIClient instance_id from %s to %s",
            self.instance_id,
            new_instance_id
        )
        self.instance_id = new_instance_id
