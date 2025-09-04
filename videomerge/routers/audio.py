from pathlib import Path
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from videomerge.config import TMP_BASE
from videomerge.services.media import get_duration
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["audio"])
logger = get_logger(__name__)


@router.post("/audio_duration")
async def get_audio_duration(audio: UploadFile = File(..., description="MP3 or WAV audio file")):
    if not (audio.content_type and ('audio' in audio.content_type.lower() or 
                                   'wav' in audio.content_type.lower() or 
                                   'mp3' in audio.content_type.lower())):
        raise HTTPException(status_code=400, detail="File must be an audio format (MP3 or WAV)")

    session_id = str(uuid.uuid4())
    temp_dir = TMP_BASE / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        audio_path = temp_dir / "input_audio"
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)

        duration = get_duration(audio_path)
        if not duration:
            raise HTTPException(status_code=500, detail="Could not determine audio duration")

        return JSONResponse(content={"duration": duration})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[audio_duration] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
