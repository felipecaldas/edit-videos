import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from videomerge.config import DATA_SHARED_BASE, ENABLE_IMAGE_GEN, COMFYUI_TIMEOUT_SECONDS, COMFYUI_POLL_INTERVAL_SECONDS, ENABLE_VOICEOVER_GEN
from videomerge.services.redis_client import get_redis
from videomerge.services.queue import QUEUE_KEY, get_job, set_job, Job, push_dead_letter
from videomerge.services.voiceover import synthesize_voice
from videomerge.services.comfyui import (
    submit_text_to_image,
    submit_image_to_video,
    poll_until_complete,
    download_outputs,
    fetch_output_bytes,
    upload_image_to_input,
)
from videomerge.utils.logging import get_logger
from videomerge.services.stitcher import (
    concat_videos_with_voiceover,
    generate_and_burn_subtitles,
)

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

            # synthesize voiceover (optional)
            audio_path: Path | None = None
            if ENABLE_VOICEOVER_GEN:
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
            else:
                logger.info("[worker] Voiceover generation disabled by ENABLE_VOICEOVER_GEN. Skipping.")

            # Helper for console progress bar
            def _progress_bar(current: int, total: int, width: int = 30) -> str:
                if total <= 0:
                    return "[------------------------------] 0/0"
                current = max(0, min(current, total))
                filled = int(width * current / total)
                return f"[{'#' * filled}{'.' * (width - filled)}] {current}/{total}"

            # Optional: ComfyUI text->image generation
            image_files: list[str] = []  # flat list, ordered by prompt index where an image was produced
            comfy_ids: list[str] = []
            # Maintain strict index alignment: map prompt index -> first image filename returned
            image_by_index: dict[int, str] = {}
            # Map prompt index -> uploaded filename in ComfyUI input directory
            uploaded_image_by_index: dict[int, str] = {}
            # Determine whether to run image generation for this job
            enable_image = ENABLE_IMAGE_GEN
            if isinstance(payload.get("enable_image_gen"), bool):
                enable_image = bool(payload.get("enable_image_gen"))

            # Precompute image targets (only prompts with a non-empty image_prompt)
            img_targets = [idx for idx, item in enumerate(prompts) if (item.get("image_prompt") or "").strip()]
            images_total = len(img_targets)

            if enable_image and images_total:
                logger.info("[worker] Image generation enabled. Processing %d prompt items", len(prompts))
                logger.info("[progress] Images %s", _progress_bar(0, images_total))
                _t0_imgs_total = time.perf_counter()
                images_done = 0
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
                        images_done += 1
                        logger.info("[progress] Images %s", _progress_bar(images_done, images_total))
                    except Exception as e:
                        # Abort entire job and push to DLQ on any image-generation failure
                        job.status = "failed"
                        job.error = f"image_generation_failed at index {idx+1}: {e}"
                        await set_job(redis, job)
                        await push_dead_letter(redis, job, reason="image_generation_failed")
                        logger.exception("[worker] Image generation failed for prompt %d: %s. Job aborted and sent to DLQ.", idx + 1, e)
                        return
                _t1_imgs_total = time.perf_counter()
                logger.info(
                    "[metrics] total_images_generation_seconds=%.3f images_count=%d run_id=%s job_id=%s",
                    _t1_imgs_total - _t0_imgs_total,
                    len(image_files),
                    run_id,
                    job.job_id,
                )

            # Before I2V: ensure images exist in ComfyUI input; fetch from output and upload
            if image_by_index:
                for idx, hint in image_by_index.items():
                    try:
                        fname, content = fetch_output_bytes(hint)
                        uploaded_name = upload_image_to_input(fname, content, overwrite=True)
                        uploaded_image_by_index[idx] = uploaded_name
                        logger.debug("[worker] Uploaded image for index %d to ComfyUI input as %s", idx + 1, uploaded_name)
                    except Exception as e:
                        job.status = "failed"
                        job.error = f"image_upload_failed at index {idx+1}: {e}"
                        await set_job(redis, job)
                        await push_dead_letter(redis, job, reason="image_upload_failed")
                        logger.exception("[worker] Failed to upload image for index %d: %s. Job aborted and sent to DLQ.", idx + 1, e)
                        return

            # Image-to-Video generation per prompt (strict index alignment)
            video_files: list[str] = []
            # Metrics total timer for videos
            if prompts and image_by_index:
                _t0_videos_total = time.perf_counter()
                # Precompute video targets: only prompts with non-empty video_prompt and with an image available
                video_targets = [
                    idx for idx, item in enumerate(prompts)
                    if (item.get("video_prompt") or "").strip() and (uploaded_image_by_index.get(idx) or image_by_index.get(idx))
                ]
                videos_total = len(video_targets)
                videos_done = 0
                if videos_total:
                    logger.info("[progress] Videos %s", _progress_bar(0, videos_total))

                for idx, item in enumerate(prompts):
                    v_prompt = (item.get("video_prompt") or "").strip()
                    if not v_prompt:
                        continue
                    # Use uploaded input filename if available; else fallback to original hint
                    image_name = uploaded_image_by_index.get(idx) or image_by_index.get(idx)
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
                            prefer_node_ids=["61", "60"],
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
                        if (item.get("video_prompt") or "").strip():
                            videos_done += 1
                            logger.info("[progress] Videos %s", _progress_bar(videos_done, videos_total))
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

            # Final stitching with subtitles (requires at least one video and voiceover when enabled)
            final_video_path_str: str | None = None
            if video_files and ENABLE_VOICEOVER_GEN and audio_path and audio_path.exists():
                try:
                    _t0_stitch = time.perf_counter()
                    stitched_path = concat_videos_with_voiceover(
                        [Path(p) for p in video_files], audio_path, run_dir / "stitched_output.mp4"
                    )
                    _t1_stitch = time.perf_counter()

                    _t0_subs = time.perf_counter()
                    final_path = generate_and_burn_subtitles(
                        stitched_path, run_dir / "stitched_subtitled.mp4", language='pt', model_size='small', position='bottom'
                    )
                    _t1_subs = time.perf_counter()

                    final_video_path_str = str(final_path)
                    logger.info(
                        "[metrics] stitch_seconds=%.3f subtitles_seconds=%.3f run_id=%s job_id=%s",
                        _t1_stitch - _t0_stitch,
                        _t1_subs - _t0_subs,
                        run_id,
                        job.job_id,
                    )
                except Exception as e:
                    logger.exception("[worker] Stitch with subtitles failed: %s", e)

            job.status = "completed"
            job.output_dir = str(run_dir)
            if audio_path and audio_path.exists():
                job.voiceover_path = str(audio_path)
            if image_files:
                job.image_files = image_files
                job.comfy_prompt_ids = comfy_ids
            if video_files:
                job.video_files = video_files
            if final_video_path_str:
                job.final_video_path = final_video_path_str
            await set_job(redis, job)
            logger.info("[worker] Completed job_id=%s", job.job_id)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            await set_job(redis, job)
            logger.exception("[worker] Job failed job_id=%s: %s", job.job_id, e)
