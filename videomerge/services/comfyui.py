import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from videomerge.config import (
    COMFYUI_URL,
    COMFYUI_TIMEOUT_SECONDS,
    COMFYUI_POLL_INTERVAL_SECONDS,
    WORKFLOW_IMAGE_PATH,
)
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def _load_workflow_template(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _inject_prompt(workflow: Dict[str, Any], node_id: str, field: str, text: str) -> None:
    node = workflow.get(node_id)
    if not node or "inputs" not in node:
        raise ValueError(f"Workflow missing node {node_id} or inputs")
    node["inputs"][field] = text


def submit_text_to_image(prompt_text: str, *, client_id: Optional[str] = None, template_path: Optional[Path] = None,
                         prompt_node_id: str = "6", prompt_field: str = "text") -> str:
    """Submit a ComfyUI workflow for text->image and return the prompt_id."""
    client_id = client_id or str(uuid.uuid4())
    tpl_path = template_path or WORKFLOW_IMAGE_PATH
    workflow = _load_workflow_template(tpl_path)
    _inject_prompt(workflow, prompt_node_id, prompt_field, prompt_text)

    url = f"{COMFYUI_URL.rstrip('/')}/prompt"
    payload = {"prompt": workflow, "client_id": client_id}
    logger.info("[comfyui] Submitting text->image prompt to %s", url)
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # ComfyUI returns { "prompt_id": "...", "number": 0, "node_errors": {} }
    prompt_id = data.get("prompt_id") or data.get("promptId")
    if not prompt_id:
        raise ValueError(f"Unexpected response from ComfyUI: {data}")
    return prompt_id


def _parse_history_outputs(hist: Dict[str, Any]) -> List[Tuple[str, Optional[str]]]:
    # Returns list of (filename, subfolder)
    outputs = []
    # hist structure: { prompt_id: { "outputs": { node_id: { "images": [ { filename, subfolder, type }, ... ] } } } }
    for _pid, item in hist.items():
        out = item.get("outputs") or {}
        for _node_id, node_out in out.items():
            imgs = node_out.get("images") or []
            for img in imgs:
                filename = img.get("filename")
                subfolder = img.get("subfolder")
                if filename:
                    outputs.append((filename, subfolder))
    return outputs


def poll_until_complete(prompt_id: str, *, timeout_s: int, poll_interval_s: float) -> List[str]:
    """Poll /history/{prompt_id} until outputs are available or timeout.

    Returns a list of image path hints. We keep filenames (optionally prefixed with subfolder if present).
    """
    url = f"{COMFYUI_URL.rstrip('/')}/history/{prompt_id}"
    logger.info("[comfyui] Polling history for prompt_id=%s", prompt_id)
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 404:
                # Not available yet
                time.sleep(poll_interval_s)
                continue
            resp.raise_for_status()
            data = resp.json()
            hist = data.get("history") or data
            outputs = _parse_history_outputs(hist)
            if outputs:
                # Compose strings; if subfolder provided, keep it in the hint
                result = [f"{sf + '/' if sf else ''}{fn}" for (fn, sf) in outputs]
                return result
        except Exception as e:
            last_error = e
            time.sleep(poll_interval_s)
    raise TimeoutError(f"Timed out waiting for ComfyUI results for {prompt_id}. Last error: {last_error}")


def generate_images_for_prompt(text_prompt: str) -> List[str]:
    """High-level helper: submit text prompt, poll until complete, and return filenames.
    Does not download images; only collects filenames/subfolder hints for later steps.
    """
    pid = submit_text_to_image(text_prompt)
    return poll_until_complete(
        pid,
        timeout_s=COMFYUI_TIMEOUT_SECONDS,
        poll_interval_s=COMFYUI_POLL_INTERVAL_SECONDS,
    )
