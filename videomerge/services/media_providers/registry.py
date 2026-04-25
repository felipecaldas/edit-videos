"""Media provider registry for routing generation requests."""

from __future__ import annotations

from typing import Literal

from videomerge.services.media_providers.base import MediaProvider
from videomerge.services.media_providers.fal_provider import FalProvider
from videomerge.services.media_providers.runpod_provider import RunpodProvider
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)

# Singleton instances
_fal_provider: FalProvider | None = None
_runpod_provider: RunpodProvider | None = None


def get_image_provider(provider: Literal["fal", "runpod"]) -> MediaProvider:
    """Get image generation provider instance.
    
    Args:
        provider: Provider identifier ("fal" or "runpod")
    
    Returns:
        MediaProvider instance
    
    Raises:
        ValueError: If provider is not supported
    """
    global _fal_provider, _runpod_provider
    
    if provider == "fal":
        if _fal_provider is None:
            logger.info("[registry] Initializing Fal image provider")
            _fal_provider = FalProvider()
        return _fal_provider
    
    elif provider == "runpod":
        if _runpod_provider is None:
            logger.info("[registry] Initializing Runpod image provider")
            _runpod_provider = RunpodProvider()
        return _runpod_provider
    
    else:
        raise ValueError(f"Unsupported image provider: {provider}")


def get_video_provider(provider: Literal["fal", "runpod"]) -> MediaProvider:
    """Get video generation provider instance.
    
    Args:
        provider: Provider identifier ("fal" or "runpod")
    
    Returns:
        MediaProvider instance
    
    Raises:
        ValueError: If provider is not supported
    """
    # Video and image providers use the same instances
    return get_image_provider(provider)


def reset_providers() -> None:
    """Reset provider singletons (for testing)."""
    global _fal_provider, _runpod_provider
    _fal_provider = None
    _runpod_provider = None
    logger.debug("[registry] Provider singletons reset")
