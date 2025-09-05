from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from videomerge.models import OrchestrateStartRequest
from videomerge.services.redis_client import get_redis
from videomerge.services.queue import enqueue_job, get_job
from videomerge.utils.logging import get_logger

router = APIRouter(prefix="", tags=["orchestrate"])
logger = get_logger(__name__)


@router.post("/orchestrate/start")
async def orchestrate_start(req: OrchestrateStartRequest):
    """Enqueue a new orchestration job (steps 1–3 performed by the worker).

    Returns a job_id that can be polled for status.
    """
    run_id = (req.run_id or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")

    payload = {
        "script": req.script,
        "caption": req.caption,
        "run_id": run_id,
        "prompts": [p.model_dump() for p in req.prompts],
        "enable_image_gen": req.enable_image_gen,
    }
    redis = await get_redis()
    job = await enqueue_job(redis, payload)
    return JSONResponse(content={"job_id": job.job_id, "status": job.status})


@router.get("/orchestrate/status/{job_id}")
async def orchestrate_status(job_id: str):
    redis = await get_redis()
    job = await get_job(redis, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse(content={
        "job_id": job.job_id,
        "status": job.status,
        "error": job.error,
        "output_dir": job.output_dir,
        "voiceover_path": job.voiceover_path,
        "image_files": job.image_files,
        "comfy_prompt_ids": job.comfy_prompt_ids,
    })
