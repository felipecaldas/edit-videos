from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from typing import Optional, List, Union
import json
import subprocess
import tempfile
import os
import uuid
import requests
from pathlib import Path
from pydantic import BaseModel
from faster_whisper import WhisperModel
import shutil

app = FastAPI(title="Video Audio Merger")

def get_duration(file_path):
    """Get duration of media file in seconds using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
        else:
            print(f"FFprobe error: {result.stderr}")
            return None
    except Exception as e:
        print(f"Error getting duration: {e}")
        return None

def download_video(url: str, file_path: Path) -> None:
    """Download video from URL to specified path"""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        # Check if content type is video
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('video/'):
            raise HTTPException(
                status_code=400, 
                detail=f"URL does not point to a video file. Content-Type: {content_type}"
            )
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
    except requests.RequestException as e:
        raise HTTPException(
            status_code=400, 
            detail=f"Failed to download video from URL: {str(e)}"
        )

@app.post("/merge")
async def merge_video_audio(
    audio: UploadFile = File(..., description="WAV audio file"),
    video: Optional[UploadFile] = File(None, description="MP4 video file"),
    videoUrl: Optional[str] = Form(None, description="URL to download video from")
):
    # Validate that exactly one video source is provided
    if not video and not videoUrl:
        raise HTTPException(
            status_code=400, 
            detail="Either 'video' file or 'videoUrl' must be provided"
        )
    
    if video and videoUrl:
        raise HTTPException(
            status_code=400, 
            detail="Provide either 'video' file OR 'videoUrl', not both"
        )
    
    # Validate audio file type by content type instead of filename
    if not (audio.content_type and ('wav' in audio.content_type.lower() or 'audio' in audio.content_type.lower())):
        raise HTTPException(status_code=400, detail="Audio must be WAV format")
    
    # Validate video file type if uploaded
    if video and not video.filename.lower().endswith('.mp4'):
        raise HTTPException(status_code=400, detail="Video must be MP4 format")
    
    # Generate unique ID for this processing session
    session_id = str(uuid.uuid4())
    temp_dir = Path(f"/tmp/media/{session_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Processing session: {session_id}")
    
    try:
        # Handle video input
        video_path = temp_dir / "input_video.mp4"
        
        if video:
            # Save uploaded video file
            print("Saving uploaded video file...")
            with open(video_path, "wb") as f:
                content = await video.read()
                f.write(content)
            print(f"Video saved: {video_path.exists()}, size: {video_path.stat().st_size if video_path.exists() else 0}")
        else:
            # Download video from URL
            print(f"Downloading video from: {videoUrl}")
            download_video(videoUrl, video_path)
            print(f"Video downloaded: {video_path.exists()}, size: {video_path.stat().st_size if video_path.exists() else 0}")
        
        # Save uploaded audio file
        print("Saving audio file...")
        audio_path = temp_dir / "input_audio.wav"
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)
        print(f"Audio saved: {audio_path.exists()}, size: {audio_path.stat().st_size if audio_path.exists() else 0}")
        
        # Get durations of video and audio
        video_duration = get_duration(video_path)
        audio_duration = get_duration(audio_path)
        
        print(f"Video duration: {video_duration}s")
        print(f"Audio duration: {audio_duration}s")
        
        if not video_duration or not audio_duration:
            raise HTTPException(
                status_code=500,
                detail="Could not determine media durations"
            )
        
        # Define output path
        output_path = temp_dir / "merged_output.mp4"
        
        # Check if we need to speed up audio to match video length
        if audio_duration > video_duration:
            # Calculate speed ratio to fit audio into video duration
            speed_ratio = audio_duration / video_duration
            print(f"Audio is longer than video. Speeding up audio by {speed_ratio:.2f}x")
            
            # Create sped-up audio file first
            sped_audio_path = temp_dir / "sped_audio.wav"
            speed_cmd = [
                'ffmpeg', '-y',
                '-i', str(audio_path),
                '-filter:a', f'atempo={speed_ratio}',
                str(sped_audio_path)
            ]
            
            print(f"Running audio speed command: {' '.join(speed_cmd)}")
            speed_result = subprocess.run(speed_cmd, capture_output=True, text=True)
            
            if speed_result.returncode != 0:
                print(f"Audio speed error: {speed_result.stderr}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to speed up audio: {speed_result.stderr}"
                )
            
            # Use the sped-up audio
            final_audio_path = sped_audio_path
        else:
            # Use original audio
            final_audio_path = audio_path
            print("Audio duration is shorter or equal to video duration, no speed adjustment needed")
        
        # Run ffmpeg command to merge video with (possibly sped-up) audio
        # Normalize audio to -14 LUFS, then map processed audio
        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-i', str(final_audio_path),
            '-filter_complex', '[1:a]loudnorm=I=-14:TP=-1.5:LRA=7[aud]',
            '-map', '0:v:0', '-map', '[aud]',
            '-c:v', 'copy',          # Copy video stream
            '-c:a', 'aac',           # Encode audio as AAC
            '-shortest',             # Match shortest stream duration
            '-avoid_negative_ts', 'make_zero',
            str(output_path)
        ]
        
        print(f"Running FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        print(f"FFmpeg return code: {result.returncode}")
        print(f"FFmpeg stdout: {result.stdout}")
        print(f"FFmpeg stderr: {result.stderr}")
        
        if result.returncode != 0:
            raise HTTPException(
                status_code=500, 
                detail=f"FFmpeg error: {result.stderr}"
            )
        
        # Verify output file exists and has content
        if not output_path.exists():
            raise HTTPException(
                status_code=500,
                detail="FFmpeg completed but output file was not created"
            )
            
        if output_path.stat().st_size == 0:
            raise HTTPException(
                status_code=500,
                detail="FFmpeg created empty output file"
            )
        
        print(f"Output file created: {output_path.exists()}, size: {output_path.stat().st_size}")
        
        # Return the merged file
        return FileResponse(
            path=str(output_path),
            media_type='video/mp4',
            filename=f"merged_{session_id}.mp4"
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
    # Note: Cleanup is removed to help with debugging
    # You can add it back later once everything works

class StitchRequest(BaseModel):
    voiceover: str  # URL or absolute/accessible file path to voiceover.mp3
    videos: List[str]  # Ordered list of URLs or file paths to videos

class FolderStitchRequest(BaseModel):
    folder_path: str  # Directory containing one mp3/wav voiceover and mp4 videos

class SubtitlesRequest(BaseModel):
    source: str  # URL or container-visible file path to audio/video
    language: Optional[str] = "pt"  # default Brazilian Portuguese
    model_size: Optional[str] = "small"  # e.g., tiny, base, small, medium, large-v2
    subtitle_position: Optional[str] = "bottom"  # top | middle | bottom

@app.post("/stitch")
async def stitch_videos_with_voiceover(req: Union[StitchRequest, FolderStitchRequest]):
    # Create temp working directory
    session_id = str(uuid.uuid4())
    temp_dir = Path(f"/tmp/media/{session_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)

    print(f"[stitch] Processing session: {session_id}")

    try:
        voiceover_path: Path
        video_paths: List[Path] = []

        # Branch based on request type
        if isinstance(req, StitchRequest):
            # Validate input
            if not req.voiceover:
                raise HTTPException(status_code=400, detail="'voiceover' is required")
            if not req.videos or len(req.videos) == 0:
                raise HTTPException(status_code=400, detail="'videos' must contain at least one item")

            # Resolve/download voiceover (kept as mp3 filename for backward compatibility)
            voiceover_path = temp_dir / "voiceover.mp3"
            obtain_source_to_path(req.voiceover, voiceover_path)
            if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
                raise HTTPException(status_code=400, detail="Voiceover could not be obtained or is empty")

            # Resolve/download videos in order
            for idx, src in enumerate(req.videos):
                vp = temp_dir / f"video_{idx:03d}.mp4"
                obtain_source_to_path(src, vp)
                if not vp.exists() or vp.stat().st_size == 0:
                    raise HTTPException(status_code=400, detail=f"Video at index {idx} could not be obtained or is empty")
                video_paths.append(vp)
        else:
            # Folder mode: discover files inside provided folder
            folder = Path(req.folder_path)
            if not folder.exists() or not folder.is_dir():
                raise HTTPException(status_code=400, detail=f"folder_path does not exist or is not a directory: {folder}")

            # Find audio: prefer mp3 over wav; if multiple, pick first lexicographically
            mp3s = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"])
            wavs = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".wav"])
            selected_audio: Optional[Path] = None
            if mp3s:
                selected_audio = mp3s[0]
            elif wavs:
                selected_audio = wavs[0]
            else:
                raise HTTPException(status_code=400, detail="No mp3 or wav voiceover file found in folder")

            # Copy audio preserving extension
            voiceover_path = temp_dir / f"voiceover{selected_audio.suffix.lower()}"
            shutil.copyfile(selected_audio, voiceover_path)
            if not voiceover_path.exists() or voiceover_path.stat().st_size == 0:
                raise HTTPException(status_code=400, detail="Voiceover could not be obtained or is empty")

            # Find and copy videos, sorted lexicographically
            raw_videos = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"])
            if not raw_videos:
                raise HTTPException(status_code=400, detail="No mp4 video files found in folder")
            for idx, vp_src in enumerate(raw_videos):
                vp = temp_dir / f"video_{idx:03d}.mp4"
                shutil.copyfile(vp_src, vp)
                if not vp.exists() or vp.stat().st_size == 0:
                    raise HTTPException(status_code=400, detail=f"Video at index {idx} could not be obtained or is empty")
                video_paths.append(vp)

        # Prepare concat list file for ffmpeg (use absolute posix paths for portability)
        concat_list = temp_dir / "inputs.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in video_paths:
                # ffmpeg concat demuxer expects: file 'path'
                f.write(f"file '{p.resolve().as_posix()}'\n")

        # Output path
        output_path = temp_dir / "stitched_output.mp4"

        # Build ffmpeg command:
        # - Concat videos via demuxer
        # - Normalize voiceover to -14 LUFS and then pad with silence if shorter; trim if longer (-shortest)
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

        print(f"[stitch] Running FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(f"[stitch] FFmpeg return code: {result.returncode}")
        print(f"[stitch] FFmpeg stdout: {result.stdout}")
        print(f"[stitch] FFmpeg stderr: {result.stderr}")

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg error: {result.stderr}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Output video not created or empty")

        # Return final video
        return FileResponse(
            path=str(output_path),
            media_type='video/mp4',
            filename=f"stitched_{session_id}.mp4"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[stitch] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/audio_duration")
async def get_audio_duration(audio: UploadFile = File(..., description="MP3 or WAV audio file")):
    """Get the duration of an audio file in seconds."""
    # Validate audio file type by content type
    if not (audio.content_type and ('audio' in audio.content_type.lower() or 
                                  'wav' in audio.content_type.lower() or 
                                  'mp3' in audio.content_type.lower())):
        raise HTTPException(status_code=400, detail="File must be an audio format (MP3 or WAV)")
    
    # Generate unique ID for this processing session
    session_id = str(uuid.uuid4())
    temp_dir = Path(f"/tmp/media/{session_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Save uploaded audio file
        audio_path = temp_dir / "input_audio"
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)
        
        # Get duration of audio
        duration = get_duration(audio_path)
        
        if not duration:
            raise HTTPException(
                status_code=500,
                detail="Could not determine audio duration"
            )
        
        # Return the duration in seconds
        return JSONResponse(content={"duration": duration})
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"[audio_duration] Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

def is_url(s: str) -> bool:
    return s.lower().startswith("http://") or s.lower().startswith("https://")

def download_to_path(url: str, file_path: Path) -> None:
    """Download a file from URL to the specified path (no strict content-type enforcement)."""
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download from URL {url}: {str(e)}")

def obtain_source_to_path(src: str, dest_path: Path) -> None:
    """Copy from local path or download from URL into dest_path."""
    try:
        if is_url(src):
            download_to_path(src, dest_path)
        else:
            source_path = Path(src)
            if not source_path.exists():
                raise HTTPException(status_code=400, detail=f"Source path does not exist: {src}")
            shutil.copyfile(source_path, dest_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to obtain source '{src}': {str(e)}")


# ----- Subtitles helpers (generate segments and burn-in) -----
CONFIG_PATH = Path("subtitle_config.json")

def load_subtitle_config() -> dict:
    """Load subtitle styling config from subtitle_config.json, with sane defaults."""
    defaults = {
        "font_name": "DejaVu Sans",
        "font_size": 22,
        "bold": 1,
        "outline": 2,
        "shadow": 1,
        "primary_colour_ass": "&H0000FFFF",
        "outline_colour_ass": "&H00000000",
        "margin_v": 80,
        "margin_top": 100,
        "margin_bottom": 100,
        "margin_middle": 80,
    }
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    defaults.update(data)
    except Exception as e:
        print(f"[config] Failed to load {CONFIG_PATH}: {e}. Using defaults.")
    return defaults
def _format_timestamp_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt_from_chunks(chunks, out_path: Path) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks, start=1):
            start = _format_timestamp_srt(c["start"]) 
            end = _format_timestamp_srt(c["end"]) 
            text = (c["text"] or "").strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def _run_whisper_segments(input_path: Path, language: str = "pt", model_size: str = "small"):
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(input_path),
        language=language,
        task="transcribe",
        vad_filter=True,
        word_timestamps=True
    )
    return list(segments)


def _clean_chunk_text(tokens: List[str], is_last_in_segment: bool) -> str:
    """Normalize punctuation for a chunk.
    - Trim quotes around words.
    - Collapse spaces.
    - If not last in segment, strip trailing . , ! ? : ; from the chunk end to avoid mid-sentence stops.
    """
    # Trim surrounding quotes from tokens
    cleaned = [t.strip().strip('"\'\u201c\u201d\u2018\u2019') for t in tokens]
    text = " ".join(cleaned)
    text = " ".join(text.split())
    if not is_last_in_segment:
        while len(text) > 0 and text[-1] in ",.;:!?…":
            text = text[:-1].rstrip()
    return text


def _build_chunks_from_words(segments, max_words: int = 4, min_chunk_duration: float = 0.6):
    """Split Whisper segments into smaller caption chunks with up to max_words using word timestamps.
    Produces two-line captions (2+2) when possible and normalizes punctuation.
    Ensures each chunk is at least min_chunk_duration by borrowing the next word when possible.
    Fallback to proportional splits if word timestamps are unavailable.
    """
    chunks = []
    for seg in segments:
        words = getattr(seg, "words", None)
        # Fallback: split by whitespace proportionally across time
        if not words:
            tokens = (seg.text or "").split()
            if not tokens:
                continue
            total = len(tokens)
            start = float(seg.start or 0.0)
            seg_dur = max(0.0, float(seg.end or start) - start)
            i = 0
            while i < total:
                group = tokens[i:i+max_words]
                frac = len(group) / total
                end = start + seg_dur * frac
                # 2+2 split
                if len(group) >= 3:
                    left = group[:2]
                    right = group[2:]
                    is_last = (i + len(group)) >= total
                    left_text = _clean_chunk_text(left, False)
                    right_text = _clean_chunk_text(right, is_last)
                    text = f"{left_text}\n{right_text}".strip()
                else:
                    text = _clean_chunk_text(group, (i + len(group)) >= total)
                chunks.append({"start": start, "end": end, "text": text})
                start = end
                i += len(group)
            continue

        # Use word timestamps
        i = 0
        n = len(words)
        while i < n:
            j = min(i + max_words, n)
            group = words[i:j]
            start = float(group[0].start)
            end = float(group[-1].end)
            # Ensure minimum readable duration
            while (end - start) < min_chunk_duration and j < n:
                j += 1
                group = words[i:j]
                end = float(group[-1].end)
            # 2+2 split
            raw_tokens = [w.word.strip() for w in group]
            if len(raw_tokens) >= 3:
                left = raw_tokens[:2]
                right = raw_tokens[2:]
                is_last = (j >= n)
                left_text = _clean_chunk_text(left, False)
                right_text = _clean_chunk_text(right, is_last)
                text = f"{left_text}\n{right_text}".strip()
            else:
                text = _clean_chunk_text(raw_tokens, (j >= n))
            chunks.append({"start": start, "end": end, "text": text})
            i = j
    return chunks


def _alignment_for_position(pos: str) -> int:
    # ASS alignment: 8 top-center, 5 middle-center, 2 bottom-center
    p = (pos or "bottom").lower()
    if p == "top":
        return 8
    if p == "middle":
        return 5
    return 2


def _burn_subtitles(input_video: Path, srt_path: Path, output_path: Path, position: str, margin_v: Optional[int] = None):
    alignment = _alignment_for_position(position)
    # Load styling from config
    cfg = load_subtitle_config()
    if margin_v is not None:
        mv = margin_v
    else:
        pos = (position or "bottom").lower()
        if pos == "top":
            mv = cfg.get("margin_top", cfg.get("margin_v", 80))
        elif pos == "middle":
            mv = cfg.get("margin_middle", cfg.get("margin_v", 80))
        else:
            mv = cfg.get("margin_bottom", cfg.get("margin_v", 80))
    font_name = cfg.get("font_name", "DejaVu Sans")
    font_size = cfg.get("font_size", 22)
    bold = cfg.get("bold", 1)
    outline = cfg.get("outline", 2)
    shadow = cfg.get("shadow", 1)
    primary = cfg.get("primary_colour_ass", "&H0000FFFF")
    outline_col = cfg.get("outline_colour_ass", "&H00000000")

    # Use libass via subtitles filter; force_style controls alignment/margins
    style = (
        f"Alignment={alignment},MarginV={mv},FontName={font_name},"
        f"FontSize={font_size},Bold={bold},Outline={outline},Shadow={shadow},"
        f"PrimaryColour={primary},OutlineColour={outline_col}"
    )
    sub_filter = f"subtitles='{srt_path.resolve().as_posix()}':force_style='{style}'"
    cmd = [
        'ffmpeg', '-y',
        '-i', str(input_video),
        '-vf', sub_filter,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        str(output_path)
    ]
    print(f"[subtitles] Burn cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[subtitles] FFmpeg rc={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"FFmpeg burn-in error: {result.stderr}")


@app.post("/subtitles")
async def generate_and_burn_subtitles(req: SubtitlesRequest):
    """Generate subtitles with Faster Whisper (pt default) and return video with burned-in subtitles."""
    session_id = str(uuid.uuid4())
    temp_dir = Path(f"/tmp/media/{session_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        media_path = temp_dir / "input_media"
        obtain_source_to_path(req.source, media_path)
        if not media_path.exists() or media_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Media could not be obtained or is empty")

        # Quick probe to ensure video stream exists (we burn onto video)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(media_path)], capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            raise HTTPException(status_code=400, detail="Input must contain a video stream to burn subtitles")

        segments = _run_whisper_segments(media_path, language=req.language or "pt", model_size=req.model_size or "small")

        srt_path = temp_dir / "generated.srt"
        chunks = _build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
        _write_srt_from_chunks(chunks, srt_path)

        burned_path = temp_dir / "burned.mp4"
        _burn_subtitles(media_path, srt_path, burned_path, position=req.subtitle_position or "bottom", margin_v=None)

        if not burned_path.exists() or burned_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Burned output not created or empty")

        return FileResponse(path=str(burned_path), media_type='video/mp4', filename=f"subtitled_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[/subtitles] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.post("/subtitles/upload")
async def generate_and_burn_subtitles_upload(
    file: UploadFile = File(..., description="Audio or video file"),
    language: Optional[str] = Form("pt"),
    model_size: Optional[str] = Form("small"),
    subtitle_position: Optional[str] = Form("bottom")
):
    session_id = str(uuid.uuid4())
    temp_dir = Path(f"/tmp/media/{session_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        media_path = temp_dir / (file.filename or "upload_input")
        with open(media_path, "wb") as f:
            content = await file.read()
            f.write(content)
        if media_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(media_path)], capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            raise HTTPException(status_code=400, detail="Input must contain a video stream to burn subtitles")

        segments = _run_whisper_segments(media_path, language=language or "pt", model_size=model_size or "small")
        srt_path = temp_dir / "generated.srt"
        chunks = _build_chunks_from_words(segments, max_words=4, min_chunk_duration=0.6)
        _write_srt_from_chunks(chunks, srt_path)

        burned_path = temp_dir / "burned.mp4"
        _burn_subtitles(media_path, srt_path, burned_path, position=subtitle_position or "bottom", margin_v=None)

        if not burned_path.exists() or burned_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="Burned output not created or empty")

        return FileResponse(path=str(burned_path), media_type='video/mp4', filename=f"subtitled_{session_id}.mp4")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[/subtitles/upload] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")