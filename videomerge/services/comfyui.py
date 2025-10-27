import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from videomerge.config import (
    COMFYUI_URL,
    COMFYUI_TIMEOUT_SECONDS,
    COMFYUI_POLL_INTERVAL_SECONDS,
)
from videomerge.utils.logging import get_logger
from videomerge.services.metrics import (
    comfyui_requests_total,
    comfyui_request_seconds,
)

logger = get_logger(__name__)


def _make_comfyui_request(method: str, url: str, **kwargs) -> requests.Response:
    """Make HTTP request to ComfyUI with metrics collection."""
    endpoint = url.replace(COMFYUI_URL.rstrip('/'), '').lstrip('/')

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


def _load_workflow_template(path: Path) -> str:
    """Load a workflow JSON template as a raw string."""
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def _default_headers() -> Dict[str, str]:
    """Headers that mimic browser requests to satisfy certain proxies (e.g., RunPod).

    Derives Origin/Referer from COMFYUI_URL base.
    """
    try:
        parsed = urlparse(COMFYUI_URL)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        origin = COMFYUI_URL.rstrip("/")
    return {
        "Accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Origin": origin,
        "Referer": origin + "/",
    }


def _warn_if_bad_dimensions(workflow: Dict[str, Any]) -> None:
    """Log warnings if any nodes specify width/height not multiples of 64.

    Many diffusion/video nodes expect both dimensions to be divisible by 64.
    This doesn't fail fast here, but provides context if ComfyUI rejects the prompt (400).
    """
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


def submit_text_to_image(prompt_text: str, *, template_path: Path, client_id: Optional[str] = None) -> str:
    """Submit a ComfyUI workflow for text->image and return the prompt_id."""
    client_id = client_id or str(uuid.uuid4())
    
    # Load the template as a string and validate that the placeholder exists
    workflow_str = _load_workflow_template(template_path)
    if "{{ POSITIVE_PROMPT }}" not in workflow_str:
        raise ValueError(
            f"Workflow template '{template_path.name}' is missing the '{{ POSITIVE_PROMPT }}' placeholder."
        )
    
    # Escape backslashes and quotes in the prompt text before injecting it into the JSON string
    escaped_prompt = json.dumps(prompt_text)[1:-1] # json.dumps wraps with quotes, so we strip them
    final_workflow_str = workflow_str.replace("{{ POSITIVE_PROMPT }}", escaped_prompt)
    
    # Parse the final string into a JSON object
    try:
        workflow_json = json.loads(final_workflow_str)
    except json.JSONDecodeError as e:
        logger.error("[comfyui] Failed to parse workflow JSON after prompt injection: %s", e)
        raise ValueError(f"Failed to parse workflow JSON: {e}")

    # The workflow might be wrapped in a 'prompt' key, or it might be the root object
    if isinstance(workflow_json, dict) and isinstance(workflow_json.get("prompt"), dict):
        workflow_payload = workflow_json["prompt"]
    else:
        workflow_payload = workflow_json

    url = f"{COMFYUI_URL.rstrip('/')}/prompt"
    payload = {"prompt": workflow_payload, "client_id": client_id}
    logger.info("[comfyui] Submitting text->image prompt to %s", url)
    resp = _make_comfyui_request("POST", url, json=payload, timeout=30, headers=_default_headers())
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
        r = _make_comfyui_request("GET", q_url, timeout=10, headers=_default_headers())
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
            resp = _make_comfyui_request("GET", hist_url, timeout=15, headers=_default_headers())
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


def generate_images_for_prompt(text_prompt: str, template_path: Path) -> List[str]:
    """High-level helper: submit text prompt, poll until complete, and return filenames.
    Does not download images; only collects filenames/subfolder hints for later steps.
    """
    from videomerge.services.comfyui_client import get_comfyui_client
    client = get_comfyui_client()
    pid = client.submit_text_to_image(text_prompt, template_path=template_path)
    return client.poll_until_complete(
        pid,
        timeout_s=COMFYUI_TIMEOUT_SECONDS,
        poll_interval_s=COMFYUI_POLL_INTERVAL_SECONDS,
    )


