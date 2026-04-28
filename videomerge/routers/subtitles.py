from pathlib import Path
import uuid
import subprocess
import shutil
from typing import Optional, Union, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from videomerge.config import TMP_BASE
from videomerge.models import (
    SubtitlesRequest,
    StitchWithSubsRequest,
    FolderStitchWithSubsRequest,
    TranscriptionRequest,
    TranscriptionResponse,
    WordTimestamp,
    WordTranscriptionResponse,
)
from videomerge.services.downloads import obtain_source_to_path
from videomerge.services.subtitles import (
    run_whisper_segments,
    run_whisper_segments_with_info,
    build_chunks_from_words,
    write_srt_from_chunks,
    burn_subtitles,
    map_language_to_whisper_code,
)
from videomerge.services.stitcher import (
    concat_videos_with_voiceover,
    generate_and_burn_subtitles as generate_and_burn_subtitles_service,
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

        try:
            stitched_path = concat_videos_with_voiceover(video_paths, voiceover_path, temp_dir / "stitched_output.mp4")
        except Exception as e:
            logger.exception("[stitch+subs] Concat failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

        # Subtitles (reuse helper)
        try:
            final_path = generate_and_burn_subtitles_service(
                stitched_path,
                temp_dir / "stitched_subtitled.mp4",
                language=language,
                model_size=model_size,
                position=subtitle_position or "bottom",
            )
        except Exception as e:
            logger.exception("[stitch+subs] Subtitles failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

        # If this was a folder-based request, also save a copy back to the folder_path
        try:
            if isinstance(req, FolderStitchWithSubsRequest):
                dest_path = folder / "stitched_subtitled.mp4"
                shutil.copyfile(final_path, dest_path)
                logger.info("[stitch+subs] Saved output copy to folder: %s", dest_path)
        except Exception as e:
            # Do not fail the request if the save-back copy fails; log and continue
            logger.warning("[stitch+subs] Failed to save output to folder_path: %s", e)

        return FileResponse(path=str(final_path), media_type='video/mp4', filename=f"stitched_subtitled_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[stitch+subs] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_mp3(req: TranscriptionRequest):
    """Transcribe an MP3 file using Whisper.
    
    - Accepts a path to an MP3 file in /data/shared
    - If language is provided, uses it for transcription
    - If language is not provided, Whisper will auto-detect the language
    - Returns transcribed text and detected language info
    """
    logger.info("[transcribe] Starting transcription for: %s", req.mp3_path)
    
    # Validate the MP3 path is in /data/shared
    mp3_path = Path(req.mp3_path)
    if not str(mp3_path).startswith("/data/shared/"):
        raise HTTPException(status_code=400, detail="MP3 file must be located in /data/shared directory")
    
    # Check if file exists and is accessible
    if not mp3_path.exists():
        raise HTTPException(status_code=404, detail=f"MP3 file not found: {req.mp3_path}")
    
    if not mp3_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {req.mp3_path}")
    
    # Check if it's an MP3 file by extension and basic validation
    if mp3_path.suffix.lower() != '.mp3':
        raise HTTPException(status_code=400, detail="File must have .mp3 extension")
    
    if mp3_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="MP3 file is empty")
    
    try:
        # Prepare language parameter
        whisper_language = None
        if req.language:
            whisper_language = map_language_to_whisper_code(req.language)
            logger.info("[transcribe] Using specified language: %s -> %s", req.language, whisper_language)
        else:
            logger.info("[transcribe] No language specified, Whisper will auto-detect")
        
        # Run Whisper transcription
        logger.info("[transcribe] Running Whisper with model size: %s", req.model_size)
        segments, info = run_whisper_segments_with_info(
            mp3_path, 
            language=whisper_language, 
            model_size=req.model_size
        )
        
        # Combine all segment text
        transcribed_text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        
        # Prepare response
        response = TranscriptionResponse(text=transcribed_text)
        
        # Add language detection info if available
        if info:
            # Whisper info contains language and probability when auto-detected
            detected_lang = getattr(info, 'language', None)
            lang_prob = getattr(info, 'language_probability', None)
            
            if detected_lang:
                response.detected_language = detected_lang
                if lang_prob:
                    response.confidence = float(lang_prob)
                    
                logger.info("[transcribe] Detected language: %s (confidence: %.2f)", detected_lang, lang_prob or 0.0)
        
        logger.info("[transcribe] Transcription completed. Text length: %d chars", len(transcribed_text))
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[transcribe] Transcription failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.post("/transcribe/words", response_model=WordTranscriptionResponse)
async def transcribe_words(req: TranscriptionRequest):
    """Transcribe an MP3 file using Whisper and return per-word timestamps.

    - Accepts a path to an MP3 file in /data/shared
    - Returns one entry per word with start/end times in seconds
    - Used by tabario-video-compositor to build frame-accurate CaptionTrack
    """
    logger.info("[transcribe/words] Starting word-level transcription for: %s", req.mp3_path)

    mp3_path = Path(req.mp3_path)
    if not str(mp3_path).startswith("/data/shared/"):
        raise HTTPException(status_code=400, detail="MP3 file must be located in /data/shared directory")

    if not mp3_path.exists():
        raise HTTPException(status_code=404, detail=f"MP3 file not found: {req.mp3_path}")

    if not mp3_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {req.mp3_path}")

    if mp3_path.suffix.lower() != '.mp3':
        raise HTTPException(status_code=400, detail="File must have .mp3 extension")

    if mp3_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="MP3 file is empty")

    try:
        whisper_language = None
        if req.language:
            whisper_language = map_language_to_whisper_code(req.language)
            logger.info("[transcribe/words] Using specified language: %s -> %s", req.language, whisper_language)
        else:
            logger.info("[transcribe/words] No language specified, Whisper will auto-detect")

        segments, info = run_whisper_segments_with_info(
            mp3_path,
            language=whisper_language,
            model_size=req.model_size,
        )

        words: list[WordTimestamp] = []
        for segment in segments:
            segment_words = getattr(segment, "words", None)
            if segment_words:
                for w in segment_words:
                    words.append(WordTimestamp(
                        word=w.word.strip(),
                        start=float(w.start),
                        end=float(w.end),
                    ))

        response = WordTranscriptionResponse(words=words)

        if info:
            detected_lang = getattr(info, "language", None)
            lang_prob = getattr(info, "language_probability", None)
            if detected_lang:
                response.detected_language = detected_lang
                if lang_prob:
                    response.confidence = float(lang_prob)
                logger.info("[transcribe/words] Detected language: %s (confidence: %.2f)", detected_lang, lang_prob or 0.0)

        logger.info("[transcribe/words] Completed. Word count: %d", len(words))
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[transcribe/words] Transcription failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
