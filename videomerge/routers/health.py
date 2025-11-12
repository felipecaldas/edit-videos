from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
from videomerge.services.comfyui_client import (
    refresh_comfyui_client,
    get_image_client,
    get_video_client,
    reset_comfyui_client,
    ClientType,
)
from videomerge.utils.logging import get_logger
import os

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["health"])


class RefreshRequest(BaseModel):
    image_instance_id: Optional[str] = None
    video_instance_id: Optional[str] = None


def update_env_file(var_name: str, value: str) -> None:
    """Update a variable in the .env file.
    
    Args:
        var_name: Name of the environment variable
        value: New value to set
    """
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    
    # Read existing .env file if it exists
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    
    # Update or add the variable
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{var_name}="):
            lines[i] = f"{var_name}={value}\n"
            updated = True
            break
    
    if not updated:
        lines.append(f"{var_name}={value}\n")
    
    # Write back to .env file
    env_path.write_text("".join(lines), encoding="utf-8")


@router.get("/health")
async def health_check():
    return {"status": "healthy"}


@router.post("/refresh-comfyui-client")
async def refresh_comfyui_config(request: RefreshRequest = None):
    """Refresh the ComfyUI client configuration.
    
    Can optionally update the RUNPOD_IMAGE_INSTANCE_ID and/or RUNPOD_VIDEO_INSTANCE_ID 
    environment variables before refreshing. Changes will be persisted to the .env file.
    
    Args:
        request: Optional request body with new instance_id values
    """
    try:
        refresh_results = {}
        updated_vars = {}
        env_updated = False
        
        # Update image instance ID if provided
        if request and request.image_instance_id:
            old_instance_id = os.getenv("RUNPOD_IMAGE_INSTANCE_ID")
            os.environ["RUNPOD_IMAGE_INSTANCE_ID"] = request.image_instance_id
            
            # Update .env file
            update_env_file("RUNPOD_IMAGE_INSTANCE_ID", request.image_instance_id)
            env_updated = True
            
            logger.info(
                "Updated RUNPOD_IMAGE_INSTANCE_ID from %s to %s", 
                old_instance_id, 
                request.image_instance_id
            )
            updated_vars["image_instance_id"] = {
                "old": old_instance_id,
                "new": request.image_instance_id
            }
            
            # Update existing client if it exists
            image_client = get_image_client()
            if hasattr(image_client, 'update_instance_id'):
                image_client.update_instance_id(request.image_instance_id)
            else:
                reset_comfyui_client(ClientType.IMAGE)
        
        # Update video instance ID if provided
        if request and request.video_instance_id:
            old_instance_id = os.getenv("RUNPOD_VIDEO_INSTANCE_ID")
            os.environ["RUNPOD_VIDEO_INSTANCE_ID"] = request.video_instance_id
            
            # Update .env file
            update_env_file("RUNPOD_VIDEO_INSTANCE_ID", request.video_instance_id)
            env_updated = True
            
            logger.info(
                "Updated RUNPOD_VIDEO_INSTANCE_ID from %s to %s", 
                old_instance_id, 
                request.video_instance_id
            )
            updated_vars["video_instance_id"] = {
                "old": old_instance_id,
                "new": request.video_instance_id
            }
            
            # Update existing client if it exists
            video_client = get_video_client()
            if hasattr(video_client, 'update_instance_id'):
                video_client.update_instance_id(request.video_instance_id)
            else:
                reset_comfyui_client(ClientType.VIDEO)
        
        # Reload config if .env was updated
        if env_updated:
            from videomerge.config import reload_config
            reload_config()
            
            # Force refresh all clients
            reset_comfyui_client(ClientType.IMAGE)
            reset_comfyui_client(ClientType.VIDEO)
        
        # Check if configuration has changed and refresh if needed
        if request and (request.image_instance_id or request.video_instance_id):
            # Refresh specific clients that were updated
            if request.image_instance_id:
                refresh_results["image"] = refresh_comfyui_client(ClientType.IMAGE)["image"]
            if request.video_instance_id:
                refresh_results["video"] = refresh_comfyui_client(ClientType.VIDEO)["video"]
        else:
            # Refresh all clients
            refresh_results = refresh_comfyui_client()
        
        # Get current client info
        try:
            image_client = get_image_client()
            video_client = get_video_client()
            
            client_info = {
                "image_client": {
                    "type": type(image_client).__name__,
                    "base_url": image_client.base_url,
                },
                "video_client": {
                    "type": type(video_client).__name__,
                    "base_url": video_client.base_url,
                }
            }
            
            if hasattr(image_client, 'instance_id'):
                client_info["image_client"]["instance_id"] = image_client.instance_id
            if hasattr(video_client, 'instance_id'):
                client_info["video_client"]["instance_id"] = video_client.instance_id
                
        except Exception as e:
            client_info = {"error": f"Failed to get client info: {str(e)}"}
        
        response = {
            "refresh_results": refresh_results,
            "client_info": client_info
        }
        
        if updated_vars:
            response["updated_variables"] = updated_vars
            response["status"] = "updated_and_refreshed"
            response["message"] = "Updated instance IDs and refreshed clients"
        elif any(refresh_results.values()):
            response["status"] = "refreshed"
            response["message"] = "ComfyUI client configuration was updated"
        else:
            response["status"] = "unchanged"
            response["message"] = "No configuration changes detected"
            
        return response
        
    except Exception as e:
        logger.error("Failed to refresh ComfyUI client: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to refresh client: {str(e)}")


@router.get("/comfyui-client-info")
async def get_comfyui_client_info():
    """Get information about the current ComfyUI client configurations."""
    try:
        image_client = get_image_client()
        video_client = get_video_client()
        
        client_info = {
            "image_client": {
                "type": type(image_client).__name__,
                "base_url": image_client.base_url,
                "current_instance_id": os.getenv("RUNPOD_IMAGE_INSTANCE_ID"),
            },
            "video_client": {
                "type": type(video_client).__name__,
                "base_url": video_client.base_url,
                "current_instance_id": os.getenv("RUNPOD_VIDEO_INSTANCE_ID"),
            }
        }
        
        if hasattr(image_client, 'instance_id'):
            client_info["image_client"]["client_instance_id"] = image_client.instance_id
        if hasattr(video_client, 'instance_id'):
            client_info["video_client"]["client_instance_id"] = video_client.instance_id
        
        return {
            "status": "success",
            "clients": client_info
        }
    except Exception as e:
        logger.error("Failed to get ComfyUI client info: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get client info: {str(e)}")
