from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.common import WorkflowIDReusePolicy

from videomerge.config import IMAGE_STYLE_TO_WORKFLOW_MAPPING, SUPABASE_ANON_KEY, SUPABASE_URL, TEMPORAL_SERVER_URL
from videomerge.models import ImageGenerationStartRequest, OrchestrateStartRequest, StoryboardVideoGenerationRequest
from videomerge.temporal.workflows import ImageGenerationWorkflow, StoryBoardVideoGeneration, VideoGenerationWorkflow
from videomerge.services.metrics import jobs_enqueued_total
from videomerge.utils.logging import get_logger
import hashlib

router = APIRouter(prefix="", tags=["orchestrate"])
logger = get_logger(__name__)


def aspect_ratio_to_video_format(aspect_ratio: str) -> str:
    """Convert aspect ratio string to video format.

    Args:
        aspect_ratio: Aspect ratio string (e.g., '1:1', '9:16', '16:9')

    Returns:
        Video format string (e.g., '1:1', '9:16', '16:9')
    """
    valid_ratios = {"1:1", "9:16", "16:9"}
    if aspect_ratio in valid_ratios:
        return aspect_ratio
    logger.warning("Unknown aspect_ratio '%s', defaulting to '9:16'", aspect_ratio)
    return "9:16"


def _resolve_handoff_flag(req) -> bool:
    """Resolve the effective handoff_to_compositor flag for a request.

    When ``handoff_to_compositor`` is explicitly ``True`` or ``False``, that
    value is returned as-is.  When it is ``None`` (default), the flag is
    auto-computed as ``True`` only when ``brief``, ``platform``, and
    ``client_id`` are all present.
    """
    if req.handoff_to_compositor is not None:
        return req.handoff_to_compositor
    return bool(req.brief and req.platform and req.client_id)


def _derive_run_id(video_idea_id: Optional[str], platform: Optional[str]) -> str:
    """Derive run_id from video_idea_id and platform."""
    if not video_idea_id:
        raise ValueError("video_idea_id is required when run_id is not supplied")
    if not platform:
        raise ValueError("platform is required when run_id is not supplied")
    return f"{video_idea_id}-{platform.lower()}"


def _build_image_generation_run_id(script: str, language: str) -> str:
    """Build a deterministic 6-character hexadecimal run identifier."""
    digest = hashlib.sha256(f"{language}:{script}".encode("utf-8")).hexdigest()
    return digest[:6]


@router.post(
    "/orchestrate/start",
    summary="Start the full video-generation workflow. One-Shot video generation without storyboard.",
    description=(
        "Starts the main Temporal workflow for end-to-end video generation. "
        "This flow can generate voiceover, scene prompts, images, video clips, subtitles, and the final stitched video."
    ),
    responses={
        202: {"description": "Workflow accepted and started successfully."},
        400: {"description": "Invalid request payload, such as an unknown image_style."},
        409: {"description": "A workflow with the same workflow_id is already running."},
        500: {"description": "Failed to enqueue the Temporal workflow."},
    },
)
async def orchestrate_start(req: OrchestrateStartRequest):
    """Starts a new video generation workflow."""
    # Brief-aware branching: derive run_id, video_format, image_style from brief/platform
    if req.brief and req.platform:
        platform_brief = next(
            (pb for pb in req.brief.platform_briefs if pb.platform.lower() == req.platform.lower()),
            None,
        )
        if not platform_brief:
            available_platforms = [pb.platform for pb in req.brief.platform_briefs]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Platform '{req.platform}' not found in brief.platform_briefs. "
                    f"Available platforms: {available_platforms}"
                ),
            )
        # Derive run_id: use provided or derive from video_idea_id + platform
        if not req.run_id:
            if not req.video_idea_id:
                raise HTTPException(
                    status_code=400,
                    detail="video_idea_id is required when run_id is not supplied in brief-aware flow.",
                )
            req.run_id = _derive_run_id(req.video_idea_id, req.platform)
        # Derive video_format: use provided or derive from platform_brief.aspect_ratio
        if not req.video_format and platform_brief.aspect_ratio:
            req.video_format = aspect_ratio_to_video_format(platform_brief.aspect_ratio)
        # Derive image_style: use provided or fall back to 'default'
        if not req.image_style:
            req.image_style = "default"

    workflow_id = f"tabario-user-{req.user_id}-{req.run_id}"
    logger.info(
        "Received request to start video generation with workflow_id=%s for run_id=%s",
        workflow_id,
        req.run_id,
    )

    # Validate image_style maps to a known ComfyUI workflow before enqueuing
    image_style = req.image_style or "default"
    comfyui_workflow_name = IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)
    if not comfyui_workflow_name:
        supported = sorted(IMAGE_STYLE_TO_WORKFLOW_MAPPING.keys())
        logger.warning(
            "Rejected orchestrate request run_id=%s: unknown image_style '%s'",
            req.run_id,
            image_style,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown image_style '{image_style}'. "
                f"Supported styles: {supported}"
            ),
        )

    # Validate handoff: client_id required when handoff is enabled
    if _resolve_handoff_flag(req) and not req.client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id is required when handoff_to_compositor is enabled.",
        )

    # Ensure the workflow_id is propagated into the workflow request payload
    req.workflow_id = workflow_id

    jobs_enqueued_total.inc()

    client = await Client.connect(TEMPORAL_SERVER_URL)
    try:
        # Start parent workflow with TabarioRunId search attribute
        # Child workflows will also have the same TabarioRunId for easy correlation
        await client.start_workflow(
            VideoGenerationWorkflow.run,
            req,
            id=workflow_id,
            task_queue="video-generation-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            search_attributes={
                "TabarioRunId": [req.run_id],  # Allows searching parent + all children by run_id
            },
        )
        logger.info(
            "Successfully started workflow with workflow_id=%s for run_id=%s",
            workflow_id,
            req.run_id,
        )
        return JSONResponse(
            content={
                "message": "Workflow started successfully.",
                "workflow_id": workflow_id,
                "run_id": req.run_id,
            },
            status_code=202,
        )
    except WorkflowAlreadyStartedError:
        logger.warning(f"Workflow with workflow_id={workflow_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail=f"A video generation job is already in progress for this user.",
        )
    except Exception as e:
        logger.error(f"Failed to start workflow with workflow_id={workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {e}")


