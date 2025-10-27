"""ComfyUI client abstraction for local and RunPod serverless environments."""

import base64
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from videomerge.config import (
    COMFYUI_TIMEOUT_SECONDS,
    COMFYUI_POLL_INTERVAL_SECONDS,
    RUNPOD_API_KEY,
)
from videomerge.services.metrics import (
    comfyui_request_seconds,
    comfyui_requests_total,
    worker_active,
    image_generation_seconds,
    image_generation_failures_total,
    images_generated_total,
    video_generation_seconds,
    videos_generated_total,
)
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class ClientType(Enum):
    """Type of ComfyUI client."""
    IMAGE = "image"
    VIDEO = "video"


class ComfyUIClient(ABC):
    """Abstract base class for ComfyUI clients."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.timeout_seconds = COMFYUI_TIMEOUT_SECONDS
        self.poll_interval_seconds = COMFYUI_POLL_INTERVAL_SECONDS

    @abstractmethod
    def submit_text_to_image(self, prompt_text: str, *, template_path: Path, client_id: Optional[str] = None) -> str:
        """Submit a text-to-image workflow and return the prompt_id."""
        pass

    @abstractmethod
    def submit_image_to_video(
        self,
        prompt_text: str,
        image_filename: str,
        *,
        template_path: Path,
        client_id: Optional[str] = None,
    ) -> str:
        """Submit an image-to-video workflow and return the prompt_id."""
        pass

    @abstractmethod
    def poll_until_complete(
        self,
        prompt_id: str,
        *,
        timeout_s: int,
        poll_interval_s: float,
        prefer_node_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Poll until workflow is complete and return output file hints."""
        pass

    @abstractmethod
    def download_outputs(self, file_hints: List[str], dest_dir: Path) -> List[Path]:
        """Download output files to destination directory."""
        pass

    @abstractmethod
    def fetch_output_bytes(self, hint: str) -> Tuple[str, bytes]:
        """Fetch a single output file as bytes."""
        pass

    @abstractmethod
    def upload_image_to_input(self, filename: str, content: bytes, overwrite: bool = True) -> str:
        """Upload image to ComfyUI input directory."""
        pass

    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make HTTP request with metrics collection."""
        endpoint = url.replace(self.base_url.rstrip('/'), '').lstrip('/')

        with comfyui_request_seconds.labels(endpoint=endpoint).time():
            try:
                resp = requests.request(method, url, **kwargs)
                status_code = str(resp.status_code)[0] + 'xx'  # Convert to 2xx, 4xx, 5xx format
                comfyui_requests_total.labels(endpoint=endpoint, status=status_code).inc()
                return resp
            except Exception as e:
                # Count network errors as 5xx
                comfyui_requests_total.labels(endpoint=endpoint, status='5xx').inc()
                raise

    def _default_headers(self) -> Dict[str, str]:
        """Headers that mimic browser requests to satisfy certain proxies."""
        try:
            parsed = urlparse(self.base_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            origin = self.base_url.rstrip("/")
        return {
            "Accept": "*/*",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Origin": origin,
            "Referer": origin + "/",
        }

    def _load_workflow_template(self, path: Path) -> str:
        """Load a workflow JSON template as a raw string."""
        with path.open("r", encoding="utf-8") as f:
            return f.read()

    def _warn_if_bad_dimensions(self, workflow: Dict[str, Any]) -> None:
        """Log warnings if any nodes specify width/height not multiples of 64."""
        try:
            offenders = []
            for nid, node in workflow.items():
                inputs = node.get("inputs") if isinstance(node, dict) else None
                if not isinstance(inputs, dict):
                    continue
                w = inputs.get("width")
                h = inputs.get("height")
                if isinstance(w, int) and isinstance(h, int):
                    ok_w = (w % 64 == 0)
                    ok_h = (h % 64 == 0)
                    if not (ok_w and ok_h):
                        offenders.append((nid, node.get("class_type"), w, h))
            if offenders:
                for nid, ctype, w, h in offenders:
                    logger.warning(
                        "[comfyui] dimension warning: node id=%s class=%s width=%s height=%s (expected multiples of 64)",
                        nid,
                        ctype,
                        w,
                        h,
                    )
        except Exception:
            # Never block on diagnostics
            pass

    def _parse_history_outputs(
        self, hist: Dict[str, Any], *, prefer_node_ids: Optional[List[str]] = None
    ) -> List[Tuple[str, Optional[str]]]:
        """Return list of (filename, subfolder) from history outputs."""
        preferred: List[Tuple[str, Optional[str]]] = []
        generic: List[Tuple[str, Optional[str]]] = []

        for _pid, item in hist.items():
            out = item.get("outputs") or {}
            # Preferred nodes first
            if prefer_node_ids:
                for nid in prefer_node_ids:
                    node_out = out.get(nid) or {}
                    for arr_name in ("images", "videos", "gifs"):
                        for entry in node_out.get(arr_name) or []:
                            fn = entry.get("filename")
                            sf = entry.get("subfolder")
                            if fn:
                                preferred.append((fn, sf))
            # Then collect generically from all nodes
            for _node_id, node_out in out.items():
                for arr_name in ("images", "videos", "gifs"):
                    for entry in node_out.get(arr_name) or []:
                        fn = entry.get("filename")
                        sf = entry.get("subfolder")
                        if fn:
                            generic.append((fn, sf))

        return preferred if preferred else generic


class LocalComfyUIClient(ComfyUIClient):
    """ComfyUI client for local development environment."""

    def submit_text_to_image(self, prompt_text: str, *, template_path: Path, client_id: Optional[str] = None) -> str:
        """Submit a text-to-image workflow to local ComfyUI."""
        client_id = client_id or str(uuid.uuid4())
        
        # Load and validate template
        workflow_str = self._load_workflow_template(template_path)
        if "{{ POSITIVE_PROMPT }}" not in workflow_str:
            raise ValueError(
                f"Workflow template '{template_path.name}' is missing the '{{ POSITIVE_PROMPT }}' placeholder."
            )
        
        # Inject prompt
        escaped_prompt = json.dumps(prompt_text)[1:-1]
        final_workflow_str = workflow_str.replace("{{ POSITIVE_PROMPT }}", escaped_prompt)
        
        # Parse JSON
        try:
            workflow_json = json.loads(final_workflow_str)
        except json.JSONDecodeError as e:
            logger.error("[comfyui] Failed to parse workflow JSON after prompt injection: %s", e)
            raise ValueError(f"Failed to parse workflow JSON: {e}")

        # Extract workflow payload
        if isinstance(workflow_json, dict) and isinstance(workflow_json.get("prompt"), dict):
            workflow_payload = workflow_json["prompt"]
        else:
            workflow_payload = workflow_json

        # Submit to ComfyUI
        url = f"{self.base_url}/prompt"
        payload = {"prompt": workflow_payload, "client_id": client_id}
        logger.info("[comfyui] Submitting text->image prompt to %s", url)
        resp = self._make_request("POST", url, json=payload, timeout=30, headers=self._default_headers())
        if not resp.ok:
            try:
                logger.error("[comfyui] /prompt error: status=%s body=%s", resp.status_code, resp.text)
            except Exception:
                pass
            resp.raise_for_status()
        
        data = resp.json()
        prompt_id = data.get("prompt_id") or data.get("promptId")
        if not prompt_id:
            raise ValueError(f"Unexpected response from ComfyUI: {data}")
        return prompt_id

    def submit_image_to_video(
        self,
        prompt_text: str,
        image_filename: str,
        *,
        template_path: Path,
        client_id: Optional[str] = None,
    ) -> str:
        """Submit an image-to-video workflow to local ComfyUI."""
        client_id = client_id or str(uuid.uuid4())
        
        # Load and validate template
        workflow_str = self._load_workflow_template(template_path)
        if "{{ VIDEO_PROMPT }}" not in workflow_str:
            raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ VIDEO_PROMPT }}' placeholder.")
        if "{{ INPUT_IMAGE }}" not in workflow_str:
            raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ INPUT_IMAGE }}' placeholder.")

        # Inject parameters
        escaped_prompt = json.dumps(prompt_text)[1:-1]
        escaped_image = json.dumps(image_filename)[1:-1]
        final_workflow_str = workflow_str.replace("{{ VIDEO_PROMPT }}", escaped_prompt)
        final_workflow_str = final_workflow_str.replace("{{ INPUT_IMAGE }}", escaped_image)

        # Parse JSON
        try:
            workflow_json = json.loads(final_workflow_str)
        except json.JSONDecodeError as e:
            logger.error("[comfyui] Failed to parse I2V workflow JSON after injection: %s", e)
            raise ValueError(f"Failed to parse I2V workflow JSON: {e}")

        # Extract workflow payload
        if isinstance(workflow_json, dict) and isinstance(workflow_json.get("prompt"), dict):
            workflow_payload = workflow_json["prompt"]
        else:
            workflow_payload = workflow_json

        # Dimension check
        self._warn_if_bad_dimensions(workflow_payload)

        # Submit to ComfyUI
        url = f"{self.base_url}/prompt"
        payload = {"prompt": workflow_payload, "client_id": client_id}
        logger.info("[comfyui] Submitting image->video prompt to %s (image=%s)", url, image_filename)
        resp = self._make_request("POST", url, json=payload, timeout=30, headers=self._default_headers())
        if not resp.ok:
            try:
                logger.error("[comfyui] /prompt error: status=%s body=%s", resp.status_code, resp.text)
            except Exception:
                pass
            resp.raise_for_status()
        
        data = resp.json()
        prompt_id = data.get("prompt_id") or data.get("promptId")
        if not prompt_id:
            raise ValueError(f"Unexpected response from ComfyUI: {data}")
        return prompt_id

    def _queue_says_check_history(self, prompt_id: str) -> Optional[bool]:
        """Check if queue indicates we should check history for the prompt."""
        q_url = f"{self.base_url}/queue"
        try:
            r = self._make_request("GET", q_url, timeout=10, headers=self._default_headers())
            r.raise_for_status()
            data = r.json()
            # If the root is a list, try to match by common shapes
            if isinstance(data, list):
                for item in data:
                    # Shape could be [prompt_id, ...]
                    if isinstance(item, (list, tuple)) and item and item[0] == prompt_id:
                        return None  # unknown readiness, but we found it; proceed to history immediately
                    if isinstance(item, dict):
                        pid = item.get("prompt_id") or item.get("id")
                        if pid == prompt_id:
                            return bool(item.get("shouldCheckHistory")) if "shouldCheckHistory" in item else None
                return None
            # Otherwise expect a dict with known sections
            if isinstance(data, dict):
                for section_key in ("queue_running", "queue_pending", "running", "pending"):
                    items = data.get(section_key) or []
                    # Items might be list of ids, list/tuples, or dicts
                    for item in items:
                        if isinstance(item, (list, tuple)) and item:
                            if item[0] == prompt_id:
                                return None
                        elif isinstance(item, str):
                            if item == prompt_id:
                                return None
                        elif isinstance(item, dict):
                            pid = item.get("prompt_id") or item.get("id")
                            if pid == prompt_id:
                                return bool(item.get("shouldCheckHistory")) if "shouldCheckHistory" in item else None
                return None
        except Exception as e:
            logger.debug("[comfyui] queue poll error: %s", e)
            return None

    def poll_until_complete(
        self,
        prompt_id: str,
        *,
        timeout_s: int,
        poll_interval_s: float,
        prefer_node_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Poll local ComfyUI until outputs are available."""
        hist_url = f"{self.base_url}/history"
        logger.info("[comfyui] Polling history for prompt_id=%s (via /history)", prompt_id)
        deadline = time.time() + timeout_s
        last_error = None
        attempts = 0
        while time.time() < deadline:
            try:
                # First consult the queue; only block if it explicitly says not ready
                queue_ready = self._queue_says_check_history(prompt_id)
                if queue_ready is False:
                    attempts += 1
                    logger.debug(
                        "[comfyui] queue indicates not ready (shouldCheckHistory=false). attempt=%d, sleep %.1fs",
                        attempts,
                        poll_interval_s,
                    )
                    time.sleep(poll_interval_s)
                    continue

                # Query history (full), then select our prompt_id entry
                resp = self._make_request("GET", hist_url, timeout=15, headers=self._default_headers())
                resp.raise_for_status()
                data = resp.json()
                hist = data.get("history") or data
                entry = hist.get(prompt_id) or {}
                if not entry:
                    attempts += 1
                    logger.debug("[comfyui] history entry not found for prompt_id. attempt=%d, sleep %.1fs", attempts, poll_interval_s)
                    time.sleep(poll_interval_s)
                    continue

                # Ensure job reports completed if status present
                status = (entry.get("status") or {})
                if status and not status.get("completed"):
                    attempts += 1
                    logger.debug("[comfyui] history found but not completed. attempt=%d, sleep %.1fs", attempts, poll_interval_s)
                    time.sleep(poll_interval_s)
                    continue

                outputs = self._parse_history_outputs({prompt_id: entry}, prefer_node_ids=prefer_node_ids)
                if outputs:
                    result = [f"{sf + '/' if sf else ''}{fn}" for (fn, sf) in outputs]
                    return result
                # No outputs yet; sleep before next attempt
                attempts += 1
                logger.debug("[comfyui] no outputs yet. attempt=%d, sleep %.1fs", attempts, poll_interval_s)
                time.sleep(poll_interval_s)
            except Exception as e:
                last_error = e
                attempts += 1
                logger.debug("[comfyui] polling error: %s. attempt=%d, sleep %.1fs", e, attempts, poll_interval_s)
                time.sleep(poll_interval_s)
        raise TimeoutError(f"Timed out waiting for ComfyUI results for {prompt_id}. Last error: {last_error}")

    def download_outputs(self, file_hints: List[str], dest_dir: Path) -> List[Path]:
        """Download output files from local ComfyUI."""
        saved: List[Path] = []
        for hint in file_hints:
            if "/" in hint:
                subfolder, filename = hint.rsplit("/", 1)
            else:
                subfolder, filename = "", hint
            params = {"filename": filename, "type": "output"}
            if subfolder:
                params["subfolder"] = subfolder
            url = f"{self.base_url}/view"
            logger.info("[comfyui] Downloading output %s from %s", hint, url)
            r = self._make_request("GET", url, params=params, stream=True, timeout=60, headers=self._default_headers())
            r.raise_for_status()
            dest_dir.mkdir(parents=True, exist_ok=True)
            out_path = dest_dir / filename
            with out_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            saved.append(out_path)
        return saved

    def fetch_output_bytes(self, hint: str) -> Tuple[str, bytes]:
        """Fetch a single output file from local ComfyUI."""
        if "/" in hint:
            subfolder, filename = hint.rsplit("/", 1)
        else:
            subfolder, filename = "", hint
        params = {"filename": filename, "type": "output"}
        if subfolder:
            params["subfolder"] = subfolder
        url = f"{self.base_url}/view"
        r = self._make_request("GET", url, params=params, timeout=60, headers=self._default_headers())
        r.raise_for_status()
        return filename, r.content

    def upload_image_to_input(self, filename: str, content: bytes, overwrite: bool = True) -> str:
        """Upload image to local ComfyUI input directory."""
        url = f"{self.base_url}/upload/image"
        files = {"image": (filename, content, "application/octet-stream")}
        data = {"overwrite": "true" if overwrite else "false"}
        logger.info("[comfyui] Uploading image to input: %s", filename)
        resp = self._make_request("POST", url, files=files, data=data, timeout=60, headers=self._default_headers())
        if not resp.ok:
            try:
                logger.error("[comfyui] /upload/image error: status=%s body=%s", resp.status_code, resp.text)
            except Exception:
                pass
            resp.raise_for_status()
        # Some deployments return JSON with name/subfolder/type; fallback to original name
        try:
            data = resp.json()
            uploaded_name = data.get("name") or filename
        except Exception:
            uploaded_name = filename
        return uploaded_name


