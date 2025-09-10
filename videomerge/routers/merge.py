from pathlib import Path
import uuid
from typing import Optional

from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse

from videomerge.config import TMP_BASE
from videomerge.services.media import get_duration
from videomerge.services.downloads import download_video
from videomerge.utils.logging import get_logger
import subprocess

router = APIRouter(prefix="", tags=["merge"])
logger = get_logger(__name__)


@router.post("/merge")
async def merge_video_audio(
    audio: UploadFile = File(..., description="WAV audio file"),
    video: Optional[UploadFile] = File(None, description="MP4 video file"),
    videoUrl: Optional[str] = Form(None, description="URL to download video from"),
):
    if not video and not videoUrl:
        raise HTTPException(status_code=400, detail="Either 'video' file or 'videoUrl' must be provided")
    if video and videoUrl:
        raise HTTPException(status_code=400, detail="Provide either 'video' file OR 'videoUrl', not both")
    if not (audio.content_type and ('wav' in audio.content_type.lower() or 'audio' in audio.content_type.lower())):
        raise HTTPException(status_code=400, detail="Audio must be WAV format")
    if video and not video.filename.lower().endswith('.mp4'):
        raise HTTPException(status_code=400, detail="Video must be MP4 format")

    session_id = str(uuid.uuid4())
    temp_dir = TMP_BASE / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"[merge] session=%s", session_id)

    try:
        video_path = temp_dir / "input_video.mp4"
        if video:
            logger.info("Saving uploaded video file")
            with open(video_path, "wb") as f:
                content = await video.read()
                f.write(content)
        else:
            logger.info("Downloading video from %s", videoUrl)
            download_video(videoUrl, video_path)

        audio_path = temp_dir / "input_audio.wav"
        logger.info("Saving audio file")
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)

        video_duration = get_duration(video_path)
        audio_duration = get_duration(audio_path)
        logger.info("Durations video=%s audio=%s", video_duration, audio_duration)
        if not video_duration or not audio_duration:
            raise HTTPException(status_code=500, detail="Could not determine media durations")

        output_path = temp_dir / "merged_output.mp4"

        if audio_duration > video_duration:
            speed_ratio = audio_duration / video_duration
            logger.info("Audio longer than video. Speeding audio by x%.2f", speed_ratio)
            sped_audio_path = temp_dir / "sped_audio.wav"
            speed_cmd = [
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                '-i', str(audio_path),
                '-filter:a', f'atempo={speed_ratio}',
                str(sped_audio_path)
            ]
            logger.debug("FFmpeg speed cmd: %s", ' '.join(speed_cmd))
            speed_result = subprocess.run(speed_cmd, capture_output=True, text=True)
            if speed_result.returncode != 0:
                logger.error("Audio speed error: %s", speed_result.stderr)
                raise HTTPException(status_code=500, detail=f"Failed to speed up audio: {speed_result.stderr}")
            final_audio_path = sped_audio_path
        else:
            final_audio_path = audio_path
            logger.info("No speed adjustment needed for audio")

        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(video_path),
            '-i', str(final_audio_path),
            '-filter_complex', '[1:a]loudnorm=I=-14:TP=-1.5:LRA=7[aud]',
            '-map', '0:v:0', '-map', '[aud]',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-shortest',
            '-avoid_negative_ts', 'make_zero',
            str(output_path)
        ]
        logger.debug("FFmpeg merge cmd: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("FFmpeg error rc=%s stderr=%s", result.returncode, result.stderr)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg error: {result.stderr}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="FFmpeg output not created or is empty")

        return FileResponse(path=str(output_path), media_type='video/mp4', filename=f"merged_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[merge] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
