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
    WORKFLOW_I2V_PATH,
)
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def _load_workflow_template(path: Path) -> Dict[str, Any]:
    """Load a workflow JSON.

    Supports two shapes:
    1) Flat: { "<node_id>": { ... }, ... }
    2) Wrapped: { "client_id": "...", "prompt": { "<node_id>": { ... } } }

    Always returns the nodes dictionary (shape 1).
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
        return data["prompt"]
    return data


def _find_node_id_by_meta(nodes: Dict[str, Any], *, class_type: str, title_equals: str) -> Optional[str]:
    """Find a node id by matching class_type and _meta.title (case-insensitive).

    Returns the first matching node id, or None if not found.
    """
    target_title = (title_equals or "").strip().lower()
    for nid, node in nodes.items():
        try:
            if node.get("class_type") != class_type:
                continue
            meta = node.get("_meta") or {}
            title = (meta.get("title") or "").strip().lower()
            if title == target_title:
                return nid
        except Exception:
            continue
    return None


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

    # Prefer explicit node id; if absent, fall back to meta-based lookup.
    target_nid = prompt_node_id if str(prompt_node_id) in workflow else None
    if not target_nid:
        auto_nid = _find_node_id_by_meta(
            workflow, class_type="CLIPTextEncode", title_equals="Positive Prompt"
        )
        if not auto_nid:
            # As a last resort, keep legacy behavior to raise helpful error with context
            raise ValueError(
                "Could not locate Positive Prompt node. Tried id='{}' and class_type='CLIPTextEncode' with title='Positive Prompt'"
                .format(prompt_node_id)
            )
        target_nid = auto_nid

    _inject_prompt(workflow, target_nid, prompt_field, prompt_text)

    url = f"{COMFYUI_URL.rstrip('/')}/prompt"
    payload = {"prompt": workflow, "client_id": client_id}
    logger.info("[comfyui] Submitting text->image prompt to %s", url)
    resp = requests.post(url, json=payload, timeout=30)
    if not resp.ok:
        # Log response body to help diagnose node_errors
        try:
            logger.error("[comfyui] /prompt error: status=%s body=%s", resp.status_code, resp.text)
        except Exception:
            pass
        resp.raise_for_status()
    data = resp.json()
    # ComfyUI returns { "prompt_id": "...", "number": 0, "node_errors": {} }
    prompt_id = data.get("prompt_id") or data.get("promptId")
    if not prompt_id:
        raise ValueError(f"Unexpected response from ComfyUI: {data}")
    return prompt_id


def _parse_history_outputs(
    hist: Dict[str, Any], *, prefer_node_ids: Optional[List[str]] = None
) -> List[Tuple[str, Optional[str]]]:
    """Return list of (filename, subfolder) from history outputs.

    If prefer_node_ids is provided, try extracting in that order from those nodes first
    (useful for SaveVideo/GIF nodes that may place outputs under specific keys).
    Supports 'images', 'videos', and 'gifs' arrays.
    """
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


def _queue_says_check_history(prompt_id: str) -> Optional[bool]:
    q_url = f"{COMFYUI_URL.rstrip('/')}/queue"
    try:
        r = requests.get(q_url, timeout=10)
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
    prompt_id: str,
    *,
    timeout_s: int,
    poll_interval_s: float,
    prefer_node_ids: Optional[List[str]] = None,
) -> List[str]:
    """Poll ComfyUI until outputs are available or timeout.

    Strategy: poll /queue and wait for shouldCheckHistory for our prompt, then query /history/{prompt_id}.
    If /queue does not contain our ID, still attempt /history.
    """
    hist_url = f"{COMFYUI_URL.rstrip('/')}/history"
    logger.info("[comfyui] Polling history for prompt_id=%s (via /history)", prompt_id)
    deadline = time.time() + timeout_s
    last_error = None
    attempts = 0
    while time.time() < deadline:
        try:
            # First consult the queue; only block if it explicitly says not ready
            queue_ready = _queue_says_check_history(prompt_id)
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
            resp = requests.get(hist_url, timeout=15)
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

            outputs = _parse_history_outputs({prompt_id: entry}, prefer_node_ids=prefer_node_ids)
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


def submit_image_to_video(prompt_text: str, image_filename: str, *, client_id: Optional[str] = None,
                          template_path: Optional[Path] = None,
                          prompt_node_id: str = "6", prompt_field: str = "text",
                          image_node_id: str = "52", image_field: str = "image") -> str:
    """Submit a ComfyUI image->video workflow and return the prompt_id.

    Injects the prompt into node 6 text, and sets the LoadImage node (52) input image filename.
    """
    client_id = client_id or str(uuid.uuid4())
    tpl_path = template_path or WORKFLOW_I2V_PATH
    workflow = _load_workflow_template(tpl_path)

    # Positive prompt node detection
    text_nid = prompt_node_id if str(prompt_node_id) in workflow else None
    if not text_nid:
        text_nid = _find_node_id_by_meta(
            workflow, class_type="CLIPTextEncode", title_equals="Positive Prompt"
        )
        if not text_nid:
            raise ValueError(
                "Could not locate Positive Prompt node for I2V. Tried id='{}' and meta lookup.".format(prompt_node_id)
            )
    _inject_prompt(workflow, text_nid, prompt_field, prompt_text)

    # LoadImage node detection
    img_nid = image_node_id if str(image_node_id) in workflow else None
    if not img_nid:
        img_nid = _find_node_id_by_meta(
            workflow, class_type="LoadImage", title_equals="Load Image"
        )
        if not img_nid:
            raise ValueError(
                "Could not locate Load Image node. Tried id='{}' and meta lookup.".format(image_node_id)
            )
    node = workflow.get(img_nid)
    if not node or "inputs" not in node:
        raise ValueError(f"Workflow missing node {img_nid} or inputs")
    node["inputs"][image_field] = image_filename

    url = f"{COMFYUI_URL.rstrip('/')}/prompt"
    payload = {"prompt": workflow, "client_id": client_id}
    logger.info("[comfyui] Submitting image->video prompt to %s (image=%s)", url, image_filename)
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    prompt_id = data.get("prompt_id") or data.get("promptId")
    if not prompt_id:
        raise ValueError(f"Unexpected response from ComfyUI: {data}")
    return prompt_id


def download_outputs(file_hints: List[str], dest_dir: Path) -> List[Path]:
    """Download output files (images or videos) by filename/subfolder hints to dest_dir.

    Accepts strings like "sub/filename.mp4" or "filename.png".
    Returns list of saved Paths.
    """
    saved: List[Path] = []
    for hint in file_hints:
        if "/" in hint:
            subfolder, filename = hint.split("/", 1)
        else:
            subfolder, filename = "", hint
        params = {"filename": filename, "type": "output"}
        if subfolder:
            params["subfolder"] = subfolder
        url = f"{COMFYUI_URL.rstrip('/')}/view"
        logger.info("[comfyui] Downloading output %s from %s", hint, url)
        r = requests.get(url, params=params, stream=True, timeout=60)
        r.raise_for_status()
        dest_dir.mkdir(parents=True, exist_ok=True)
        out_path = dest_dir / filename
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        saved.append(out_path)
    return saved


def fetch_output_bytes(hint: str) -> Tuple[str, bytes]:
    """Fetch a single output file from ComfyUI /view and return (filename, bytes)."""
    if "/" in hint:
        subfolder, filename = hint.split("/", 1)
    else:
        subfolder, filename = "", hint
    params = {"filename": filename, "type": "output"}
    if subfolder:
        params["subfolder"] = subfolder
    url = f"{COMFYUI_URL.rstrip('/')}/view"
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return filename, r.content


def upload_image_to_input(filename: str, content: bytes, overwrite: bool = True) -> str:
    """Upload image bytes to ComfyUI input directory via /upload/image and return the stored filename.

    Many ComfyUI setups accept multipart form with key 'image'.
    """
    url = f"{COMFYUI_URL.rstrip('/')}/upload/image"
    files = {"image": (filename, content, "application/octet-stream")}
    data = {"overwrite": "true" if overwrite else "false"}
    logger.info("[comfyui] Uploading image to input: %s", filename)
    resp = requests.post(url, files=files, data=data, timeout=60)
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