class RunPodComfyUIClient(ComfyUIClient):
    """ComfyUI client for RunPod serverless environment."""

    def __init__(self, base_url: str, instance_id: str, client_type: ClientType = ClientType.IMAGE):
        super().__init__(base_url)
        self.instance_id = instance_id
        self.client_type = client_type
        self.api_key = RUNPOD_API_KEY
        
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
        
        # Add Authorization header for RunPod API
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        return headers

    def submit_text_to_image(self, prompt_text: str, *, template_path: Path, client_id: Optional[str] = None) -> str:
        """Submit a text-to-image workflow to RunPod serverless ComfyUI."""
        workflow_name = template_path.stem
        start_time = time.time()
        
        try:
            client_id = client_id or str(uuid.uuid4())
            
            # Load and validate template
            workflow_str = self._load_workflow_template(template_path)
            if "{{ POSITIVE_PROMPT }}" not in workflow_str:
                raise ValueError(
                    f"Workflow template '{template_path.name}' is missing the '{{ POSITIVE_PROMPT }}' placeholder."
                )
            
            # Inject prompt
            escaped_prompt = json.dumps(prompt_text)[1:-1]
            final_workflow_str = workflow_str.replace("{{ POSITIVE_PROMPT }}", escaped_prompt)
            
            # Parse JSON - for RunPod, check if it's already wrapped or needs wrapping
            try:
                workflow_data = json.loads(final_workflow_str)
                
                # Check if the workflow is already wrapped in input.workflow
                if "input" in workflow_data and "workflow" in workflow_data["input"]:
                    # Already wrapped (like runpod-t2i-fluxdev.json)
                    payload = workflow_data
                    logger.debug("[comfyui] Using pre-wrapped workflow structure")
                else:
                    # Needs wrapping (like qwen-image-fast-runpod.json)
                    payload = {
                        "input": {
                            "workflow": workflow_data
                        }
                    }
                    logger.debug("[comfyui] Wrapped workflow in input.workflow structure")
                    
            except json.JSONDecodeError as e:
                logger.error("[comfyui] Failed to parse RunPod workflow JSON after prompt injection: %s", e)
                raise ValueError(f"Failed to parse RunPod workflow JSON: {e}")

            # Submit to RunPod using the exact structure from the file
            url = f"{self.base_url}/v2/{self.instance_id}/run"
            headers = self._default_headers()
            logger.info("[comfyui] Submitting text->image prompt to RunPod at %s", url)
            logger.info("[comfyui] RunPod request headers: %s", json.dumps(headers, indent=2))
            logger.info("[comfyui] RunPod request payload: %s", json.dumps(payload, indent=2))
            resp = self._make_request("POST", url, json=payload, timeout=30, headers=headers)
            if not resp.ok:
                try:
                    logger.error("[comfyui] RunPod /run error: status=%s body=%s", resp.status_code, resp.text)
                except Exception:
                    pass
                resp.raise_for_status()
            
            data = resp.json()
            # RunPod returns job ID and status
            job_id = data.get("id")
            if not job_id:
                raise ValueError(f"Unexpected response from RunPod: {data}")
            
            # Record successful image generation submission
            images_generated_total.labels(workflow=workflow_name).inc()
            return job_id
            
        except Exception as e:
            # Record failed image generation
            image_generation_failures_total.labels(reason=type(e).__name__, workflow=workflow_name).inc()
            raise
        finally:
            # Record timing
            duration = time.time() - start_time
            image_generation_seconds.labels(step='submit', workflow=workflow_name).observe(duration)

    def submit_image_to_video(
        self,
        prompt_text: str,
        image_filename: str,
        *,
        template_path: Path,
        client_id: Optional[str] = None,
    ) -> str:
        """Submit an image-to-video workflow to RunPod serverless ComfyUI."""
        workflow_name = template_path.stem
        start_time = time.time()
        
        try:
            client_id = client_id or str(uuid.uuid4())
            
            # Check if image_filename is actually a base64 data URL from image generation
            image_base64 = None
            if image_filename.startswith("data:image/"):
                # This is base64 data from image generation
                image_base64 = image_filename
                logger.info("[comfyui] Using base64 image data for video generation")
            else:
                # This is a traditional filename - we'd need to upload it first
                # For now, we'll assume it's base64 data as per the new workflow
                logger.warning("[comfyui] Expected base64 image data, got filename: %s", image_filename)
            
            # Load and validate template
            workflow_str = self._load_workflow_template(template_path)
            if "{{ POSITIVE_PROMPT }}" not in workflow_str:
                raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ POSITIVE_PROMPT }}' placeholder.")
            
            # For RunPod I2V, we need to construct the input payload with image_base64
            if image_base64:
                # Extract the actual base64 data (remove data:image/...;base64, prefix)
                if "," in image_base64:
                    base64_data = image_base64.split(",", 1)[1]
                else:
                    base64_data = image_base64
                
                # Load the template and inject the prompt and image_base64
                final_workflow_str = workflow_str.replace("{{ POSITIVE_PROMPT }}", prompt_text)
                final_workflow_str = final_workflow_str.replace("data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD...", f"data:image/jpeg;base64,{base64_data}")
                
                # Parse JSON - for RunPod I2V, this should be the complete payload structure
                try:
                    payload = json.loads(final_workflow_str)
                except json.JSONDecodeError as e:
                    logger.error("[comfyui] Failed to parse I2V workflow JSON after injection: %s", e)
                    raise ValueError(f"Failed to parse I2V workflow JSON: {e}")
            else:
                raise ValueError("Base64 image data is required for RunPod video generation")

            # Submit to RunPod using the exact structure from the file
            url = f"{self.base_url}/v2/{self.instance_id}/run"
            headers = self._default_headers()
            logger.info("[comfyui] Submitting image->video prompt to RunPod at %s", url)
            logger.info("[comfyui] RunPod video request headers: %s", json.dumps(headers, indent=2))
            logger.info("[comfyui] RunPod video request payload: %s", json.dumps(payload, indent=2))
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
            
            # Record successful video generation submission
            videos_generated_total.labels(workflow=workflow_name).inc()
            return job_id
            
        except Exception as e:
            # Record failed video generation (using image failures counter as there's no specific video failure counter)
            image_generation_failures_total.labels(reason=type(e).__name__, workflow=f"{workflow_name}_video").inc()
            raise
        finally:
            # Record timing
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
                
                # Log the actual response for debugging
                logger.debug("[comfyui] RunPod status response: %s", json.dumps(data, indent=2))
                
                # Check job status
                raw_status = data.get("status", "")
                status = raw_status.upper()
                logger.debug("[comfyui] RunPod job status='%s' (raw='%s') for prompt_id=%s", status, raw_status, prompt_id)
                
                if status == "COMPLETED":
                    # Extract outputs from RunPod response structure
                    outputs = data.get("output", {})
                    if isinstance(outputs, dict):
                        # RunPod returns base64 encoded image data
                        result_files = []
                        
                        # Handle images - check for both formats
                        images = outputs.get("images", [])
                        if not images and "image_url" in outputs:
                            # Handle single image_url format
                            images = [outputs["image_url"]]
                        
                        for image in images:
                            if isinstance(image, str):
                                # Handle base64 string format (data:image/png;base64,...)
                                if image.startswith("data:image/"):
                                    # Store the full base64 data URL for later use
                                    # We'll use this as the "filename" for video generation
                                    result_files.append(image)
                                else:
                                    # Fallback: treat as filename
                                    result_files.append(image)
                            elif isinstance(image, dict):
                                # Handle new RunPod format: {"data": "iVBORw...", "filename": "...", "type": "base64"}
                                if "data" in image and "filename" in image:
                                    # Construct full base64 data URL
                                    base64_data = image["data"]
                                    filename = image["filename"]
                                    
                                    # Determine image type from filename or default to PNG
                                    if filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'):
                                        data_url = f"data:image/jpeg;base64,{base64_data}"
                                    elif filename.lower().endswith('.webp'):
                                        data_url = f"data:image/webp;base64,{base64_data}"
                                    else:
                                        data_url = f"data:image/png;base64,{base64_data}"
                                    
                                    logger.debug("[comfyui] Constructed base64 data URL for %s", filename)
                                    result_files.append(data_url)
                                elif "filename" in image:
                                    # Fallback: just use filename
                                    filename = image["filename"]
                                    result_files.append(filename)
                        
                        # Handle videos
                        videos = outputs.get("videos", [])
                        for video in videos:
                            if isinstance(video, str) and video.startswith("data:video/"):
                                result_files.append(video)
                            elif isinstance(video, dict) and "filename" in video:
                                filename = video["filename"]
                                result_files.append(filename)
                        
                        # Handle gifs
                        gifs = outputs.get("gifs", [])
                        for gif in gifs:
                            if isinstance(gif, str) and gif.startswith("data:image/gif"):
                                result_files.append(gif)
                            elif isinstance(gif, dict) and "filename" in gif:
                                filename = gif["filename"]
                                result_files.append(filename)
                        
                        if result_files:
                            logger.info("[comfyui] RunPod job completed with %d outputs", len(result_files))
                            return result_files
                    
                    # If we can't parse outputs, return empty list to indicate completion
                    logger.info("[comfyui] RunPod job completed but no outputs found")
                    return []
                elif status in ("FAILED", "ERROR"):
                    error_msg = data.get("error", "Unknown RunPod error")
                    logger.error("[comfyui] RunPod job FAILED for prompt_id=%s: %s", prompt_id, error_msg)
                    logger.error("[comfyui] About to raise RuntimeError to stop temporal workflow")
                    raise RuntimeError(f"RunPod job failed: {error_msg}")
                elif status in ("IN_QUEUE", "RUNNING", "IN_PROGRESS"):
                    # Job still running, continue polling
                    attempts += 1
                    logger.debug("[comfyui] RunPod job status=%s. attempt=%d, sleep %.1fs", status, attempts, poll_interval_s)
                    time.sleep(poll_interval_s)
                    continue
                else:
                    # Unknown status, continue polling
                    attempts += 1
                    logger.warning("[comfyui] RunPod UNKNOWN status='%s'. attempt=%d, sleep %.1fs", status, attempts, poll_interval_s)
                    time.sleep(poll_interval_s)
                    continue
                    
            except requests.exceptions.Timeout as e:
                last_error = e
                attempts += 1
                logger.warning("[comfyui] RunPod polling timeout: %s. attempt=%d, sleep %.1fs", e, attempts, poll_interval_s)
                time.sleep(poll_interval_s)
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

    def download_outputs(self, file_hints: List[str], dest_dir: Path) -> List[Path]:
        """Download output files from RunPod by fetching the final status and decoding base64 data."""
        saved: List[Path] = []
        
        # For RunPod, we need to get the job status to access the base64 data
        # Since we don't have the job_id here, we'll need to modify the approach
        # For now, let's assume the file_hints contain the job_id or we need to store it
        
        # This is a simplified implementation - in practice, you might need to
        # store the job_id when polling and pass it here, or modify the interface
        
        for hint in file_hints:
            # For RunPod, the hint is typically just the filename
            # We need to fetch the actual data from the last status call
            # This is a limitation of the current interface design
            
            # As a fallback, try to download from a generic endpoint
            url = f"{self.base_url}/output/{hint}"
            logger.info("[comfyui] Downloading RunPod output %s from %s", hint, url)
            
            try:
                r = self._make_request("GET", url, stream=True, timeout=60, headers=self._default_headers())
                r.raise_for_status()
                dest_dir.mkdir(parents=True, exist_ok=True)
                out_path = dest_dir / hint
                with out_path.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                saved.append(out_path)
            except Exception as e:
                logger.warning("[comfyui] Failed to download %s from generic endpoint: %s", hint, e)
                # For RunPod, we might need a different approach
                # This could involve storing the base64 data during polling
                # and writing it here instead
                pass
                
        return saved

    def fetch_output_bytes(self, hint: str) -> Tuple[str, bytes]:
        """Fetch a single output file from RunPod."""
        # Check if hint is a base64 data URL
        if hint.startswith("data:image/") or hint.startswith("data:video/"):
            # This is base64 data directly from the RunPod response
            try:
                # Extract the base64 data (remove data:...;base64, prefix)
                if "," in hint:
                    base64_data = hint.split(",", 1)[1]
                else:
                    base64_data = hint
                
                # Decode base64 data
                decoded_data = base64.b64decode(base64_data)
                
                # Generate a filename based on the data type
                if "png" in hint:
                    filename = "generated_image.png"
                elif "jpeg" in hint or "jpg" in hint:
                    filename = "generated_image.jpg"
                elif "gif" in hint:
                    filename = "generated_video.gif"
                elif "mp4" in hint:
                    filename = "generated_video.mp4"
                else:
                    filename = "generated_file"
                
                logger.info("[comfyui] Decoded base64 data for %s", filename)
                return filename, decoded_data
                
            except Exception as e:
                logger.error("[comfyui] Failed to decode base64 data: %s", e)
                raise ValueError(f"Failed to decode base64 data: {e}")
        
        # Fallback to traditional URL-based fetching
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
        # RunPod may have different upload mechanism or require pre-uploaded images
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


