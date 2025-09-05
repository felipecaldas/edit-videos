import asyncio
import json
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from videomerge.config import DATA_SHARED_BASE, ENABLE_IMAGE_GEN, COMFYUI_TIMEOUT_SECONDS, COMFYUI_POLL_INTERVAL_SECONDS
from videomerge.services.redis_client import get_redis
from videomerge.services.queue import QUEUE_KEY, get_job, set_job, Job
from videomerge.services.voiceover import synthesize_voice
from videomerge.services.comfyui import submit_text_to_image, poll_until_complete
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class Worker:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self):
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())
            logger.info("[worker] started")

    async def stop(self):
        self._stop_event.set()
        if self._task:
            await self._task
            logger.info("[worker] stopped")

    async def _run_loop(self):
        redis = await get_redis()
        while not self._stop_event.is_set():
            try:
                # BLPOP blocks until an item is available or timeout
                popped = await redis.blpop(QUEUE_KEY, timeout=2)
                if not popped:
                    # timeout, loop again to check stop_event
                    continue
                _key, job_id_bytes = popped
                job_id = job_id_bytes.decode("utf-8") if isinstance(job_id_bytes, (bytes, bytearray)) else str(job_id_bytes)
                job = await get_job(redis, job_id)
                if not job:
                    logger.warning("[worker] Job %s missing, skipping", job_id)
                    continue

                await self._process_job(job)
            except Exception as e:
                logger.exception("[worker] Loop error: %s", e)
                await asyncio.sleep(1)

    async def _process_job(self, job: Job):
        redis = await get_redis()
        logger.info("[worker] Processing job_id=%s", job.job_id)
        job.status = "running"
        job.error = None
        await set_job(redis, job)

        try:
            payload: Dict[str, Any] = job.payload
            run_id = (payload.get("run_id") or "").strip()
            script = payload.get("script") or ""
            caption = payload.get("caption") or ""
            prompts = payload.get("prompts") or []
            if not run_id:
                raise HTTPException(status_code=400, detail="run_id is required")

            run_dir: Path = DATA_SHARED_BASE / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            # persist manifest
            try:
                manifest = {
                    "script": script,
                    "caption": caption,
                    "run_id": run_id,
                    "prompts": prompts,
                    "job_id": job.job_id,
                }
                (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning("[worker] failed to write manifest.json: %s", e)

            # synthesize voiceover
            audio_path = run_dir / "voiceover.mp3"
            synthesize_voice(script, audio_path)

            # Optional: ComfyUI text->image generation
            image_files: list[str] = []
            comfy_ids: list[str] = []
            # Determine whether to run image generation for this job
            enable_image = ENABLE_IMAGE_GEN
            if isinstance(payload.get("enable_image_gen"), bool):
                enable_image = bool(payload.get("enable_image_gen"))

            if enable_image and prompts:
                logger.info("[worker] Image generation enabled. Processing %d prompt items", len(prompts))
                for idx, item in enumerate(prompts):
                    # item is a dict at this point (originated from model_dump)
                    img_prompt = (item.get("image_prompt") or "").strip()
                    if not img_prompt:
                        continue
                    try:
                        pid = submit_text_to_image(img_prompt)
                        comfy_ids.append(pid)
                        filenames = poll_until_complete(
                            pid,
                            timeout_s=COMFYUI_TIMEOUT_SECONDS,
                            poll_interval_s=COMFYUI_POLL_INTERVAL_SECONDS,
                        )
                        image_files.extend(filenames)
                        # update job state incrementally
                        job.image_files = image_files
                        job.comfy_prompt_ids = comfy_ids
                        await set_job(redis, job)
                        logger.info("[worker] Image prompt %d completed: %s", idx + 1, filenames)
                    except Exception as e:
                        logger.exception("[worker] Image generation failed for prompt %d: %s", idx + 1, e)
                        # Do not fail the whole job; continue to next prompt

            job.status = "completed"
            job.output_dir = str(run_dir)
            job.voiceover_path = str(audio_path)
            if image_files:
                job.image_files = image_files
                job.comfy_prompt_ids = comfy_ids
            await set_job(redis, job)
            logger.info("[worker] Completed job_id=%s", job.job_id)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            await set_job(redis, job)
            logger.exception("[worker] Job failed job_id=%s: %s", job.job_id, e)
