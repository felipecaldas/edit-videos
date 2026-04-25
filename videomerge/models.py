from typing import List, Optional, Union
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# V-CaaS brief-aware models (TAB-5 / TAB-6)
#
# These mirror the `brief` / `platform_brief` structure produced by N8N for the
# brief-aware orchestration flow. They are intentionally permissive (most
# fields are Optional) so the same payload shape can be reused across
# platforms that populate different subsets of the brief.
# ---------------------------------------------------------------------------


class SceneBrief(BaseModel):
    """A single scene inside a platform brief.

    One ``SceneBrief`` corresponds to one generated image-to-video clip. The
    ``spoken_line`` values are concatenated across scenes to build the TTS
    script, and ``duration_seconds`` drives per-scene clip length.
    """

    scene_number: int = Field(
        ...,
        description="Ordinal position of the scene within the platform brief (1-indexed).",
        examples=[1],
    )
    spoken_line: str = Field(
        ...,
        description="Narration line spoken during this scene; concatenated across scenes to form the voiceover script.",
        examples=["Every founder has that moment."],
    )
    caption_text: str = Field(
        ...,
        description="Text overlay/caption displayed during the scene.",
        examples=["The moment everything changes."],
    )
    duration_seconds: float = Field(
        ...,
        description="Target duration for this scene in seconds; used to size the generated image-to-video clip.",
        examples=[2.0],
    )
    visual_description: str = Field(
        ...,
        description="Base visual description for the scene; seed for image + video prompt enrichment.",
        examples=["A founder at a desk at night, lit by the glow of a laptop."],
    )


class VisualDirection(BaseModel):
    """Shared visual-direction cues applied across all platform briefs."""

    mood: Optional[str] = Field(
        None,
        description="Overall mood or emotion (e.g. 'optimistic', 'urgent').",
        examples=["optimistic"],
    )
    color_feel: Optional[str] = Field(
        None,
        description="Color palette or lighting feel (e.g. 'warm pastels', 'high-contrast noir').",
        examples=["warm pastels"],
    )
    shot_style: Optional[str] = Field(
        None,
        description="Camera or shot style (e.g. 'handheld documentary', 'clean studio').",
        examples=["clean studio"],
    )
    branding_elements: Optional[str] = Field(
        None,
        description="Branding cues to weave into frames (logos, typography, product motifs).",
        examples=["Tabario wordmark lower-third"],
    )


class PlatformBriefModel(BaseModel):
    """A per-platform execution brief (LinkedIn / Instagram / YouTubeShorts / TikTok / X)."""

    platform: str = Field(
        ...,
        description="Platform identifier used to select this brief (e.g. 'LinkedIn', 'Instagram').",
        examples=["LinkedIn"],
    )
    hook: Optional[str] = Field(
        None,
        description="Platform-specific opening hook.",
    )
    tone: Optional[str] = Field(
        None,
        description="Platform-specific narrative tone.",
        examples=["confident, conversational"],
    )
    aspect_ratio: Optional[str] = Field(
        None,
        description="Aspect ratio for this platform ('1:1', '9:16', '16:9').",
        examples=["1:1"],
    )
    scenes: List[SceneBrief] = Field(
        default_factory=list,
        description="Ordered list of scenes making up the platform-specific video.",
    )
    call_to_action: Optional[str] = Field(
        None,
        description="Platform-specific CTA string.",
    )
    platform_notes: Optional[str] = Field(
        None,
        description="Free-form platform-specific guidance or constraints.",
    )


