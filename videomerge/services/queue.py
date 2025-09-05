import json
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, List

from redis.asyncio import Redis

QUEUE_KEY = "video_orchestrator:queue"
JOB_PREFIX = "video_orchestrator:job:"


@dataclass
class Job:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"  # queued | running | completed | failed
    error: Optional[str] = None
    output_dir: Optional[str] = None
    voiceover_path: Optional[str] = None
    # Image generation (optional)
    image_files: List[str] | None = None
    comfy_prompt_ids: List[str] | None = None
    # Image-to-Video results (saved on disk)
    video_files: List[str] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(s: str) -> "Job":
        data = json.loads(s)
        return Job(**data)


def job_key(job_id: str) -> str:
    return f"{JOB_PREFIX}{job_id}"


async def enqueue_job(redis: Redis, payload: Dict[str, Any]) -> Job:
    job = Job(job_id=str(uuid.uuid4()), payload=payload)
    # Persist job state and push to queue
    await redis.set(job_key(job.job_id), job.to_json())
    await redis.rpush(QUEUE_KEY, job.job_id)
    return job


async def set_job(redis: Redis, job: Job) -> None:
    await redis.set(job_key(job.job_id), job.to_json())


async def get_job(redis: Redis, job_id: str) -> Optional[Job]:
    raw = await redis.get(job_key(job_id))
    if not raw:
        return None
    return Job.from_json(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
