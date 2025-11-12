from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.common import WorkflowIDReusePolicy

from videomerge.config import TEMPORAL_SERVER_URL
from videomerge.models import OrchestrateStartRequest
from videomerge.temporal.workflows import VideoGenerationWorkflow
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["orchestrate"])
logger = get_logger(__name__)


@router.post("/orchestrate/start")
async def orchestrate_start(req: OrchestrateStartRequest):
    """Starts a new video generation workflow."""
    workflow_id = f"tabario-user-{req.user_id}-{req.run_id}"
    logger.info(
        "Received request to start video generation with workflow_id=%s for run_id=%s",
        workflow_id,
        req.run_id,
    )


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
