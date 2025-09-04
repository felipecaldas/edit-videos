from pathlib import Path
import uuid
import subprocess
from typing import Optional, Union, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from videomerge.config import TMP_BASE
from videomerge.models import (
    SubtitlesRequest,
    StitchWithSubsRequest,
    FolderStitchWithSubsRequest,
)
from videomerge.services.downloads import obtain_source_to_path
from videomerge.services.subtitles import (
    run_whisper_segments,
    build_chunks_from_words,
    write_srt_from_chunks,
    burn_subtitles,
)
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["subtitles"])
logger = get_logger(__name__)


@router.post("/subtitles")
async def generate_and_burn_subtitles(req: SubtitlesRequest):
    session_id = str(uuid.uuid4())
    temp_dir = TMP_BASE / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        media_path = temp_dir / "input_media"
        obtain_source_to_path(req.source, media_path)
        if not media_path.exists() or media_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Media could not be obtained or is empty")

        probe = subprocess.run([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=index', '-of', 'csv=p=0', str(media_path)
        ], capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            raise HTTPException(status_code=400, detail="Input must contain a video stream to burn subtitles")

        segments = run_whisper_segments(media_path, language=req.language or "pt", model_size=req.model_size or "small")
        srt_path = temp_dir / "generated.srt"
        chunks = build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
        write_srt_from_chunks(chunks, srt_path)

        burned_path = temp_dir / "burned.mp4"
        burn_subtitles(media_path, srt_path, burned_path, position=req.subtitle_position or "bottom", margin_v=None)

        if not burned_path.exists() or burned_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Burned output not created or empty")

        return FileResponse(path=str(burned_path), media_type='video/mp4', filename=f"subtitled_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[/subtitles] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/subtitles/upload")
async def generate_and_burn_subtitles_upload(
    file: UploadFile = File(..., description="Audio or video file"),
    language: Optional[str] = Form("pt"),
    model_size: Optional[str] = Form("small"),
    subtitle_position: Optional[str] = Form("bottom"),
):
    session_id = str(uuid.uuid4())
    temp_dir = TMP_BASE / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        media_path = temp_dir / (file.filename or "upload_input")
        with open(media_path, "wb") as f:
            content = await file.read()
            f.write(content)
        if media_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        probe = subprocess.run([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=index', '-of', 'csv=p=0', str(media_path)
        ], capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            raise HTTPException(status_code=400, detail="Input must contain a video stream to burn subtitles")

        segments = run_whisper_segments(media_path, language=language or "pt", model_size=model_size or "small")
        srt_path = temp_dir / "generated.srt"
        chunks = build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
        write_srt_from_chunks(chunks, srt_path)

        burned_path = temp_dir / "burned.mp4"
        burn_subtitles(media_path, srt_path, burned_path, position=subtitle_position or "bottom", margin_v=None)

        if not burned_path.exists() or burned_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Burned output not created or empty")

        return FileResponse(path=str(burned_path), media_type='video/mp4', filename=f"subtitled_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[/subtitles/upload] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/stitch_with_subtitles")
async def stitch_with_subtitles(req: Union[StitchWithSubsRequest, FolderStitchWithSubsRequest]):
    session_id = str(uuid.uuid4())
    temp_dir = TMP_BASE / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[stitch+subs] session=%s", session_id)

    try:
        # Discover or obtain inputs
        voiceover_path: Path
        video_paths: List[Path] = []

        if isinstance(req, StitchWithSubsRequest):
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
            language = req.language or "pt"
            model_size = req.model_size or "small"
            subtitle_position = req.subtitle_position or "bottom"
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
            import shutil
            shutil.copyfile(selected_audio, voiceover_path)
            if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
                raise HTTPException(status_code=400, detail="Voiceover could not be obtained or is empty")
            raw_videos = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"])
            if not raw_videos:
                raise HTTPException(status_code=400, detail="No mp4 video files found in folder")
            for idx, vp_src in enumerate(raw_videos):
                vp = temp_dir / f"video_{idx:03d}.mp4"
                import shutil
                shutil.copyfile(vp_src, vp)
                if not vp.exists() or vp.stat().st_size == 0:
                    raise HTTPException(status_code=400, detail=f"Video at index {idx} could not be obtained or is empty")
                video_paths.append(vp)
            language = getattr(req, 'language', None) or "pt"
            model_size = getattr(req, 'model_size', None) or "small"
            subtitle_position = getattr(req, 'subtitle_position', None) or "bottom"

        # Concat
        concat_list = temp_dir / "inputs.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in video_paths:
                f.write(f"file '{p.resolve().as_posix()}'\n")

        stitched_path = temp_dir / "stitched_output.mp4"
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
            str(stitched_path)
        ]
        logger.debug("[stitch+subs] FFmpeg concat cmd: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg error: {result.stderr}")
        if not stitched_path.exists() or stitched_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Stitched output not created or empty")

        # Subtitles
        segments = run_whisper_segments(stitched_path, language=language, model_size=model_size)
        srt_path = temp_dir / "generated.srt"
        chunks = build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
        write_srt_from_chunks(chunks, srt_path)

        final_path = temp_dir / "stitched_subtitled.mp4"
        burn_subtitles(stitched_path, srt_path, final_path, position=subtitle_position or "bottom", margin_v=None)
        if not final_path.exists() or final_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Final output not created or empty")

        return FileResponse(path=str(final_path), media_type='video/mp4', filename=f"stitched_subtitled_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[stitch+subs] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
