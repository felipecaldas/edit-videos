from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from videomerge.services.comfyui.base import ComfyUIClient
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class LocalComfyUIClient(ComfyUIClient):
    """ComfyUI client for local development environment."""

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
        """Submit a text-to-image workflow to local ComfyUI."""
        client_id = client_id or str(uuid.uuid4())

        if template_path is None:
            raise ValueError("template_path is required for local ComfyUI text-to-image")
        
        workflow_str = self._load_workflow_template(template_path)
        if "{{ POSITIVE_PROMPT }}" not in workflow_str:
            raise ValueError(
                f"Workflow template '{template_path.name}' is missing the '{{ POSITIVE_PROMPT }}' placeholder."
            )
        
        width = int(image_width) if image_width is not None else 480
        height = int(image_height) if image_height is not None else 480

        escaped_prompt = json.dumps(prompt_text)[1:-1]
        final_workflow_str = workflow_str.replace("{{ POSITIVE_PROMPT }}", escaped_prompt)

        final_workflow_str = final_workflow_str.replace("{{ IMAGE_WIDTH }}", str(width))
        final_workflow_str = final_workflow_str.replace("{{ IMAGE_HEIGHT }}", str(height))
        
        try:
            workflow_json = json.loads(final_workflow_str)
        except json.JSONDecodeError as e:
            logger.error("[comfyui] Failed to parse workflow JSON after prompt injection: %s", e)
            raise ValueError(f"Failed to parse workflow JSON: {e}")

        if isinstance(workflow_json, dict) and isinstance(workflow_json.get("prompt"), dict):
            workflow_payload = workflow_json["prompt"]
        else:
            workflow_payload = workflow_json

        self._coerce_width_height_to_int(workflow_payload)

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
        image_input: str,
        *,
        template_path: Path,
        client_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> str:
        """Submit an image-to-video workflow to local ComfyUI."""
        client_id = client_id or str(uuid.uuid4())
        
        workflow_str = self._load_workflow_template(template_path)
        if "{{ VIDEO_PROMPT }}" not in workflow_str:
            raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ VIDEO_PROMPT }}' placeholder.")
        if "{{ INPUT_IMAGE }}" not in workflow_str:
            raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ INPUT_IMAGE }}' placeholder.")

        if image_input.startswith("data:image/"):
            logger.error("[comfyui] Received base64 image data instead of filename - this indicates a workflow error for local deployment")
            raise ValueError("Expected filename, but received base64 image data")

        escaped_prompt = json.dumps(prompt_text)[1:-1]
        escaped_image = json.dumps(image_input)[1:-1]
        final_workflow_str = workflow_str.replace("{{ VIDEO_PROMPT }}", escaped_prompt)
        final_workflow_str = final_workflow_str.replace("{{ INPUT_IMAGE }}", escaped_image)

        try:
            workflow_json = json.loads(final_workflow_str)
        except json.JSONDecodeError as e:
            logger.error("[comfyui] Failed to parse I2V workflow JSON after injection: %s", e)
            raise ValueError(f"Failed to parse I2V workflow JSON: {e}")

        if isinstance(workflow_json, dict) and isinstance(workflow_json.get("prompt"), dict):
            workflow_payload = workflow_json["prompt"]
        else:
            workflow_payload = workflow_json

        self._warn_if_bad_dimensions(workflow_payload)

        url = f"{self.base_url}/prompt"
        payload = {"prompt": workflow_payload, "client_id": client_id}
        logger.info("[comfyui] Submitting image->video prompt to %s (image=%s)", url, image_input)
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
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, (list, tuple)) and item and item[0] == prompt_id:
                        return None
                    if isinstance(item, dict):
                        pid = item.get("prompt_id") or item.get("id")
                        if pid == prompt_id:
                            return bool(item.get("shouldCheckHistory")) if "shouldCheckHistory" in item else None
                return None
            if isinstance(data, dict):
                for section_key in ("queue_running", "queue_pending", "running", "pending"):
                    items = data.get(section_key) or []
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
        try:
            data = resp.json()
            uploaded_name = data.get("name") or filename
        except Exception:
            uploaded_name = filename
        return uploaded_name
