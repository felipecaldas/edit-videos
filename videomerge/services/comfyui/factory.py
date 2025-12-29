from __future__ import annotations

from typing import Dict, Optional

from videomerge.services.comfyui.base import ComfyUIClient, ClientType
from videomerge.services.comfyui.local_client import LocalComfyUIClient
from videomerge.services.comfyui.runpod_client import RunPodComfyUIClient
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class ComfyUIClientFactory:
    """Factory to create appropriate ComfyUI client based on environment and type."""

    @staticmethod
    def create_client(
        base_url: str,
        environment: str = "local",
        instance_id: Optional[str] = None,
        client_type: ClientType = ClientType.IMAGE
    ) -> ComfyUIClient:
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


_image_client: Optional[ComfyUIClient] = None
_video_client: Optional[ComfyUIClient] = None
_image_client_config_hash: Optional[str] = None
_video_client_config_hash: Optional[str] = None


def _get_config_hash(client_type: ClientType) -> str:
    """Generate a hash of current ComfyUI configuration for a specific client type."""
    from videomerge.config import (
        ensure_config_current,
        COMFYUI_URL,
        RUN_ENV,
        RUNPOD_IMAGE_INSTANCE_ID,
        RUNPOD_VIDEO_INSTANCE_ID,
    )

    ensure_config_current()
    
    if client_type == ClientType.IMAGE:
        instance_id = RUNPOD_IMAGE_INSTANCE_ID
    else:
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

    from videomerge.config import ensure_config_current

    ensure_config_current()

    current_config_hash = _get_config_hash(client_type)

    if client_type == ClientType.IMAGE:
        client = _image_client
        config_hash = _image_client_config_hash
    else:
        client = _video_client
        config_hash = _video_client_config_hash
    
    if (client is None or 
        force_refresh or 
        config_hash != current_config_hash):
        
        from videomerge.config import COMFYUI_URL, RUN_ENV, RUNPOD_IMAGE_INSTANCE_ID, RUNPOD_VIDEO_INSTANCE_ID
        
        if RUN_ENV == "runpod":
            if client_type == ClientType.IMAGE:
                instance_id = RUNPOD_IMAGE_INSTANCE_ID
                if not instance_id:
                    raise ValueError("RUNPOD_IMAGE_INSTANCE_ID environment variable is required for RunPod image generation")
            else:
                instance_id = RUNPOD_VIDEO_INSTANCE_ID
                if not instance_id:
                    raise ValueError("RUNPOD_VIDEO_INSTANCE_ID environment variable is required for RunPod video generation")
            
            new_client = ComfyUIClientFactory.create_client(COMFYUI_URL, RUN_ENV, instance_id, client_type)
            logger.info("Created new RunPod ComfyUI %s client with instance_id: %s", client_type.value, instance_id)
        else:
            new_client = ComfyUIClientFactory.create_client(COMFYUI_URL, RUN_ENV, client_type=client_type)
            logger.info("Created new local ComfyUI %s client", client_type.value)
        
        if client_type == ClientType.IMAGE:
            _image_client = new_client
            _image_client_config_hash = current_config_hash
        else:
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
            get_comfyui_client(ClientType.IMAGE)
            results["image"] = True
        else:
            results["image"] = False
    
    if client_type is None or client_type == ClientType.VIDEO:
        current_config_hash = _get_config_hash(ClientType.VIDEO)
        if _video_client_config_hash != current_config_hash:
            logger.info("ComfyUI video configuration changed, refreshing client...")
            reset_comfyui_client(ClientType.VIDEO)
            get_comfyui_client(ClientType.VIDEO)
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
