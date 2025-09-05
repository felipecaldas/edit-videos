import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from videomerge.config import DATA_SHARED_BASE, ENABLE_IMAGE_GEN, COMFYUI_TIMEOUT_SECONDS, COMFYUI_POLL_INTERVAL_SECONDS
from videomerge.services.redis_client import get_redis
from videomerge.services.queue import QUEUE_KEY, get_job, set_job, Job
from videomerge.services.voiceover import synthesize_voice
from videomerge.services.comfyui import (
    submit_text_to_image,
    submit_image_to_video,
    poll_until_complete,
    download_outputs,
)
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
            _t0_vo = time.perf_counter()
            synthesize_voice(script, audio_path)
            _t1_vo = time.perf_counter()
            logger.info(
                "[metrics] voiceover_generation_seconds=%.3f run_id=%s job_id=%s",
                _t1_vo - _t0_vo,
                run_id,
                job.job_id,
            )

            # Optional: ComfyUI text->image generation
            image_files: list[str] = []  # flat list, ordered by prompt index where an image was produced
            comfy_ids: list[str] = []
            # Maintain strict index alignment: map prompt index -> first image filename returned
            image_by_index: dict[int, str] = {}
            # Determine whether to run image generation for this job
            enable_image = ENABLE_IMAGE_GEN
            if isinstance(payload.get("enable_image_gen"), bool):
                enable_image = bool(payload.get("enable_image_gen"))

            if enable_image and prompts:
                logger.info("[worker] Image generation enabled. Processing %d prompt items", len(prompts))
                _t0_imgs_total = time.perf_counter()
                for idx, item in enumerate(prompts):
                    # item is a dict at this point (originated from model_dump)
                    img_prompt = (item.get("image_prompt") or "").strip()
                    if not img_prompt:
                        continue
                    try:
                        _t0_img = time.perf_counter()
                        pid = submit_text_to_image(img_prompt)
                        comfy_ids.append(pid)
                        filenames = poll_until_complete(
                            pid,
                            timeout_s=COMFYUI_TIMEOUT_SECONDS,
                            poll_interval_s=COMFYUI_POLL_INTERVAL_SECONDS,
                        )
                        # Use the first filename for strict alignment; warn if multiple
                        if not filenames:
                            logger.warning("[worker] No image outputs for prompt index %d", idx + 1)
                        else:
                            if len(filenames) > 1:
                                logger.warning(
                                    "[worker] Multiple image outputs for prompt index %d; using the first one: %s",
                                    idx + 1,
                                    filenames[0],
                                )
                            image_by_index[idx] = filenames[0]
                            image_files.append(filenames[0])
                        # update job state incrementally
                        job.image_files = image_files
                        job.comfy_prompt_ids = comfy_ids
                        await set_job(redis, job)
                        _t1_img = time.perf_counter()
                        logger.info(
                            "[metrics] image_generation_seconds=%.3f prompt_index=%d filenames=%s run_id=%s job_id=%s",
                            _t1_img - _t0_img,
                            idx + 1,
                            filenames,
                            run_id,
                            job.job_id,
                        )
                    except Exception as e:
                        logger.exception("[worker] Image generation failed for prompt %d: %s", idx + 1, e)
                        # Do not fail the whole job; continue to next prompt
                _t1_imgs_total = time.perf_counter()
                logger.info(
                    "[metrics] total_images_generation_seconds=%.3f images_count=%d run_id=%s job_id=%s",
                    _t1_imgs_total - _t0_imgs_total,
                    len(image_files),
                    run_id,
                    job.job_id,
                )

            # Image-to-Video generation per prompt (strict index alignment)
            video_files: list[str] = []
            # Metrics total timer for videos
            if prompts and image_by_index:
                _t0_videos_total = time.perf_counter()
                for idx, item in enumerate(prompts):
                    v_prompt = (item.get("video_prompt") or "").strip()
                    if not v_prompt:
                        continue
                    image_name = image_by_index.get(idx)
                    if not image_name:
                        logger.warning(
                            "[worker] No image found for prompt index %d; skipping video generation for this index.",
                            idx + 1,
                        )
                        continue
                    try:
                        _t0_vid = time.perf_counter()
                        v_pid = submit_image_to_video(v_prompt, image_name)
                        v_outputs = poll_until_complete(
                            v_pid,
                            timeout_s=COMFYUI_TIMEOUT_SECONDS,
                            poll_interval_s=COMFYUI_POLL_INTERVAL_SECONDS,
                        )
                        # Filter to common video extensions to avoid re-downloading images here
                        video_hints = [h for h in v_outputs if h.lower().endswith((".mp4", ".webm", ".mov", ".mkv"))]
                        if not video_hints:
                            # If ComfyUI marks outputs differently, attempt to download all and infer by extension
                            video_hints = v_outputs
                        saved = download_outputs(video_hints, run_dir)
                        for p in saved:
                            video_files.append(str(p))
                        # Update job state incrementally
                        job.video_files = video_files
                        await set_job(redis, job)
                        _t1_vid = time.perf_counter()
                        logger.info(
                            "[metrics] video_generation_seconds=%.3f prompt_index=%d image=%s outputs=%s run_id=%s job_id=%s",
                            _t1_vid - _t0_vid,
                            idx + 1,
                            image_name,
                            [p.name for p in saved],
                            run_id,
                            job.job_id,
                        )
                    except Exception as e:
                        logger.exception("[worker] Video generation failed for prompt %d (image %s): %s", idx + 1, image_name, e)
                        # Continue with next prompt
                _t1_videos_total = time.perf_counter()
                logger.info(
                    "[metrics] total_videos_generation_seconds=%.3f videos_count=%d run_id=%s job_id=%s",
                    _t1_videos_total - _t0_videos_total,
                    len(video_files),
                    run_id,
                    job.job_id,
                )

            job.status = "completed"
            job.output_dir = str(run_dir)
            job.voiceover_path = str(audio_path)
            if image_files:
                job.image_files = image_files
                job.comfy_prompt_ids = comfy_ids
            if video_files:
                job.video_files = video_files
            await set_job(redis, job)
            logger.info("[worker] Completed job_id=%s", job.job_id)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            await set_job(redis, job)
            logger.exception("[worker] Job failed job_id=%s: %s", job.job_id, e)
