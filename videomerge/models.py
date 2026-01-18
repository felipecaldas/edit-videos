from typing import List, Optional, Union
from pydantic import BaseModel


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


class UpscaleStartRequest(BaseModel):
    run_id: str
    user_id: str
    target_resolution: str
    workflow_id: str


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
