import asyncio
from datetime import timedelta
from pathlib import Path

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


def _root_cause_message(exc: BaseException) -> str:
    """Walk the __cause__ chain and return the deepest non-empty message.

    Temporal wraps activity/child-workflow errors in ``ActivityError`` or
    ``ChildWorkflowError`` whose ``str()`` is a generic label like
    "Activity task failed".  The real message (e.g. the RunPod validation
    error) lives in the innermost ``__cause__``.
    """
    msg = str(exc)
    current = exc
    while current.__cause__ is not None:
        current = current.__cause__
        cause_msg = str(current)
        if cause_msg:
            msg = cause_msg
    return msg

from videomerge.config import (
    ACTIVITY_SHORT_TIMEOUT_MINUTES,
    DATA_SHARED_BASE,
    DEFAULT_ACTIVITY_TIMEOUT_MINUTES,
    ENABLE_VOICEOVER_GEN,
    GENERATE_SCENES_TIMEOUT_MINUTES,
    IMAGE_HEIGHT,
    IMAGE_STYLE_TO_WORKFLOW_MAPPING,
    IMAGE_WIDTH,
    IMAGE_WORKFLOWS,
    SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS,
    STITCH_TIMEOUT_MINUTES,
    SUBTITLES_TIMEOUT_MINUTES,
    TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES,
    TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES,
    TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES,
    WORKFLOWS_BASE_PATH,
)
from videomerge.utils.video_dimensions import calculate_video_dimensions
from videomerge.models import (
    HandoffPayload,
    OrchestrateStartRequest,
    PromptItem,
    UpscaleStartRequest,
    UpscaleChildRequest,
    UpscaleStitchRequest,
    ImageGenerationStartRequest,
    StoryboardVideoGenerationRequest,
)

# Import all activities from the activities module
with workflow.unsafe.imports_passed_through():
    from videomerge.temporal.activities import (
        setup_run_directory,
        generate_voiceover,
        generate_scene_prompts,
        generate_image_scene_prompts,
        load_storyboard_scene_inputs,
        generate_image,
        persist_image_output,
        upload_final_video_output,
        start_image_generation,
        poll_image_generation,
        send_image_generation_webhook,
        upload_image_for_video_generation,
        generate_video_from_image,
        start_video_generation,
        poll_video_generation,
        stitch_videos,
        burn_subtitles_into_video,
        send_completion_webhook,
        handoff_to_compositor,
        poll_compose_status,
        download_video,
        classify_scenes_activity,
        start_image_generation_provider,
        poll_image_generation_provider,
        start_video_generation_provider,
        poll_video_generation_provider,
        start_video_upscaling,
        poll_upscale_status,
        save_upscaled_video,
        list_run_videos_for_upscale,
        list_upscaled_videos,
        encode_file_to_base64,
        send_upscale_completion_webhook,
        persist_scene_prompts,
    )
    from videomerge.services.brand_prompt import (
        build_prompt_items,
        resolve_platform_brief,
    )


