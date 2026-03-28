from typing import List, Optional, Union
from pydantic import BaseModel, Field


class PromptItem(BaseModel):
    image_prompt: Optional[str] = Field(
        None,
        description="Optional image-generation prompt for a scene.",
        examples=["Cinematic wide shot of a futuristic city at sunrise"],
    )
    video_prompt: Optional[str] = Field(
        None,
        description="Optional image-to-video prompt for a scene.",
        examples=["Slow cinematic push-in, gentle camera drift, atmospheric lighting"],
    )


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
    user_id: str = Field(..., description="User identifier used for correlation and storage ownership.", examples=["user-42"])
    script: str = Field(..., description="Narration script used to generate the voiceover and scene prompts.", examples=["In 1999, a programmer accidentally changed the world."])
    caption: str = Field(..., description="Caption or descriptive text associated with the generated video.", examples=["A short story about innovation."])
    prompts: Optional[List[PromptItem]] = Field(None, description="Optional scene prompt overrides. When omitted, prompts are generated automatically.")
    language: str = Field("en", description="Language code used for voiceover and subtitles.", examples=["en"])
    image_style: str = Field(..., description="Named image style mapped to an internal image-generation workflow.", examples=["default"])
    z_image_style: Optional[str] = Field(None, description="Optional secondary or experimental image style selector.")
    image_width: Optional[int] = Field(None, description="Optional image width in pixels for image generation. If not provided, uses default from config.", examples=[360])
    image_height: Optional[int] = Field(None, description="Optional image height in pixels for image generation. If not provided, uses default from config.", examples=[640])
    video_format: str = Field(..., description="Video aspect ratio format. Supported values: '9:16' (vertical), '16:9' (horizontal), '1:1' (square)", examples=["9:16"])
    target_resolution: str = Field(..., description="Target video resolution. Supported values: '480p', '720p', '1080p'", examples=["720p"])
    run_id: str = Field(..., description="Business identifier for the run. Also used as the shared working-directory name.", examples=["run-abc123"])
    elevenlabs_voice_id: str = Field(..., description="Voice identifier passed to the voiceover generation service.", examples=["21m00Tcm4TlvDq8ikWAM"])
    workflow_id: Optional[str] = Field(None, description="Optional explicit Temporal workflow id. If omitted, the backend generates one.")
    enable_image_gen: Optional[bool] = Field(None, description="Optional override to control whether image generation should run in the workflow.")


class ImageGenerationStartRequest(BaseModel):
    user_id: str = Field(..., description="User identifier used for ownership and Supabase storage paths.", examples=["user-42"])
    script: str = Field(..., description="Script used to generate storyboard scene prompts and images.", examples=["A short narrated story about a futuristic city."])
    language: str = Field("en", description="Language code used when generating scene prompts.", examples=["en"])
    image_style: str = Field("default", description="Named image style mapped to an internal workflow.", examples=["default"])
    z_image_style: Optional[str] = Field(None, description="Optional secondary or experimental image style selector.")
    image_width: Optional[int] = Field(
        None,
        description="Optional image width in pixels for image generation. If not provided, uses default from config.",
        examples=[360],
    )
    image_height: Optional[int] = Field(
        None,
        description="Optional image height in pixels for image generation. If not provided, uses default from config.",
        examples=[640],
    )
    run_id: Optional[str] = Field(None, description="Optional run identifier. If omitted, the backend derives one deterministically from script and language.", examples=["abc123"])
    workflow_id: Optional[str] = Field(None, description="Optional explicit Temporal workflow id. If omitted, the backend generates one.")
    user_access_token: str = Field(
        ...,
        description="Supabase user JWT access token for authenticated storage uploads (respects RLS policies)",
        examples=["eyJhbGciOi..."],
    )


class StoryboardVideoGenerationRequest(BaseModel):
    user_id: str = Field(..., description="User identifier used for ownership and Supabase storage paths.", examples=["user-42"])
    script: str = Field(..., description="Script used to generate the voiceover for the final video.", examples=["In 1999, a programmer accidentally changed the world."])
    language: str = Field("en", description="Language code used for voiceover generation and subtitles.", examples=["en"])
    run_id: str = Field(..., description="Existing run identifier whose shared directory already contains scene_prompts.json and image_XXX.png files.", examples=["kef99ac7y9e"])
    workflow_id: Optional[str] = Field(None, description="Optional explicit Temporal workflow id. If omitted, the backend generates one.")
    user_access_token: str = Field(
        ...,
        description="Supabase user JWT access token for authenticated storage uploads (respects RLS policies)",
        examples=["eyJhbGciOi..."],
    )
    elevenlabs_voice_id: str = Field(..., description="Voice identifier passed to the voiceover generation service.", examples=["21m00Tcm4TlvDq8ikWAM"])
    video_format: str = Field(
        "9:16",
        description="Video aspect ratio format. Supported values: '9:16' (vertical), '16:9' (horizontal), '1:1' (square)",
        examples=["9:16"],
    )
    target_resolution: str = Field(
        "720p",
        description="Target video resolution. Supported values: '480p', '720p', '1080p'",
        examples=["720p"],
    )


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
