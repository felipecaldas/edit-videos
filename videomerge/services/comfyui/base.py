from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from videomerge.config import (
    COMFYUI_TIMEOUT_SECONDS,
    COMFYUI_POLL_INTERVAL_SECONDS,
)
from videomerge.services.metrics import (
    comfyui_request_seconds,
    comfyui_requests_total,
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
        """Submit a text-to-image workflow and return the prompt_id."""
        pass

    @abstractmethod
    def submit_image_to_video(
        self,
        prompt_text: str,
        image_input: str,
        *,
        template_path: Path,
        client_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> str:
        """Submit an image-to-video workflow and return the prompt_id.
        
        Args:
            prompt_text: The video generation prompt
            image_input: For local deployment, a filename; for RunPod, base64 image data URL
            template_path: Path to the workflow template
            client_id: Optional client ID
            run_id: Optional run ID for debugging purposes
        """
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
                status_code = str(resp.status_code)[0] + 'xx'
                comfyui_requests_total.labels(endpoint=endpoint, status=status_code).inc()
                return resp
            except Exception as e:
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

    @staticmethod
    def _coerce_width_height_to_int(payload: Any) -> None:
        """Recursively coerce digit-only `width`/`height` strings to integers."""

        if isinstance(payload, dict):
            for key, value in list(payload.items()):
                if key in {"width", "height"} and isinstance(value, str):
                    stripped = value.strip()
                    if stripped.isdigit():
                        payload[key] = int(stripped)
                        continue
                ComfyUIClient._coerce_width_height_to_int(value)
            return

        if isinstance(payload, list):
            for item in payload:
                ComfyUIClient._coerce_width_height_to_int(item)
            return

    def _load_workflow_config(self, run_env: str) -> tuple[dict[str, str], Path, Path]:
        """Load workflow configuration."""
        workflows = {
            "local": {
                "t2i": "path/to/t2i/template.json",
                "i2v": "path/to/i2v/template.json",
            },
            "runpod": {
                "t2i": "path/to/t2i/template.json",
                "i2v": "path/to/i2v/template.json",
            },
        }
        workflows_base_path = Path(workflows[run_env]["t2i"]).parent
        workflow_i2v_path = Path(workflows[run_env]["i2v"])
        return workflows, workflows_base_path, workflow_i2v_path

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
            pass

    def _parse_history_outputs(
        self, hist: Dict[str, Any], *, prefer_node_ids: Optional[List[str]] = None
    ) -> List[Tuple[str, Optional[str]]]:
        """Return list of (filename, subfolder) from history outputs."""
        preferred: List[Tuple[str, Optional[str]]] = []
        generic: List[Tuple[str, Optional[str]]] = []

        for _pid, item in hist.items():
            out = item.get("outputs") or {}
            if prefer_node_ids:
                for nid in prefer_node_ids:
                    node_out = out.get(nid) or {}
                    for arr_name in ("images", "videos", "gifs"):
                        for entry in node_out.get(arr_name) or []:
                            fn = entry.get("filename")
                            sf = entry.get("subfolder")
                            if fn:
                                preferred.append((fn, sf))
            for _node_id, node_out in out.items():
                for arr_name in ("images", "videos", "gifs"):
                    for entry in node_out.get(arr_name) or []:
                        fn = entry.get("filename")
                        sf = entry.get("subfolder")
                        if fn:
                            generic.append((fn, sf))

        return preferred if preferred else generic