@workflow.defn
class ProcessSceneWorkflow:
    @workflow.run
    async def run(
        self,
        run_id: str,
        prompt: PromptItem,
        workflow_path: str,
        index: int,
        image_width: int,
        image_height: int,
        video_width: int,
        video_height: int,
        comfyui_workflow_name: str | None = None,
        image_style: str | None = None,
    ) -> list[str]:
        """Workflow to process a single scene (image -> video)."""
        # Log parent workflow info for correlation
        parent_info = workflow.info().parent
        if parent_info:
            workflow.logger.info(
                f"Child workflow scene-{index} started by parent: "
                f"workflow_id={parent_info.workflow_id}, run_id={parent_info.run_id}"
            )
        
        # Retry transient failures but immediately fail on permanent errors
        # (e.g. invalid image_style, RunPod validation failures).
        scene_retry_policy = RetryPolicy(
            maximum_attempts=3,
            non_retryable_error_types=["NonRetryableError"],
        )
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
            "retry_policy": scene_retry_policy,
        }

        try:
            # 1. Generate image
            image_hint = ""
            if prompt.image_prompt:
                try:
                    image_job_id = await workflow.execute_activity(
                        start_image_generation,
                        args=[
                            run_id,
                            prompt.image_prompt,
                            workflow_path,
                            index,
                            image_width,
                            image_height,
                            comfyui_workflow_name,
                            image_style,
                        ],
                        start_to_close_timeout=timedelta(minutes=TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES),
                        retry_policy=scene_retry_policy,
                    )

                    image_hint = await workflow.execute_activity(
                        poll_image_generation,
                        args=[image_job_id, run_id, index],
                        schedule_to_close_timeout=timedelta(minutes=TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES),
                        start_to_close_timeout=timedelta(minutes=TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES),
                        heartbeat_timeout=timedelta(minutes=2),
                        retry_policy=scene_retry_policy,
                    )
                except Exception as e:
                    detail = _root_cause_message(e)
                    workflow.logger.error(f"Image generation failed for scene {index}: {detail}")
                    raise ApplicationError(
                        f"Scene {index} image generation failed: {detail}",
                        non_retryable=True,
                    )

            if not image_hint:
                workflow.logger.warning(f"Skipping scene {index} as no image was generated.")
                return []

            # 2. Upload image for video generation
            try:
                image_input = await workflow.execute_activity(
                    upload_image_for_video_generation, args=[image_hint], **activity_defaults
                )
            except Exception as e:
                detail = _root_cause_message(e)
                workflow.logger.error(f"Image upload failed for scene {index}: {detail}")
                raise ApplicationError(
                    f"Scene {index} image upload failed: {detail}",
                    non_retryable=True,
                )

            # 3. Generate video from image
            video_paths = []
            if prompt.video_prompt:
                try:
                    video_job_id = await workflow.execute_activity(
                        start_video_generation,
                        args=[run_id, prompt.video_prompt, image_input, index, video_width, video_height],
                        start_to_close_timeout=timedelta(minutes=TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES),
                        retry_policy=activity_defaults["retry_policy"],
                    )

                    video_paths = await workflow.execute_activity(
                        poll_video_generation,
                        args=[video_job_id, run_id, index],
                        schedule_to_close_timeout=timedelta(minutes=TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES),
                        start_to_close_timeout=timedelta(minutes=TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES),
                        heartbeat_timeout=timedelta(minutes=2),
                        retry_policy=activity_defaults["retry_policy"],
                    )
                except Exception as e:
                    detail = _root_cause_message(e)
                    workflow.logger.error(f"Video generation failed for scene {index}: {detail}")
                    raise ApplicationError(
                        f"Scene {index} video generation failed: {detail}",
                        non_retryable=True,
                    )

            workflow.logger.info(f"Scene {index} completed successfully, generated {len(video_paths)} video files")
            return video_paths
            
        except ApplicationError:
            raise
        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Scene {index} workflow failed: {detail}")
            raise ApplicationError(
                f"Scene {index} workflow failed: {detail}",
                non_retryable=True,
            )


