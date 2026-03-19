from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.common import WorkflowIDReusePolicy

from videomerge.config import IMAGE_STYLE_TO_WORKFLOW_MAPPING, TEMPORAL_SERVER_URL
from videomerge.models import ImageGenerationStartRequest, OrchestrateStartRequest
from videomerge.temporal.workflows import ImageGenerationWorkflow, VideoGenerationWorkflow
from videomerge.services.metrics import jobs_enqueued_total
from videomerge.utils.logging import get_logger
import hashlib

router = APIRouter(prefix="", tags=["orchestrate"])
logger = get_logger(__name__)


def _build_image_generation_run_id(script: str, language: str) -> str:
    """Build a deterministic 6-character hexadecimal run identifier."""
    digest = hashlib.sha256(f"{language}:{script}".encode("utf-8")).hexdigest()
    return digest[:6]


@router.post("/orchestrate/start")
async def orchestrate_start(req: OrchestrateStartRequest):
    """Starts a new video generation workflow."""
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


@router.post("/orchestrate/generate-images")
async def orchestrate_generate_images(req: ImageGenerationStartRequest):
    """Starts a new image-generation workflow."""
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