def submit_image_to_video(
    prompt_text: str,
    image_filename: str,
    *,
    template_path: Path,
    client_id: Optional[str] = None,
) -> str:
    """Submit a ComfyUI image->video workflow and return the prompt_id."""
    client_id = client_id or str(uuid.uuid4())
    
    # Load the template as a string and validate placeholders
    workflow_str = _load_workflow_template(template_path)
    if "{{ VIDEO_PROMPT }}" not in workflow_str:
        raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ VIDEO_PROMPT }}' placeholder.")
    if "{{ INPUT_IMAGE }}" not in workflow_str:
        raise ValueError(f"Workflow template '{template_path.name}' is missing '{{ INPUT_IMAGE }}' placeholder.")

    # Escape and replace placeholders
    escaped_prompt = json.dumps(prompt_text)[1:-1]
    escaped_image = json.dumps(image_filename)[1:-1]
    final_workflow_str = workflow_str.replace("{{ VIDEO_PROMPT }}", escaped_prompt)
    final_workflow_str = final_workflow_str.replace("{{ INPUT_IMAGE }}", escaped_image)

    # Parse the final string into a JSON object
    try:
        workflow_json = json.loads(final_workflow_str)
    except json.JSONDecodeError as e:
        logger.error("[comfyui] Failed to parse I2V workflow JSON after injection: %s", e)
        raise ValueError(f"Failed to parse I2V workflow JSON: {e}")

    # The workflow might be wrapped in a 'prompt' key, or it might be the root object
    if isinstance(workflow_json, dict) and isinstance(workflow_json.get("prompt"), dict):
        workflow_payload = workflow_json["prompt"]
    else:
        workflow_payload = workflow_json

    # Dimension check (optional, can be done on the parsed payload)
    _warn_if_bad_dimensions(workflow_payload)

    url = f"{COMFYUI_URL.rstrip('/')}/prompt"
    payload = {"prompt": workflow_payload, "client_id": client_id}
    logger.info("[comfyui] Submitting image->video prompt to %s (image=%s)", url, image_filename)
    resp = _make_comfyui_request("POST", url, json=payload, timeout=30, headers=_default_headers())
    # If ComfyUI rejects the workflow (400), log the response body for diagnostics
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


def download_outputs(file_hints: List[str], dest_dir: Path) -> List[Path]:
    """Download output files (images or videos) by filename/subfolder hints to dest_dir.

    Accepts strings like "sub/filename.mp4" or "filename.png".
    Returns list of saved Paths.
    """
    saved: List[Path] = []
    for hint in file_hints:
        if "/" in hint:
            # Split on the LAST slash so nested subfolders are preserved.
            # Example: "Hunyuan/videos/24/vid_00010.mp4" ->
            #   subfolder="Hunyuan/videos/24", filename="vid_00010.mp4"
            subfolder, filename = hint.rsplit("/", 1)
        else:
            subfolder, filename = "", hint
        params = {"filename": filename, "type": "output"}
        if subfolder:
            params["subfolder"] = subfolder
        url = f"{COMFYUI_URL.rstrip('/')}/view"
        logger.info("[comfyui] Downloading output %s from %s", hint, url)
        r = _make_comfyui_request("GET", url, params=params, stream=True, timeout=60, headers=_default_headers())
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
        # Use last slash to preserve nested subfolders
        subfolder, filename = hint.rsplit("/", 1)
    else:
        subfolder, filename = "", hint
    params = {"filename": filename, "type": "output"}
    if subfolder:
        params["subfolder"] = subfolder
    url = f"{COMFYUI_URL.rstrip('/')}/view"
    r = _make_comfyui_request("GET", url, params=params, timeout=60, headers=_default_headers())
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
    resp = _make_comfyui_request("POST", url, files=files, data=data, timeout=60, headers=_default_headers())
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
