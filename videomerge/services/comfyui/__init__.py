"""ComfyUI client package for local and RunPod serverless environments.

This package provides a unified interface for interacting with ComfyUI instances
in both local development and RunPod serverless environments.
"""

from videomerge.services.comfyui.base import ClientType, ComfyUIClient
from videomerge.services.comfyui.factory import (
    ComfyUIClientFactory,
    get_comfyui_client,
    get_image_client,
    get_video_client,
    refresh_comfyui_client,
    reset_comfyui_client,
)
from videomerge.services.comfyui.local_client import LocalComfyUIClient
from videomerge.services.comfyui.runpod_client import RunPodComfyUIClient

__all__ = [
    "ClientType",
    "ComfyUIClient",
    "ComfyUIClientFactory",
    "LocalComfyUIClient",
    "RunPodComfyUIClient",
    "get_comfyui_client",
    "get_image_client",
    "get_video_client",
    "refresh_comfyui_client",
    "reset_comfyui_client",
]