class Brief(BaseModel):
    """Top-level brief object carrying cross-platform narrative + per-platform execution briefs."""

    hook: Optional[str] = Field(
        None,
        description="Cross-platform narrative hook.",
    )
    title: Optional[str] = Field(
        None,
        description="Working title for the video idea.",
    )
    narrative_structure: Optional[str] = Field(
        None,
        description="Narrative skeleton (e.g. 'problem-solution-CTA').",
    )
    music_sound_mood: Optional[str] = Field(
        None,
        description="Music and sound-design guidance.",
    )
    visual_direction: Optional[VisualDirection] = Field(
        None,
        description="Shared visual-direction cues applied across platforms.",
    )
    platform_briefs: List[PlatformBriefModel] = Field(
        default_factory=list,
        description="Per-platform briefs; one is selected by the request's 'platform' field.",
    )


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
    """Payload accepted by ``POST /orchestrate/start``.

    Supports both the legacy flow (script + prompts generated via N8N) and the
    brief-aware V-CaaS flow (``brief`` + ``platform``). Fields required only
    by the legacy flow are made ``Optional`` so N8N payloads can omit them
    and have the router fall back to env defaults.
    """

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(..., description="User identifier used for correlation and storage ownership.", examples=["user-42"])
    script: str = Field(..., description="Narration script used to generate the voiceover and scene prompts.", examples=["In 1999, a programmer accidentally changed the world."])
    caption: str = Field(..., description="Caption or descriptive text associated with the generated video.", examples=["A short story about innovation."])
    prompts: Optional[List[PromptItem]] = Field(None, description="Optional scene prompt overrides. When omitted, prompts are generated automatically.")
    language: Optional[str] = Field("en", description="Language code used for voiceover and subtitles. Falls back to env default when omitted.", examples=["en"])
    image_style: Optional[str] = Field(
        None,
        description="Named image style mapped to an internal image-generation workflow. Accepts the alias 'style' for N8N compatibility. Router falls back to 'default' when omitted.",
        validation_alias=AliasChoices("image_style", "style"),
        examples=["default"],
    )
    z_image_style: Optional[str] = Field(None, description="Optional secondary or experimental image style selector.")
    image_width: Optional[int] = Field(None, description="Optional image width in pixels for image generation. If not provided, uses default from config.", examples=[360])
    image_height: Optional[int] = Field(None, description="Optional image height in pixels for image generation. If not provided, uses default from config.", examples=[640])
    video_format: Optional[str] = Field(None, description="Video aspect ratio format. Supported values: '9:16' (vertical), '16:9' (horizontal), '1:1' (square). Router derives this from brief.aspect_ratio or env default when omitted.", examples=["9:16"])
    target_resolution: Optional[str] = Field(None, description="Target video resolution. Supported values: '480p', '720p', '1080p'. Router falls back to env default when omitted.", examples=["720p"])
    run_id: Optional[str] = Field(None, description="Business identifier for the run. Also used as the shared working-directory name. Router derives one from video_idea_id + platform when omitted in brief-aware flow.", examples=["run-abc123"])
    elevenlabs_voice_id: Optional[str] = Field(None, description="Voice identifier passed to the voiceover generation service. Router falls back to env default when omitted.", examples=["21m00Tcm4TlvDq8ikWAM"])
    workflow_id: Optional[str] = Field(None, description="Optional explicit Temporal workflow id. If omitted, the backend generates one.")
    enable_image_gen: Optional[bool] = Field(None, description="Optional override to control whether image generation should run in the workflow.")
    brief: Optional[Brief] = Field(None, description="V-CaaS brief object. When present together with 'platform', the router/workflow switches to the brief-aware flow and skips the N8N prompts webhook.")
    platform: Optional[str] = Field(None, description="Platform identifier selecting one PlatformBriefModel from brief.platform_briefs (e.g. 'LinkedIn').", examples=["LinkedIn"])
    video_idea_id: Optional[str] = Field(None, description="Supabase video_ideas.id, echoed in completion webhooks for correlation with the source idea.", examples=["fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"])
    client_id: Optional[str] = Field(
        None,
        description="Supabase clients.id. Required when handoff_to_compositor is True (or auto-computed True).",
        examples=["client-42"],
    )
    handoff_to_compositor: Optional[bool] = Field(
        None,
        description=(
            "Controls whether the workflow hands off the finished clips to tabario-video-compositor. "
            "When None (default), auto-computes to True if brief + platform + client_id are all present, "
            "otherwise False. Explicitly set to False to disable handoff even in brief-aware runs."
        ),
    )
    user_access_token: Optional[str] = Field(
        None,
        description=(
            "Supabase user JWT access token. Required when handoff_to_compositor is enabled (or auto-resolves True). "
            "Forwarded to the compositor so Supabase uploads honour the user's RLS context."
        ),
        examples=["eyJhbGciOi..."],
    )


