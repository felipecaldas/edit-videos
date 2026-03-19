from typing import List, Optional, Union
from pydantic import BaseModel, Field


class PromptItem(BaseModel):
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None


class StitchRequest(BaseModel):
    voiceover: str  # URL or absolute/accessible file path to voiceover.mp3/wav
    videos: List[str]  # Ordered list of URLs or file paths to videos


class FolderStitchRequest(BaseModel):
    folder_path: str  # Directory containing one mp3/wav voiceover and mp4 videos


class SubtitlesRequest(BaseModel):
    source: str  # URL or container-visible file path to audio/video
    language: Optional[str] = "pt"  # default Brazilian Portuguese
    model_size: Optional[str] = "small"  # tiny, base, small, medium, large-v2
    subtitle_position: Optional[str] = "bottom"  # top | middle | bottom


class StitchWithSubsRequest(StitchRequest):
    language: Optional[str] = "pt"
    model_size: Optional[str] = "small"
    subtitle_position: Optional[str] = "bottom"


class FolderStitchWithSubsRequest(FolderStitchRequest):
    language: Optional[str] = "pt"
    model_size: Optional[str] = "small"
    subtitle_position: Optional[str] = "bottom"


class OrchestrateStartRequest(BaseModel):
    user_id: str
    script: str
    caption: str
    prompts: Optional[List[PromptItem]] = None
    language: str = "en"
    image_style: str
    z_image_style: Optional[str] = None
    image_width: Optional[int] = Field(None, description="Optional image width in pixels for image generation. If not provided, uses default from config.")
    image_height: Optional[int] = Field(None, description="Optional image height in pixels for image generation. If not provided, uses default from config.")
    video_format: str = Field(..., description="Video aspect ratio format. Supported values: '9:16' (vertical), '16:9' (horizontal), '1:1' (square)")
    target_resolution: str = Field(..., description="Target video resolution. Supported values: '480p', '720p', '1080p'")
    run_id: str
    elevenlabs_voice_id: str
    workflow_id: Optional[str] = None
    enable_image_gen: Optional[bool] = None


class ImageGenerationStartRequest(BaseModel):
    user_id: str
    script: str
    language: str = "en"
    image_style: str = "default"
    z_image_style: Optional[str] = None
    image_width: Optional[int] = Field(
        None,
        description="Optional image width in pixels for image generation. If not provided, uses default from config.",
    )
    image_height: Optional[int] = Field(
        None,
        description="Optional image height in pixels for image generation. If not provided, uses default from config.",
    )
    run_id: Optional[str] = None
    workflow_id: Optional[str] = None


class UpscaleStartRequest(BaseModel):
    run_id: str
    user_id: str
    target_resolution: str
    workflow_id: str
    voice_language: Optional[str] = "en"


class UpscaleChildRequest(BaseModel):
    video_path: str
    video_id: str
    run_id: str
    user_id: str
    target_resolution: str
    workflow_id: str


class UpscaleStitchRequest(BaseModel):
    run_id: str
    user_id: str
    workflow_id: str
    voice_language: Optional[str] = "en"


class TranscriptionRequest(BaseModel):
    mp3_path: str = Field(..., description="Path to MP3 file in /data/shared")
    language: Optional[str] = Field(None, description="Optional language code (e.g., 'en', 'pt'). If not provided, Whisper will auto-detect")
    model_size: Optional[str] = Field("small", description="Whisper model size: tiny, base, small, medium, large-v2")


class TranscriptionResponse(BaseModel):
    text: str = Field(..., description="Transcribed text")
    detected_language: Optional[str] = Field(None, description="Detected language code (if auto-detected)")
    confidence: Optional[float] = Field(None, description="Language detection confidence (if available)")
