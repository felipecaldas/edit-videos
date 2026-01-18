from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.common import WorkflowIDReusePolicy

from videomerge.config import TEMPORAL_SERVER_URL
from videomerge.models import UpscaleStartRequest
from videomerge.temporal.workflows import VideoUpscalingWorkflow
from videomerge.services.metrics import jobs_enqueued_total
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["upscale"])
logger = get_logger(__name__)


@router.post("/upscale/start")
async def upscale_start(req: UpscaleStartRequest):
    """Starts a new video upscaling workflow."""
    workflow_id = f"upscale-{req.user_id}-{req.run_id}"
    logger.info(
        "Received request to start video upscaling with workflow_id=%s for run_id=%s",
        workflow_id,
        req.run_id,
    )

    # Ensure the workflow_id is propagated into the workflow request payload
    req.workflow_id = workflow_id

    jobs_enqueued_total.inc()

    client = await Client.connect(TEMPORAL_SERVER_URL)
    try:
        # Start upscaling workflow
        await client.start_workflow(
            VideoUpscalingWorkflow.run,
            req,
            id=workflow_id,
            task_queue="video-upscaling-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            search_attributes={
                "UpscaleRunId": [req.run_id],  # Allows searching by run_id
            },
        )
        logger.info(
            "Successfully started upscaling workflow with workflow_id=%s for run_id=%s",
            workflow_id,
            req.run_id,
        )
        return JSONResponse(
            content={
                "message": "Upscaling workflow started successfully.",
                "workflow_id": workflow_id,
                "run_id": req.run_id,
            },
            status_code=202,
        )
    except WorkflowAlreadyStartedError:
        logger.warning(f"Upscaling workflow with workflow_id={workflow_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail=f"An upscaling job is already in progress for this run.",
        )
    except Exception as e:
        logger.error(f"Failed to start upscaling workflow with workflow_id={workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start upscaling workflow: {e}")