class ComfyUIClientFactory:
    """Factory to create appropriate ComfyUI client based on environment and type."""

    @staticmethod
    def create_client(base_url: str, environment: str = "local", instance_id: Optional[str] = None, client_type: ClientType = ClientType.IMAGE) -> ComfyUIClient:
        """Create ComfyUI client for the specified environment and type."""
        environment = environment.lower()
        
        if environment == "runpod":
            if not instance_id:
                raise ValueError(f"instance_id is required for RunPod environment ({client_type.value} client)")
            logger.info("Creating RunPod ComfyUI %s client with instance_id: %s", client_type.value, instance_id)
            return RunPodComfyUIClient(base_url, instance_id, client_type)
        elif environment == "local":
            logger.info("Creating local ComfyUI %s client", client_type.value)
            return LocalComfyUIClient(base_url)
        else:
            raise ValueError(f"Unsupported ComfyUI environment: {environment}")


# Global client instances for image and video generation
_image_client: Optional[ComfyUIClient] = None
_video_client: Optional[ComfyUIClient] = None
_image_client_config_hash: Optional[str] = None
_video_client_config_hash: Optional[str] = None


def _get_config_hash(client_type: ClientType) -> str:
    """Generate a hash of current ComfyUI configuration for a specific client type."""
    from videomerge.config import COMFYUI_URL, RUN_ENV, RUNPOD_IMAGE_INSTANCE_ID, RUNPOD_VIDEO_INSTANCE_ID
    
    if client_type == ClientType.IMAGE:
        instance_id = RUNPOD_IMAGE_INSTANCE_ID
    else:  # ClientType.VIDEO
        instance_id = RUNPOD_VIDEO_INSTANCE_ID
    
    config_str = f"{COMFYUI_URL}|{RUN_ENV}|{instance_id or ''}|{client_type.value}"
    return str(hash(config_str))