@router.post(
    "/orchestrate/generate-images",
    summary="Generate storyboard images only",
    description=(
        "Starts the image-generation workflow that creates ordered storyboard images and uploads them to Supabase. "
        "If run_id is omitted, the backend derives one deterministically from the script and language."
    ),
    responses={
        202: {"description": "Image-generation workflow accepted and started successfully."},
        400: {"description": "Invalid request payload, missing user_access_token, or unknown image_style."},
        409: {"description": "A workflow with the same workflow_id is already running."},
        500: {"description": "Supabase is misconfigured or the Temporal workflow could not be started."},
    },
)
async def orchestrate_generate_images(req: ImageGenerationStartRequest):
    """Starts a new image-generation workflow."""
    # Brief-aware branching: derive run_id from brief/platform
    if req.brief and req.platform:
        platform_brief = next(
            (pb for pb in req.brief.platform_briefs if pb.platform.lower() == req.platform.lower()),
            None,
        )
        if not platform_brief:
            available_platforms = [pb.platform for pb in req.brief.platform_briefs]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Platform '{req.platform}' not found in brief.platform_briefs. "
                    f"Available platforms: {available_platforms}"
                ),
            )
        # Derive run_id: use provided or derive from video_idea_id + platform
        if not req.run_id:
            if not req.video_idea_id:
                raise HTTPException(
                    status_code=400,
                    detail="video_idea_id is required when run_id is not supplied in brief-aware flow.",
                )
            req.run_id = _derive_run_id(req.video_idea_id, req.platform)
    else:
        req.run_id = req.run_id or _build_image_generation_run_id(req.script, req.language)
    workflow_id = req.workflow_id or f"tabario-image-user-{req.user_id}-{req.run_id}"
    logger.info(
        "Received request to start image generation with workflow_id=%s for run_id=%s",
        workflow_id,
        req.run_id,
    )

    image_style = req.image_style or "default"
    comfyui_workflow_name = IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)
    if not comfyui_workflow_name:
        supported = sorted(IMAGE_STYLE_TO_WORKFLOW_MAPPING.keys())
        logger.warning(
            "Rejected image-generation request run_id=%s: unknown image_style '%s'",
            req.run_id,
            image_style,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown image_style '{image_style}'. "
                f"Supported styles: {supported}"
            ),
        )

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error(
            "Rejected image-generation request run_id=%s: Supabase configuration is missing",
            req.run_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Image generation storage is not configured. SUPABASE_URL and SUPABASE_ANON_KEY must be set.",
        )
    
    if not req.user_access_token:
        logger.error(
            "Rejected image-generation request run_id=%s: user_access_token is missing",
            req.run_id,
        )
        raise HTTPException(
            status_code=400,
            detail="user_access_token is required for authenticated storage uploads.",
        )

    req.workflow_id = workflow_id
    jobs_enqueued_total.inc()

    client = await Client.connect(TEMPORAL_SERVER_URL)
    try:
        await client.start_workflow(
            ImageGenerationWorkflow.run,
            req,
            id=workflow_id,
            task_queue="video-generation-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            search_attributes={
                "TabarioRunId": [req.run_id],
            },
        )
        return JSONResponse(
            content={
                "message": "Image generation workflow started successfully.",
                "workflow_id": workflow_id,
                "run_id": req.run_id,
                "status": "received",
            },
            status_code=202,
        )
    except WorkflowAlreadyStartedError:
        logger.warning(f"Image workflow with workflow_id={workflow_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail="An image generation job is already in progress for this user.",
        )
    except Exception as e:
        logger.error(f"Failed to start image workflow with workflow_id={workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start image workflow: {e}")


