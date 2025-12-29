"""ComfyUI client abstraction for local and RunPod serverless environments.

DEPRECATED: This module has been refactored into a package structure.
All imports are re-exported from videomerge.services.comfyui for backward compatibility.

New code should import from videomerge.services.comfyui directly:
    from videomerge.services.comfyui import (
        ClientType,
        ComfyUIClient,
        LocalComfyUIClient,
        RunPodComfyUIClient,
        get_comfyui_client,
        get_image_client,
        get_video_client,
    )
"""

# Re-export everything from the new package structure for backward compatibility
from videomerge.services.comfyui import (
    ClientType,
    ComfyUIClient,
    ComfyUIClientFactory,
    LocalComfyUIClient,
    RunPodComfyUIClient,
    get_comfyui_client,
    get_image_client,
    get_video_client,
    refresh_comfyui_client,
    reset_comfyui_client,
)

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
