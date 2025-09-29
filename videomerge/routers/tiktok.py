from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from videomerge.services.tiktok import TikTokService
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class TikTokUploadRequest(BaseModel):
    tiktok_bearer_token: str
    file_path: str
    privacy_level: str


def get_tiktok_service():
    return TikTokService()


@router.post("/tiktok/upload", tags=["tiktok"])
async def upload_to_tiktok(
    request: TikTokUploadRequest,
    tiktok_service: TikTokService = Depends(get_tiktok_service)
):
    """
    Endpoint to upload a video to TikTok.
    """
    try:
        logger.info(f"Received request to upload to TikTok: {request.file_path}")
        result = await tiktok_service.upload_video(
            request.tiktok_bearer_token,
            request.file_path,
            request.privacy_level
        )
        return result
    except Exception as e:
        logger.exception("Failed to upload video to TikTok.")
        raise HTTPException(status_code=500, detail=str(e))