def get_comfyui_client(client_type: ClientType = ClientType.IMAGE, force_refresh: bool = False) -> ComfyUIClient:
    """Get the global ComfyUI client instance for a specific type.
    
    Args:
        client_type: Type of client (IMAGE or VIDEO)
        force_refresh: If True, force recreation of the client even if config hasn't changed.
    """
    global _image_client, _video_client, _image_client_config_hash, _video_client_config_hash
    
    current_config_hash = _get_config_hash(client_type)
    
    # Select the appropriate global variables
    if client_type == ClientType.IMAGE:
        client = _image_client
        config_hash = _image_client_config_hash
    else:  # ClientType.VIDEO
        client = _video_client
        config_hash = _video_client_config_hash
    
    # Check if we need to recreate the client
    if (client is None or 
        force_refresh or 
        config_hash != current_config_hash):
        
        from videomerge.config import COMFYUI_URL, RUN_ENV, RUNPOD_IMAGE_INSTANCE_ID, RUNPOD_VIDEO_INSTANCE_ID
        
        if RUN_ENV == "runpod":
            # For RunPod, we need the appropriate instance_id
            if client_type == ClientType.IMAGE:
                instance_id = RUNPOD_IMAGE_INSTANCE_ID
                if not instance_id:
                    raise ValueError("RUNPOD_IMAGE_INSTANCE_ID environment variable is required for RunPod image generation")
            else:  # ClientType.VIDEO
                instance_id = RUNPOD_VIDEO_INSTANCE_ID
                if not instance_id:
                    raise ValueError("RUNPOD_VIDEO_INSTANCE_ID environment variable is required for RunPod video generation")
            
            new_client = ComfyUIClientFactory.create_client(COMFYUI_URL, RUN_ENV, instance_id, client_type)
            logger.info("Created new RunPod ComfyUI %s client with instance_id: %s", client_type.value, instance_id)
        else:
            new_client = ComfyUIClientFactory.create_client(COMFYUI_URL, RUN_ENV, client_type=client_type)
            logger.info("Created new local ComfyUI %s client", client_type.value)
        
        # Update the appropriate global variables
        if client_type == ClientType.IMAGE:
            _image_client = new_client
            _image_client_config_hash = current_config_hash
        else:  # ClientType.VIDEO
            _video_client = new_client
            _video_client_config_hash = current_config_hash
        
        return new_client
    
    return client


