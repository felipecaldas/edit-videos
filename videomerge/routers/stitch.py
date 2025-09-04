from pathlib import Path
import uuid
import shutil
import subprocess
from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from videomerge.config import TMP_BASE
from videomerge.models import (
    StitchRequest,
    FolderStitchRequest,
)
from videomerge.services.downloads import obtain_source_to_path
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

        concat_list = temp_dir / "inputs.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in video_paths:
                f.write(f"file '{p.resolve().as_posix()}'\n")

        output_path = temp_dir / "stitched_output.mp4"
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', str(concat_list),
            '-i', str(voiceover_path),
            '-filter_complex', '[1:a]loudnorm=I=-14:TP=-1.5:LRA=7,apad[aud]',
            '-map', '0:v:0', '-map', '[aud]',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac',
            '-shortest',
            '-movflags', '+faststart',
            str(output_path)
        ]

        logger.debug("[stitch] FFmpeg cmd: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.debug("[stitch] rc=%s stdout=%s stderr=%s", result.returncode, result.stdout, result.stderr)

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg error: {result.stderr}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Output video not created or empty")

        return FileResponse(path=str(output_path), media_type='video/mp4', filename=f"stitched_{session_id}.mp4")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[stitch] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
