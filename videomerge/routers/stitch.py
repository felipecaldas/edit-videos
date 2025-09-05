from pathlib import Path
import uuid
import shutil
from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from videomerge.config import TMP_BASE
from videomerge.models import (
    StitchRequest,
    FolderStitchRequest,
)
from videomerge.services.downloads import obtain_source_to_path
from videomerge.services.stitcher import concat_videos_with_voiceover
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["stitch"])
logger = get_logger(__name__)


@router.post("/stitch")
async def stitch_videos_with_voiceover(req: Union[StitchRequest, FolderStitchRequest]):
    session_id = str(uuid.uuid4())
    temp_dir = TMP_BASE / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[stitch] session=%s", session_id)

    try:
        voiceover_path: Path
        video_paths: List[Path] = []

        if isinstance(req, StitchRequest):
            if not req.voiceover:
                raise HTTPException(status_code=400, detail="'voiceover' is required")
            if not req.videos or len(req.videos) == 0:
                raise HTTPException(status_code=400, detail="'videos' must contain at least one item")

            voiceover_path = temp_dir / "voiceover.mp3"
            obtain_source_to_path(req.voiceover, voiceover_path)
            if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
                raise HTTPException(status_code=400, detail="Voiceover could not be obtained or is empty")

            for idx, src in enumerate(req.videos):
                vp = temp_dir / f"video_{idx:03d}.mp4"
                obtain_source_to_path(src, vp)
                if not vp.exists() or vp.stat().st_size == 0:
                    raise HTTPException(status_code=400, detail=f"Video at index {idx} could not be obtained or is empty")
                video_paths.append(vp)
        else:
            folder = Path(req.folder_path)
            if not folder.exists() or not folder.is_dir():
                raise HTTPException(status_code=400, detail=f"folder_path does not exist or is not a directory: {folder}")

            mp3s = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"])
            wavs = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".wav"])
            selected_audio: Optional[Path] = mp3s[0] if mp3s else (wavs[0] if wavs else None)
            if not selected_audio:
                raise HTTPException(status_code=400, detail="No mp3 or wav voiceover file found in folder")

            voiceover_path = temp_dir / f"voiceover{selected_audio.suffix.lower()}"
            shutil.copyfile(selected_audio, voiceover_path)
            if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
                raise HTTPException(status_code=400, detail="Voiceover could not be obtained or is empty")

            raw_videos = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"])
            if not raw_videos:
                raise HTTPException(status_code=400, detail="No mp4 video files found in folder")
            for idx, vp_src in enumerate(raw_videos):
                vp = temp_dir / f"video_{idx:03d}.mp4"
                shutil.copyfile(vp_src, vp)
                if not vp.exists() or vp.stat().st_size == 0:
                    raise HTTPException(status_code=400, detail=f"Video at index {idx} could not be obtained or is empty")
                video_paths.append(vp)

        try:
            output_path = concat_videos_with_voiceover(video_paths, voiceover_path, temp_dir / "stitched_output.mp4")
        except Exception as e:
            logger.exception("[stitch] Concat failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

        return FileResponse(path=str(output_path), media_type='video/mp4', filename=f"stitched_{session_id}.mp4")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[stitch] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