@workflow.defn
class VideoGenerationWorkflow:
    @workflow.run
    async def run(self, req: OrchestrateStartRequest) -> str:
        """Main workflow execution method."""
        workflow.logger.info(f"Starting video generation workflow for run_id={req.run_id}")

        # Define a retry policy for activities that might fail due to transient issues.
        retry_policy = RetryPolicy(
            maximum_attempts=1,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
            "retry_policy": retry_policy,
        }

        try:
            # 1. Setup run directory and save manifest
            run_dir = await workflow.execute_activity(
                setup_run_directory,
                args=[req.run_id, req.model_dump()],
                start_to_close_timeout=timedelta(seconds=SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # 2. Generate voiceover (if enabled)
            voiceover_path = ""
            if ENABLE_VOICEOVER_GEN:
                voiceover_path = await workflow.execute_activity(
                    generate_voiceover,
                    args=[req.run_id, req.script, req.language, req.elevenlabs_voice_id],
                    start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                    retry_policy=retry_policy,
                )
            else:
                workflow.logger.info("Skipping voiceover generation as ENABLE_VOICEOVER_GEN is false.")

            if not voiceover_path:
                if run_dir.endswith("/") or run_dir.endswith("\\"):
                    default_voiceover = f"{run_dir}voiceover.mp3"
                elif "\\" in run_dir:
                    default_voiceover = f"{run_dir}\\voiceover.mp3"
                else:
                    default_voiceover = f"{run_dir}/voiceover.mp3"

                workflow.logger.info("Using default voiceover path %s", default_voiceover)
                voiceover_path = default_voiceover

            # 3. Generate prompts for each scene via external service
            image_style = req.image_style or "default"
            timeout_retry_policy = RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
                non_retryable_error_types=["RuntimeError"],
            )
            scene_prompts = await workflow.execute_activity(
                generate_scene_prompts,
                args=[req.run_id, req.script, image_style],
                start_to_close_timeout=timedelta(minutes=GENERATE_SCENES_TIMEOUT_MINUTES),
                retry_policy=timeout_retry_policy,
            )

            image_width = int(req.image_width) if req.image_width is not None else int(IMAGE_WIDTH)
            image_height = int(req.image_height) if req.image_height is not None else int(IMAGE_HEIGHT)
            
            # Calculate video dimensions from format and resolution
            video_width, video_height = calculate_video_dimensions(req.video_format, req.target_resolution)

            # 4. Process each scene as a child workflow
            scene_processing_tasks = []
            workflow_filename = IMAGE_WORKFLOWS.get(image_style, IMAGE_WORKFLOWS["default"])
            workflow_path = f"{WORKFLOWS_BASE_PATH}/{workflow_filename}"

            # Map image_style to comfyui_workflow_name using the YAML config
            comfyui_workflow_name: str | None = IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)

            # Resolve z_image_style: only applies when using the Z Image model
            z_image_style: str | None = req.z_image_style if comfyui_workflow_name == "z-image-photo" else None

            # Get parent workflow info for child correlation
            parent_workflow_id = workflow.info().workflow_id
            parent_run_id = workflow.info().run_id
            
            for i, prompt in enumerate(scene_prompts):
                # Support both dict-based prompts and PromptItem-like objects
                if isinstance(prompt, dict):
                    image_prompt = prompt.get("image_prompt")
                    video_prompt = prompt.get("video_prompt")
                else:
                    image_prompt = getattr(prompt, "image_prompt", None)
                    video_prompt = getattr(prompt, "video_prompt", None)
                # Each scene gets its own child workflow for better isolation and resumability
                child_id = f"{req.run_id}-scene-{i}"
                
                # Add memo and search attributes for parent-child correlation
                # Note: Parent workflow also has TabarioRunId set (in orchestrate.py)
                task = workflow.execute_child_workflow(
                    ProcessSceneWorkflow.run,
                    args=[
                        req.run_id,
                        prompt,
                        workflow_path,
                        i,
                        image_width,
                        image_height,
                        video_width,
                        video_height,
                        comfyui_workflow_name,
                        z_image_style,
                    ],
                    id=child_id,
                    memo={
                        "parent_workflow_id": parent_workflow_id,
                        "parent_run_id": parent_run_id,
                        "scene_index": str(i),
                        "run_id": req.run_id,
                    },
                    search_attributes={
                        "TabarioRunId": [req.run_id],  # Allows searching all workflows by run_id
                    }
                )
                scene_processing_tasks.append(task)
                
                workflow.logger.info(
                    f"Started child workflow {child_id} for scene {i} "
                    f"(parent: {parent_workflow_id})"
                )

            # Collect all video file paths from the child workflows
            # Start all child workflows immediately - RunPod will handle queuing
            workflow.logger.info(f"Starting {len(scene_processing_tasks)} scene child workflows (RunPod will queue)")
            
            results = await asyncio.gather(*scene_processing_tasks)
            video_paths = []
            for result_list in results:
                video_paths.extend(result_list)

            if not video_paths:
                raise ApplicationError(
                    "No video clips were generated.",
                    non_retryable=True,
                )

            # 6. Compositor handoff OR legacy stitch/subtitle/upload/webhook tail
            effective_handoff = (
                req.handoff_to_compositor
                if req.handoff_to_compositor is not None
                else bool(req.brief and req.platform and req.client_id)
            )

            if effective_handoff:
                handoff_payload = HandoffPayload(
                    run_id=req.run_id,
                    client_id=req.client_id,
                    brief=req.brief,
                    platform=req.platform,
                    voiceover_path=voiceover_path,
                    clip_paths=video_paths,
                    video_format=req.video_format or "9:16",
                    target_resolution=req.target_resolution,
                    video_idea_id=req.video_idea_id,
                    workflow_id=req.workflow_id,
                    user_access_token=req.user_access_token or "",
                )
                handoff_retry_policy = RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    non_retryable_error_types=["NonRetryableError"],
                )
                try:
                    compose_job_id = await workflow.execute_activity(
                        handoff_to_compositor,
                        args=[handoff_payload],
                        start_to_close_timeout=timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
                        retry_policy=handoff_retry_policy,
                    )
                    workflow.logger.info(
                        f"Handoff to compositor succeeded for run_id={req.run_id} compose_job_id={compose_job_id}"
                    )
                except Exception as handoff_exc:
                    detail = _root_cause_message(handoff_exc)
                    workflow.logger.error(
                        f"Handoff activity failed for run_id={req.run_id}: {detail}"
                    )
                    await workflow.execute_activity(
                        send_completion_webhook,
                        args=[
                            req.run_id,
                            "failed",
                            "",
                            req.workflow_id,
                            run_dir,
                            video_paths,
                            [],
                            voiceover_path,
                            detail,
                            None,
                            req.video_idea_id,
                            req.platform,
                        ],
                        start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                        retry_policy=retry_policy,
                    )
                    raise ApplicationError(
                        f"Handoff to compositor failed for run_id={req.run_id}: {detail}",
                        non_retryable=True,
                    ) from handoff_exc

                # Poll compositor until composed.mp4 is ready
                final_video_path = await workflow.execute_activity(
                    poll_compose_status,
                    args=[compose_job_id, req.run_id],
                    schedule_to_close_timeout=timedelta(minutes=30),
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=retry_policy,
                )
                workflow.logger.info(
                    f"Compositor finished for run_id={req.run_id}; final_video_path={final_video_path}"
                )

                # Upload composed video to Supabase and fire completion webhook
                uploaded_object_path = await workflow.execute_activity(
                    upload_final_video_output,
                    args=[req.run_id, req.user_id, final_video_path, req.user_access_token],
                    start_to_close_timeout=timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
                    retry_policy=retry_policy,
                )
                await workflow.execute_activity(
                    send_completion_webhook,
                    args=[
                        req.run_id,
                        "completed",
                        final_video_path,
                        req.workflow_id,
                        run_dir,
                        video_paths,
                        [],
                        voiceover_path,
                        None,
                        uploaded_object_path,
                        req.video_idea_id,
                        req.platform,
                    ],
                    start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                    retry_policy=retry_policy,
                )

                workflow.logger.info(f"Workflow for run_id={req.run_id} completed via compositor handoff.")
                return final_video_path

            # Legacy tail: stitch -> subtitles -> upload -> webhook
            stitched_video_path = await workflow.execute_activity(
                stitch_videos,
                args=[req.run_id, video_paths, voiceover_path],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            final_video_path = await workflow.execute_activity(
                burn_subtitles_into_video,
                args=[req.run_id, stitched_video_path, req.language, voiceover_path],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            # Collect generated image filenames from prompts for webhook payload
            image_files = []
            for prompt in scene_prompts:
                if isinstance(prompt, dict):
                    img = prompt.get("image_prompt")
                else:
                    img = getattr(prompt, "image_prompt", None)
                if img:
                    image_files.append(img)

            await workflow.execute_activity(
                send_completion_webhook,
                args=[
                    req.run_id,
                    "completed",
                    final_video_path,
                    req.workflow_id,
                    run_dir,
                    video_paths,
                    image_files,
                    voiceover_path,
                    None,  # failure_reason
                    None,  # uploaded_video_object_path
                    req.video_idea_id,
                    req.platform,
                ],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Workflow for run_id={req.run_id} completed successfully.")
            return final_video_path

        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Workflow for run_id={req.run_id} failed: {detail}")
            # Send failure webhook
            await workflow.execute_activity(
                send_completion_webhook,
                args=[
                    req.run_id,
                    "failed",
                    "",
                    req.workflow_id,
                    run_dir if "run_dir" in locals() else "",
                    locals().get("video_paths", []),
                    [
                        (p.get("image_prompt") if isinstance(p, dict) else getattr(p, "image_prompt", None)) or ""
                        for p in locals().get("scene_prompts", [])
                        if (p.get("image_prompt") if isinstance(p, dict) else getattr(p, "image_prompt", None))
                    ],
                    voiceover_path if "voiceover_path" in locals() else "",
                    detail,
                    None,  # uploaded_video_object_path
                    req.video_idea_id,
                    req.platform,
                ],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )
            if isinstance(e, ApplicationError):
                raise
            raise ApplicationError(
                f"Workflow for run_id={req.run_id} failed: {detail}",
                non_retryable=True,
            ) from e


@workflow.defn
class ImageGenerationWorkflow:
    @workflow.run
    async def run(self, req: ImageGenerationStartRequest) -> list[str]:
        """Generate ordered scene images and upload them to Supabase."""
        workflow.logger.info(f"Starting image generation workflow for run_id={req.run_id}")

        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=5),
            backoff_coefficient=2.0,
        )
        prompt_retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            non_retryable_error_types=["RuntimeError"],
        )
        image_retry_policy = RetryPolicy(
            maximum_attempts=3,
            non_retryable_error_types=["NonRetryableError"],
        )

        saved_images: list[str] = []
        try:
            await workflow.execute_activity(
                setup_run_directory,
                args=[req.run_id, req.model_dump()],
                start_to_close_timeout=timedelta(seconds=SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            image_style = req.image_style or "default"

            if req.brief and req.platform:
                # Brief-aware path: build prompts locally from branding fields
                pb = resolve_platform_brief(req.brief, req.platform)
                prompt_items = build_prompt_items(pb, req.brief)
                scene_prompts = [item.model_dump() for item in prompt_items]
                await workflow.execute_activity(
                    persist_scene_prompts,
                    args=[req.run_id, scene_prompts],
                    start_to_close_timeout=timedelta(minutes=GENERATE_SCENES_TIMEOUT_MINUTES),
                    retry_policy=prompt_retry_policy,
                )
                workflow.logger.info(
                    f"[image-prompts] Built {len(scene_prompts)} prompts from brief "
                    f"for run_id={req.run_id} platform={req.platform}"
                )
            else:
                # Legacy path: delegate to n8n prompts webhook
                scene_prompts = await workflow.execute_activity(
                    generate_image_scene_prompts,
                    args=[req.run_id, req.script, req.language, image_style],
                    start_to_close_timeout=timedelta(minutes=GENERATE_SCENES_TIMEOUT_MINUTES),
                    retry_policy=prompt_retry_policy,
                )

            image_width = int(req.image_width) if req.image_width is not None else int(IMAGE_WIDTH)
            image_height = int(req.image_height) if req.image_height is not None else int(IMAGE_HEIGHT)
            workflow_filename = IMAGE_WORKFLOWS.get(image_style, IMAGE_WORKFLOWS["default"])
            workflow_path = f"{WORKFLOWS_BASE_PATH}/{workflow_filename}"
            comfyui_workflow_name = IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)
            style_override = req.z_image_style if comfyui_workflow_name == "z-image-photo" else None

            image_prompts: list[tuple[int, str]] = []
            for index, prompt in enumerate(scene_prompts):
                image_prompt = prompt.get("image_prompt") if isinstance(prompt, dict) else getattr(prompt, "image_prompt", None)
                if not image_prompt:
                    raise ApplicationError(
                        f"Scene {index} is missing an image_prompt",
                        non_retryable=True,
                    )
                image_prompts.append((index, image_prompt))

            image_job_tasks = [
                workflow.start_activity(
                    start_image_generation,
                    args=[
                        req.run_id,
                        image_prompt,
                        workflow_path,
                        index,
                        image_width,
                        image_height,
                        comfyui_workflow_name,
                        style_override,
                    ],
                    start_to_close_timeout=timedelta(minutes=TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES),
                    retry_policy=image_retry_policy,
                )
                for index, image_prompt in image_prompts
            ]
            image_job_ids = await asyncio.gather(*image_job_tasks)

            image_hint_tasks = [
                workflow.start_activity(
                    poll_image_generation,
                    args=[image_job_id, req.run_id, index],
                    schedule_to_close_timeout=timedelta(minutes=TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES),
                    start_to_close_timeout=timedelta(minutes=TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=image_retry_policy,
                )
                for (index, _), image_job_id in zip(image_prompts, image_job_ids, strict=True)
            ]
            image_hints = await asyncio.gather(*image_hint_tasks)

            persist_tasks = [
                workflow.start_activity(
                    persist_image_output,
                    args=[req.run_id, req.user_id, image_hint, index, req.user_access_token],
                    start_to_close_timeout=timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
                    retry_policy=retry_policy,
                )
                for (index, _), image_hint in zip(image_prompts, image_hints, strict=True)
            ]
            saved_images = await asyncio.gather(*persist_tasks)
            ordered_image_prompts = [image_prompt for _, image_prompt in image_prompts]

            await workflow.execute_activity(
                send_image_generation_webhook,
                args=[
                    req.run_id,
                    req.user_id,
                    "completed",
                    saved_images,
                    ordered_image_prompts,
                    req.workflow_id,
                    None,  # failure_reason
                    req.video_idea_id,
                    req.platform,
                ],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )
            return saved_images

        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Image generation workflow for run_id={req.run_id} failed: {detail}")
            await workflow.execute_activity(
                send_image_generation_webhook,
                args=[
                    req.run_id,
                    req.user_id,
                    "failed",
                    saved_images,
                    ordered_image_prompts if "ordered_image_prompts" in locals() else [],
                    req.workflow_id,
                    detail,
                    req.video_idea_id,
                    req.platform,
                ],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )
            if isinstance(e, ApplicationError):
                raise
            raise ApplicationError(
                f"Image generation workflow for run_id={req.run_id} failed: {detail}",
                non_retryable=True,
            ) from e


@workflow.defn
class StoryBoardVideoGeneration:
    @workflow.run
    async def run(self, req: StoryboardVideoGenerationRequest) -> str:
        """Generate ordered storyboard-based video clips and publish the final video."""
        workflow.logger.info(f"Starting storyboard video generation workflow for run_id={req.run_id}")

        retry_policy = RetryPolicy(
            maximum_attempts=1,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )
        prompt_retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            non_retryable_error_types=["RuntimeError"],
        )
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
            "retry_policy": retry_policy,
        }

        video_paths: list[str] = []
        try:
            run_dir = await workflow.execute_activity(
                setup_run_directory,
                args=[req.run_id, req.model_dump()],
                start_to_close_timeout=timedelta(seconds=SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            voiceover_path = await workflow.execute_activity(
                generate_voiceover,
                args=[req.run_id, req.script, req.language, req.elevenlabs_voice_id],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            scene_inputs = await workflow.execute_activity(
                load_storyboard_scene_inputs,
                args=[req.run_id],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=prompt_retry_policy,
            )

            video_width, video_height = calculate_video_dimensions(req.video_format, req.target_resolution)

            start_tasks = []
            for scene_input in scene_inputs:
                start_tasks.append(
                    workflow.start_activity(
                        start_video_generation,
                        args=[
                            req.run_id,
                            scene_input["video_prompt"],
                            scene_input["image_path"],
                            int(scene_input["index"]),
                            video_width,
                            video_height,
                        ],
                        start_to_close_timeout=timedelta(minutes=TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES),
                        retry_policy=retry_policy,
                    )
                )

            video_job_ids = await asyncio.gather(*start_tasks)

            poll_tasks = [
                workflow.start_activity(
                    poll_video_generation,
                    args=[video_job_id, req.run_id, int(scene_input["index"])],
                    schedule_to_close_timeout=timedelta(minutes=TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES),
                    start_to_close_timeout=timedelta(minutes=TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=retry_policy,
                )
                for scene_input, video_job_id in zip(scene_inputs, video_job_ids, strict=True)
            ]
            raw_video_paths = await asyncio.gather(*poll_tasks)

            for scene_input, result_list in zip(scene_inputs, raw_video_paths, strict=True):
                if not result_list:
                    raise ApplicationError(
                        f"No video output generated for scene {scene_input['index']}",
                        non_retryable=True,
                    )
                video_paths.append(result_list[0])

            # Compositor handoff OR legacy stitch/subtitle/upload/webhook tail
            effective_handoff = (
                req.handoff_to_compositor
                if req.handoff_to_compositor is not None
                else bool(req.brief and req.platform and req.client_id)
            )

            if effective_handoff:
                handoff_payload = HandoffPayload(
                    run_id=req.run_id,
                    client_id=req.client_id,
                    brief=req.brief,
                    platform=req.platform,
                    voiceover_path=voiceover_path,
                    clip_paths=video_paths,
                    video_format=req.video_format or "9:16",
                    target_resolution=req.target_resolution,
                    video_idea_id=req.video_idea_id,
                    workflow_id=req.workflow_id,
                    user_access_token=req.user_access_token,
                )
                handoff_retry_policy = RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    non_retryable_error_types=["NonRetryableError"],
                )
                try:
                    compose_job_id = await workflow.execute_activity(
                        handoff_to_compositor,
                        args=[handoff_payload],
                        start_to_close_timeout=timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
                        retry_policy=handoff_retry_policy,
                    )
                    workflow.logger.info(
                        "Handoff to compositor succeeded for run_id=%s compose_job_id=%s",
                        req.run_id,
                        compose_job_id,
                    )
                except Exception as handoff_exc:
                    detail = _root_cause_message(handoff_exc)
                    workflow.logger.error(
                        "Handoff activity failed for run_id=%s: %s", req.run_id, detail
                    )
                    await workflow.execute_activity(
                        send_completion_webhook,
                        args=[
                            req.run_id,
                            "failed",
                            "",
                            req.workflow_id,
                            locals().get("run_dir", ""),
                            video_paths,
                            [],
                            voiceover_path,
                            detail,
                            None,
                            req.video_idea_id,
                            req.platform,
                        ],
                        **activity_defaults,
                    )
                    raise ApplicationError(
                        f"Handoff to compositor failed for run_id={req.run_id}: {detail}",
                        non_retryable=True,
                    ) from handoff_exc

                # Poll compositor until composed.mp4 is ready
                final_video_path = await workflow.execute_activity(
                    poll_compose_status,
                    args=[compose_job_id, req.run_id],
                    schedule_to_close_timeout=timedelta(minutes=30),
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=retry_policy,
                )
                workflow.logger.info(
                    "Compositor finished for run_id=%s; final_video_path=%s",
                    req.run_id,
                    final_video_path,
                )

                # Upload composed video to Supabase and fire completion webhook
                uploaded_object_path = await workflow.execute_activity(
                    upload_final_video_output,
                    args=[req.run_id, req.user_id, final_video_path, req.user_access_token],
                    start_to_close_timeout=timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
                    retry_policy=retry_policy,
                )
                await workflow.execute_activity(
                    send_completion_webhook,
                    args=[
                        req.run_id,
                        "completed",
                        final_video_path,
                        req.workflow_id,
                        locals().get("run_dir", ""),
                        video_paths,
                        [],
                        voiceover_path,
                        None,
                        uploaded_object_path,
                        req.video_idea_id,
                        req.platform,
                    ],
                    **activity_defaults,
                )

                workflow.logger.info(
                    "Storyboard video generation completed via compositor handoff for run_id=%s",
                    req.run_id,
                )
                return final_video_path

            # Legacy tail: stitch -> subtitles -> upload -> webhook
            stitched_video_path = await workflow.execute_activity(
                stitch_videos,
                args=[req.run_id, video_paths, voiceover_path],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            final_video_path = await workflow.execute_activity(
                burn_subtitles_into_video,
                args=[req.run_id, stitched_video_path, req.language, voiceover_path],
                start_to_close_timeout=timedelta(minutes=ACTIVITY_SHORT_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            uploaded_object_path = await workflow.execute_activity(
                upload_final_video_output,
                args=[req.run_id, req.user_id, final_video_path, req.user_access_token],
                start_to_close_timeout=timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            await workflow.execute_activity(
                send_completion_webhook,
                args=[
                    req.run_id,
                    "completed",
                    final_video_path,
                    req.workflow_id,
                    run_dir,
                    video_paths,
                    [],
                    voiceover_path,
                    None,
                    uploaded_object_path,
                    req.video_idea_id,
                    req.platform,
                ],
                **activity_defaults,
            )

            workflow.logger.info(
                "Storyboard video generation completed for run_id=%s with final_video=%s uploaded_object=%s",
                req.run_id,
                final_video_path,
                uploaded_object_path,
            )
            return final_video_path

        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Storyboard video generation workflow for run_id={req.run_id} failed: {detail}")
            await workflow.execute_activity(
                send_completion_webhook,
                args=[
                    req.run_id,
                    "failed",
                    "",
                    req.workflow_id,
                    locals().get("run_dir", ""),
                    video_paths,
                    [],
                    locals().get("voiceover_path", ""),
                    detail,
                    None,  # uploaded_video_object_path
                    req.video_idea_id,
                    req.platform,
                ],
                **activity_defaults,
            )
            if isinstance(e, ApplicationError):
                raise
            raise ApplicationError(
                f"Storyboard video generation workflow for run_id={req.run_id} failed: {detail}",
                non_retryable=True,
            ) from e


@workflow.defn
class VideoUpscalingChildWorkflow:
    @workflow.run
    async def run(self, req: UpscaleChildRequest) -> str:
        """Main workflow execution method for video upscaling."""
        workflow.logger.info(f"Starting video upscaling workflow for video_id={req.video_id}")

        # Define a retry policy for activities that might fail due to transient issues.
        retry_policy = RetryPolicy(
            maximum_attempts=1,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )

        # Polling an existing RunPod job is idempotent and safe to retry,
        # but permanent failures (e.g. FAILED status) should not be retried.
        poll_retry_policy = RetryPolicy(
            maximum_attempts=20,
            initial_interval=timedelta(seconds=5),
            backoff_coefficient=1.5,
            maximum_interval=timedelta(minutes=2),
            non_retryable_error_types=["NonRetryableError"],
        )
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
            "retry_policy": retry_policy,
        }

        try:
            # 1. Setup run directory and save manifest
            run_dir = await workflow.execute_activity(
                setup_run_directory,
                args=[req.run_id, req.model_dump()],
                start_to_close_timeout=timedelta(seconds=SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # 2. Prepare and call Runpod upscaling
            upscale_job_id = await workflow.execute_activity(
                start_video_upscaling,
                args=[req.video_id, req.video_path, req.target_resolution],
                start_to_close_timeout=timedelta(minutes=TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            # 3. Poll for completion and save to disk (returns file path)
            upscaled_video_path = await workflow.execute_activity(
                poll_upscale_status,
                args=[upscale_job_id, req.run_id, req.video_id],
                # Allow long queue delays while still treating single attempts as bounded.
                schedule_to_close_timeout=timedelta(minutes=TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES),
                start_to_close_timeout=timedelta(minutes=TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=poll_retry_policy,
            )

            workflow.logger.info(f"Upscaling workflow for video_id={req.video_id} completed successfully. Saved to {upscaled_video_path}")
            return upscaled_video_path

        except ApplicationError:
            raise
        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Upscaling workflow for video_id={req.video_id} failed: {detail}")
            raise ApplicationError(
                f"Upscaling workflow for video_id={req.video_id} failed: {detail}",
                non_retryable=True,
            ) from e


@workflow.defn
class VideoUpscalingStitchWorkflow:
    @workflow.run
    async def run(self, req: UpscaleStitchRequest) -> str:
        """Workflow to stitch upscaled videos with voiceover and burn subtitles."""
        workflow.logger.info(f"Starting upscaling stitch workflow for run_id={req.run_id}")

        # Define a retry policy for activities that might fail due to transient issues.
        retry_policy = RetryPolicy(
            maximum_attempts=1,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
            "retry_policy": retry_policy,
        }

        try:
            run_dir = DATA_SHARED_BASE / req.run_id

            upscaled_files = await workflow.execute_activity(
                list_upscaled_videos,
                args=[req.run_id],
                **activity_defaults,
            )
            workflow.logger.info(f"Found {len(upscaled_files)} upscaled video files to stitch")

            voiceover_path = DATA_SHARED_BASE / req.run_id / "voiceover.mp3"
            srt_path = DATA_SHARED_BASE / req.run_id / "generated.srt"

            # Stitch videos with voiceover
            output_path = run_dir / "stitched_output.mp4"
            await workflow.execute_activity(
                stitch_videos,
                args=[req.run_id, [str(p) for p in upscaled_files], str(voiceover_path)],
                start_to_close_timeout=timedelta(minutes=STITCH_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            # Burn subtitles into video
            final_path = run_dir / "final_video.mp4"
            final_video_path = await workflow.execute_activity(
                burn_subtitles_into_video,
                args=[req.run_id, str(output_path), req.voice_language or "en", str(voiceover_path)],
                start_to_close_timeout=timedelta(minutes=SUBTITLES_TIMEOUT_MINUTES),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Upscaling stitch workflow for run_id={req.run_id} completed successfully.")
            return final_video_path

        except ApplicationError:
            raise
        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Upscaling stitch workflow for run_id={req.run_id} failed: {detail}")
            raise ApplicationError(
                f"Upscaling stitch workflow for run_id={req.run_id} failed: {detail}",
                non_retryable=True,
            ) from e


@workflow.defn
class VideoUpscalingWorkflow:
    @workflow.run
    async def run(self, req: UpscaleStartRequest) -> str:
        """Parent workflow for video upscaling that starts child workflows for each video clip."""
        workflow.logger.info(f"Starting video upscaling parent workflow for run_id={req.run_id}")

        # Define a retry policy for activities that might fail due to transient issues.
        retry_policy = RetryPolicy(
            maximum_attempts=1,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=DEFAULT_ACTIVITY_TIMEOUT_MINUTES),
            "retry_policy": retry_policy,
        }

        try:
            # List video files in shared directory (must be done via activity; workflow sandbox forbids I/O)
            video_files = await workflow.execute_activity(
                list_run_videos_for_upscale,
                args=[req.run_id],
                **activity_defaults,
            )

            workflow.logger.info(f"Found {len(video_files)} video files to upscale")
            
            # Start all upscaling child workflows immediately - RunPod will handle queuing
            workflow.logger.info(f"Starting {len(video_files)} upscaling child workflows (RunPod will queue)")
            
            futures = []
            for idx, video_file in enumerate(video_files):
                video_path = str(video_file)
                child_req = UpscaleChildRequest(
                    video_path=video_path,
                    video_id=Path(video_path).stem,  # filename without extension
                    run_id=req.run_id,
                    user_id=req.user_id,
                    target_resolution=req.target_resolution,
                    workflow_id=req.workflow_id,
                )

                futures.append(
                    workflow.execute_child_workflow(
                        VideoUpscalingChildWorkflow.run,
                        child_req,
                        id=f"upscale-child-{req.run_id}-{idx}",
                    )
                )

            await asyncio.gather(*futures)

            # Start stitching workflow
            final_video_path = await workflow.execute_child_workflow(
                VideoUpscalingStitchWorkflow.run,
                UpscaleStitchRequest(
                    run_id=req.run_id,
                    user_id=req.user_id,
                    workflow_id=req.workflow_id,
                    voice_language=req.voice_language,
                ),
                id=f"upscale-stitch-{req.run_id}",
            )

            # Send success webhook with final video path
            await workflow.execute_activity(
                send_upscale_completion_webhook,
                args=[
                    req.run_id,
                    final_video_path,
                    "completed",
                    req.workflow_id,
                    req.user_id,
                    None,
                ],
                **activity_defaults,
            )

            workflow.logger.info(f"Parent upscaling workflow for run_id={req.run_id} completed all workflows.")
            return "completed"

        except Exception as e:
            detail = _root_cause_message(e)
            workflow.logger.error(f"Parent upscaling workflow for run_id={req.run_id} failed: {detail}")
            # Send failure webhook
            await workflow.execute_activity(
                send_upscale_completion_webhook,
                args=[
                    req.run_id,
                    "",
                    "failed",
                    req.workflow_id,
                    req.user_id,
                    detail,
                ],
                **activity_defaults,
            )
            if isinstance(e, ApplicationError):
                raise
            raise ApplicationError(
                f"Parent upscaling workflow for run_id={req.run_id} failed: {detail}",
                non_retryable=True,
            ) from e
