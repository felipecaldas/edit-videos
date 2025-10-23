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
    workflow_id = f"tabario-user-{req.user_id}"
    logger.info(f"Received request to start video generation with workflow_id={workflow_id}")


    client = await Client.connect(TEMPORAL_SERVER_URL)
    try:
        await client.start_workflow(
            VideoGenerationWorkflow.run,
            req,
            id=workflow_id,
            task_queue="video-generation-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
        logger.info(f"Successfully started workflow with workflow_id={workflow_id}")
        return JSONResponse(
            content={
                "message": "Workflow started successfully.",
                "workflow_id": workflow_id,
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
