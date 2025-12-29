from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, List, Optional


def guess_media_type(filename: Optional[str], media_hint: Optional[str]) -> str:
    """Guess MIME type from filename or media hint."""
    if media_hint and "/" in media_hint:
        return media_hint.lower()
    if filename:
        lower = filename.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
        if lower.endswith(".gif"):
            return "image/gif"
        if lower.endswith(".mp4"):
            return "video/mp4"
    return "application/octet-stream"


def default_extension(media_type: str) -> str:
    """Get file extension for a given MIME type."""
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
        "video/mp4": "mp4",
    }
    return mapping.get(media_type.lower(), "bin")


def sanitize_filename(filename: str) -> str:
    """Return a filesystem-safe filename for cross-platform mounts."""
    safe = re.sub(r"[<>:\\|?*\n\r\t]", "_", filename)
    safe = re.sub(r"[\x00-\x1f]", "", safe)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", safe)
    safe = safe.rstrip(" .")
    return safe


def output_filename_for_index(
    *,
    media_type: str,
    provided: Optional[str],
    index: int,
) -> str:
    """Generate a safe filename preserving output order.

    For RunPod video outputs, we *must not* reuse generic ComfyUI filenames
    like ``ComfyUI_00002_.mp4`` across scenes, because they collide within
    the same ``/data/shared/{run_id}`` directory and cause later clips to
    overwrite earlier ones. To avoid this, all video outputs get a fresh
    UUID-based basename while still keeping the per-output index prefix.

    For non-video outputs (e.g. images), we keep the previous behavior of
    attempting to preserve a sanitized version of the provided filename.
    """
    ext = default_extension(media_type)
    media_type_lower = media_type.lower()
    is_video = media_type_lower.startswith("video/") or ext == "mp4"

    if is_video:
        return f"{index:03d}_{uuid.uuid4().hex}.{ext}"

    sanitized: Optional[str] = None

    if provided:
        provided_name = Path(provided).name
        if provided_name:
            sanitized_candidate = sanitize_filename(provided_name)
            if sanitized_candidate:
                sanitized = sanitized_candidate

    if sanitized:
        return f"{index:03d}_{sanitized}"

    return f"{index:03d}_{uuid.uuid4().hex}.{ext}"


def build_data_url(
    base64_data: str,
    filename: Optional[str],
    media_hint: Optional[str] = None,
) -> str:
    """Build a data URL from base64 data and optional filename."""
    media_type = guess_media_type(filename, media_hint)
    payload = base64_data.strip()
    data_url = f"data:{media_type};base64,{payload}"
    if filename:
        data_url = f"{data_url}#filename={filename}"
    return data_url


def extract_runpod_outputs(payload: Any) -> List[str]:
    """Recursively extract output data URLs or filenames from RunPod response payload."""
    results: List[str] = []

    if payload is None:
        return results

    if isinstance(payload, dict):
        base64_value = payload.get("data")
        filename = payload.get("filename")
        media_hint = payload.get("mime") or payload.get("type")
        if isinstance(base64_value, str):
            results.append(build_data_url(base64_value, filename, media_hint))
            return results

        url_value = payload.get("url")
        if isinstance(url_value, str):
            results.append(url_value)

        for key in ("output", "outputs", "images", "videos", "gifs", "files", "result", "items"):
            if key in payload:
                results.extend(extract_runpod_outputs(payload[key]))
        return results

    if isinstance(payload, list):
        for item in payload:
            results.extend(extract_runpod_outputs(item))
        return results

    if isinstance(payload, str):
        results.append(payload)

    return results
