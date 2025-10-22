from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from temporalio.client import Client
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
    run_id = (req.run_id or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")

    client = await Client.connect(TEMPORAL_SERVER_URL)

    try:
        # Start the workflow
        await client.start_workflow(
            VideoGenerationWorkflow.run,
            req,
            id=run_id,
            task_queue="video-generation-task-queue",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        logger.info(f"Successfully started workflow for run_id={run_id}")
        return JSONResponse(
            content={
                "message": "Workflow started successfully.",
                "run_id": run_id,
            },
            status_code=202,
        )
    except Exception as e:
        logger.exception(f"Failed to start workflow for run_id={run_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {e}")