class ImageGenerationStartRequest(BaseModel):
    """Payload accepted by ``POST /orchestrate/generate-images``.

    Brief-aware when ``brief`` + ``platform`` are supplied; otherwise runs the
    legacy scene-prompt generation via the N8N webhook.
    """

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(..., description="User identifier used for ownership and Supabase storage paths.", examples=["user-42"])
    script: str = Field(..., description="Script used to generate storyboard scene prompts and images.", examples=["A short narrated story about a futuristic city."])
    language: Optional[str] = Field("en", description="Language code used when generating scene prompts.", examples=["en"])
    image_style: Optional[str] = Field(
        "default",
        description="Named image style mapped to an internal workflow. Accepts the alias 'style' for N8N compatibility.",
        validation_alias=AliasChoices("image_style", "style"),
        examples=["default"],
    )
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
    run_id: Optional[str] = Field(None, description="Optional run identifier. If omitted, the backend derives one deterministically from script and language (legacy flow) or from video_idea_id + platform (brief-aware flow).", examples=["abc123"])
    workflow_id: Optional[str] = Field(None, description="Optional explicit Temporal workflow id. If omitted, the backend generates one.")
    user_access_token: str = Field(
        ...,
        description="Supabase user JWT access token for authenticated storage uploads (respects RLS policies)",
        examples=["eyJhbGciOi..."],
    )
    brief: Optional[Brief] = Field(None, description="V-CaaS brief object. When present together with 'platform', image prompts are built from brief.scenes[] instead of calling the N8N prompts webhook.")
    platform: Optional[str] = Field(None, description="Platform identifier selecting one PlatformBriefModel from brief.platform_briefs (e.g. 'LinkedIn').", examples=["LinkedIn"])
    video_idea_id: Optional[str] = Field(None, description="Supabase video_ideas.id, echoed in completion webhooks for correlation with the source idea.", examples=["fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"])
    video_format: Optional[str] = Field(
        None,
        description="Video aspect ratio format ('9:16', '16:9', '1:1'). Used to derive correct image dimensions. Defaults to '9:16' when omitted.",
        examples=["9:16"],
    )
    target_resolution: Optional[str] = Field(
        None,
        description="Target image resolution ('480p', '720p', '1080p'). Image generation is capped at 720p regardless. Defaults to '720p' when omitted.",
        examples=["720p"],
    )