def get_image_client() -> ComfyUIClient:
    """Get the ComfyUI client for image generation."""
    return get_comfyui_client(ClientType.IMAGE)


def get_video_client() -> ComfyUIClient:
    """Get the ComfyUI client for video generation."""
    return get_comfyui_client(ClientType.VIDEO)


def refresh_comfyui_client(client_type: Optional[ClientType] = None) -> Dict[str, bool]:
    """Explicitly refresh ComfyUI clients if configuration has changed.
    
    Args:
        client_type: Specific client type to refresh, or None to refresh both.
    
    Returns:
        Dict mapping client types to whether they were refreshed.
    """
    results = {}
    
    if client_type is None or client_type == ClientType.IMAGE:
        current_config_hash = _get_config_hash(ClientType.IMAGE)
        if _image_client_config_hash != current_config_hash:
            logger.info("ComfyUI image configuration changed, refreshing client...")
            reset_comfyui_client(ClientType.IMAGE)
            get_comfyui_client(ClientType.IMAGE)  # This will recreate with new config
            results["image"] = True
        else:
            results["image"] = False
    
    if client_type is None or client_type == ClientType.VIDEO:
        current_config_hash = _get_config_hash(ClientType.VIDEO)
        if _video_client_config_hash != current_config_hash:
            logger.info("ComfyUI video configuration changed, refreshing client...")
            reset_comfyui_client(ClientType.VIDEO)
            get_comfyui_client(ClientType.VIDEO)  # This will recreate with new config
            results["video"] = True
        else:
            results["video"] = False
    
    return results


def reset_comfyui_client(client_type: Optional[ClientType] = None):
    """Reset the global ComfyUI client instance(s) (useful for testing).
    
    Args:
        client_type: Specific client type to reset, or None to reset both.
    """
    global _image_client, _video_client, _image_client_config_hash, _video_client_config_hash
    
    if client_type is None or client_type == ClientType.IMAGE:
        _image_client = None
        _image_client_config_hash = None
    
    if client_type is None or client_type == ClientType.VIDEO:
        _video_client = None
        _video_client_config_hash = None