@router.post(
    "/orchestrate/generate-videos",
    summary="Generate a final video from existing storyboard assets",
    description=(
        "Starts the storyboard video-generation workflow using an existing scene_prompts.json file and ordered image_XXX.png files "
        "already present in /data/shared/{run_id}. This flow generates clips in parallel, stitches them, burns subtitles, and uploads only the final video to Supabase."
    ),
    responses={
        202: {"description": "Storyboard video-generation workflow accepted and started successfully."},
        400: {"description": "Invalid request payload or missing user_access_token."},
        409: {"description": "A workflow with the same workflow_id is already running."},
        500: {"description": "Supabase is misconfigured or the Temporal workflow could not be started."},
    },
)
async def orchestrate_generate_videos(req: StoryboardVideoGenerationRequest):
    """Starts a storyboard video-generation workflow from pre-generated images and prompts."""
    # Brief-aware branching: derive run_id, video_format from brief/platform
    if req.brief and req.platform:
        platform_brief = next(
            (pb for pb in req.brief.platform_briefs if pb.platform.lower() == req.platform.lower()),
            None,
        )
        if not platform_brief:
            available_platforms = [pb.platform for pb in req.brief.platform_briefs]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Platform '{req.platform}' not found in brief.platform_briefs. "
                    f"Available platforms: {available_platforms}"
                ),
            )
        # Derive run_id: use provided or derive from video_idea_id + platform
        if not req.run_id:
            if not req.video_idea_id:
                raise HTTPException(
                    status_code=400,
                    detail="video_idea_id is required when run_id is not supplied in brief-aware flow.",
                )
            req.run_id = _derive_run_id(req.video_idea_id, req.platform)
        # Derive video_format: use provided or derive from platform_brief.aspect_ratio
        if not req.video_format and platform_brief.aspect_ratio:
            req.video_format = aspect_ratio_to_video_format(platform_brief.aspect_ratio)

    workflow_id = req.workflow_id or f"tabario-storyboard-video-user-{req.user_id}-{req.run_id}"
    logger.info(
        "Received request to start storyboard video generation with workflow_id=%s for run_id=%s",
        workflow_id,
        req.run_id,
    )

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error(
            "Rejected storyboard video-generation request run_id=%s: Supabase configuration is missing",
            req.run_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Final video storage is not configured. SUPABASE_URL and SUPABASE_ANON_KEY must be set.",
        )

    if not req.user_access_token:
        logger.error(
            "Rejected storyboard video-generation request run_id=%s: user_access_token is missing",
            req.run_id,
        )
        raise HTTPException(
            status_code=400,
            detail="user_access_token is required for authenticated storage uploads.",
        )

    # Validate handoff: client_id required when handoff is enabled
    if _resolve_handoff_flag(req) and not req.client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id is required when handoff_to_compositor is enabled.",
        )

    req.workflow_id = workflow_id
    jobs_enqueued_total.inc()

    client = await Client.connect(TEMPORAL_SERVER_URL)
    try:
        await client.start_workflow(
            StoryBoardVideoGeneration.run,
            req,
            id=workflow_id,
            task_queue="video-generation-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            search_attributes={
                "TabarioRunId": [req.run_id],
            },
        )
        return JSONResponse(
            content={
                "message": "Storyboard video generation workflow started successfully.",
                "workflow_id": workflow_id,
                "run_id": req.run_id,
                "status": "received",
            },
            status_code=202,
        )
    except WorkflowAlreadyStartedError:
        logger.warning(f"Storyboard video workflow with workflow_id={workflow_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail="A storyboard video generation job is already in progress for this user.",
        )
    except Exception as e:
        logger.error(f"Failed to start storyboard video workflow with workflow_id={workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start storyboard video workflow: {e}")