class StoryboardVideoGenerationRequest(BaseModel):
    """Payload accepted by ``POST /orchestrate/generate-videos``.

    Brief-aware when ``brief`` + ``platform`` are supplied; otherwise loads
    existing ``scene_prompts.json`` from the run directory and uses
    ``req.script`` for voiceover generation.
    """

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(..., description="User identifier used for ownership and Supabase storage paths.", examples=["user-42"])
    script: str = Field(..., description="Script used to generate the voiceover for the final video.", examples=["In 1999, a programmer accidentally changed the world."])
    language: Optional[str] = Field("en", description="Language code used for voiceover generation and subtitles.", examples=["en"])
    run_id: Optional[str] = Field(None, description="Existing run identifier whose shared directory already contains scene_prompts.json and image_XXX.png files. Router derives one from video_idea_id + platform when omitted in brief-aware flow.", examples=["kef99ac7y9e"])
    workflow_id: Optional[str] = Field(None, description="Optional explicit Temporal workflow id. If omitted, the backend generates one.")
    user_access_token: str = Field(
        ...,
        description="Supabase user JWT access token for authenticated storage uploads (respects RLS policies)",
        examples=["eyJhbGciOi..."],
    )
    elevenlabs_voice_id: Optional[str] = Field(None, description="Voice identifier passed to the voiceover generation service. Router falls back to env default when omitted.", examples=["21m00Tcm4TlvDq8ikWAM"])
    video_format: Optional[str] = Field(
        None,
        description="Video aspect ratio format. Supported values: '9:16' (vertical), '16:9' (horizontal), '1:1' (square). Router derives from brief.aspect_ratio or defaults to '9:16' when omitted.",
        examples=["9:16"],
    )
    target_resolution: Optional[str] = Field(
        None,
        description="Target video resolution. Supported values: '480p', '720p', '1080p'. Router defaults to '720p' when omitted.",
        examples=["720p"],
    )
    brief: Optional[Brief] = Field(None, description="V-CaaS brief object. When present together with 'platform', voiceover script is built from concatenated spoken_line values and per-scene clip length is derived from scenes[].duration_seconds.")
    platform: Optional[str] = Field(None, description="Platform identifier selecting one PlatformBriefModel from brief.platform_briefs (e.g. 'LinkedIn').", examples=["LinkedIn"])
    video_idea_id: Optional[str] = Field(None, description="Supabase video_ideas.id, echoed in completion webhooks for correlation with the source idea.", examples=["fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"])
    client_id: Optional[str] = Field(
        None,
        description="Supabase clients.id. Required when handoff_to_compositor is True (or auto-computed True).",
        examples=["client-42"],
    )
    handoff_to_compositor: Optional[bool] = Field(
        None,
        description=(
            "Controls whether the workflow hands off the finished clips to tabario-video-compositor. "
            "When None (default), auto-computes to True if brief + platform + client_id are all present, "
            "otherwise False. Explicitly set to False to disable handoff even in brief-aware runs."
        ),
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


class HandoffPayload(BaseModel):
    """Payload forwarded to ``tabario-video-compositor`` via the ``handoff_to_compositor`` activity.

    Carries everything the compositor needs to assemble and upload a final
    brand-aware video from already-generated clips.
    """

    run_id: str = Field(
        ...,
        description="Business run identifier; maps to the shared working directory ``/data/shared/{run_id}/``.",
        examples=["run-abc123"],
    )
    client_id: str = Field(
        ...,
        description="Client / tenant identifier used for brand-profile resolution and storage namespacing.",
        examples=["client-42"],
    )
    brand_profile_id: Optional[str] = Field(
        None,
        description="Optional brand profile UUID. When omitted, the compositor resolves it from ``client_id``.",
        examples=["bp-9f3e1a"],
    )
    brief: Brief = Field(
        ...,
        description="The full V-CaaS brief used to produce the source clips; forwarded for downstream enrichment.",
    )
    platform: str = Field(
        ...,
        description="Platform identifier that selected the active ``PlatformBriefModel`` (e.g. 'LinkedIn').",
        examples=["LinkedIn"],
    )
    voiceover_path: str = Field(
        ...,
        description="Container-absolute path to the voiceover audio file under ``/data/shared/{run_id}/``.",
        examples=["/data/shared/run-abc123/voiceover.mp3"],
    )
    clip_paths: List[str] = Field(
        ...,
        description="Ordered list of container-absolute paths to per-scene video clips.",
        examples=[["/data/shared/run-abc123/000_clip.mp4", "/data/shared/run-abc123/001_clip.mp4"]],
    )
    video_format: str = Field(
        ...,
        description="Video aspect-ratio format ('9:16', '16:9', or '1:1').",
        examples=["9:16"],
    )
    target_resolution: Optional[str] = Field(
        None,
        description="Target output resolution ('480p', '720p', '1080p'). Compositor applies its own default when omitted.",
        examples=["720p"],
    )
    video_idea_id: Optional[str] = Field(
        None,
        description="Supabase ``video_ideas.id`` echoed for correlation with the originating idea.",
        examples=["fe1004f1-9a5d-4b9f-8e0a-5c7f9b3e6c11"],
    )
    workflow_id: str = Field(
        ...,
        description="Temporal workflow ID of the originating generation workflow, for traceability.",
        examples=["wf-xyz789"],
    )
    user_access_token: str = Field(
        ...,
        description="Supabase user JWT forwarded so the compositor can upload assets under the user's RLS context.",
        examples=["eyJhbGciOi..."],
    )
