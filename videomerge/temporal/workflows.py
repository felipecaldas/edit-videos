import asyncio
from datetime import timedelta
from pathlib import Path
import base64

from temporalio import workflow
from temporalio.common import RetryPolicy

from videomerge.config import IMAGE_WORKFLOWS, WORKFLOWS_BASE_PATH, ENABLE_VOICEOVER_GEN, IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_STYLE_TO_WORKFLOW_MAPPING
from videomerge.models import OrchestrateStartRequest, PromptItem, UpscaleStartRequest, UpscaleChildRequest, UpscaleStitchRequest

# Import all activities from the activities module
with workflow.unsafe.imports_passed_through():
    from videomerge.temporal.activities import (
        setup_run_directory,
        generate_voiceover,
        generate_scene_prompts,
        generate_image,
        upload_image_for_video_generation,
        generate_video_from_image,
        stitch_videos,
        burn_subtitles_into_video,
        send_completion_webhook,
        download_video,
        start_video_upscaling,
        poll_upscale_status,
        send_upscale_completion_webhook,
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
        comfyui_workflow_name: str | None = None,
    ) -> list[str]:
        """Workflow to process a single scene (image -> video)."""
        # Log parent workflow info for correlation
        parent_info = workflow.info().parent
        if parent_info:
            workflow.logger.info(
                f"Child workflow scene-{index} started by parent: "
                f"workflow_id={parent_info.workflow_id}, run_id={parent_info.run_id}"
            )
        
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=15),
            "retry_policy": RetryPolicy(maximum_attempts=3),
        }

        try:
            # 1. Generate image
            image_hint = ""
            if prompt.image_prompt:
                try:
                    image_hint = await workflow.execute_activity(
                        generate_image,
                        args=[
                            run_id,
                            prompt.image_prompt,
                            workflow_path,
                            index,
                            image_width,
                            image_height,
                            comfyui_workflow_name,
                        ],
                        **activity_defaults,
                    )
                except Exception as e:
                    workflow.logger.error(f"Image generation failed for scene {index}: {e}")
                    raise RuntimeError(f"Scene {index} image generation failed: {e}")

            if not image_hint:
                workflow.logger.warning(f"Skipping scene {index} as no image was generated.")
                return []

            # 2. Upload image for video generation
            try:
                image_input = await workflow.execute_activity(
                    upload_image_for_video_generation, args=[image_hint], **activity_defaults
                )
            except Exception as e:
                workflow.logger.error(f"Image upload failed for scene {index}: {e}")
                raise RuntimeError(f"Scene {index} image upload failed: {e}")

            # 3. Generate video from image
            video_paths = []
            if prompt.video_prompt:
                try:
                    video_paths = await workflow.execute_activity(
                        generate_video_from_image, args=[run_id, prompt.video_prompt, image_input, index], **activity_defaults
                    )
                except Exception as e:
                    workflow.logger.error(f"Video generation failed for scene {index}: {e}")
                    raise RuntimeError(f"Scene {index} video generation failed: {e}")

            workflow.logger.info(f"Scene {index} completed successfully, generated {len(video_paths)} video files")
            return video_paths
            
        except Exception as e:
            workflow.logger.error(f"Scene {index} workflow failed: {e}")
            # Re-raise the exception to ensure the workflow is marked as FAILED
            raise


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
            "start_to_close_timeout": timedelta(minutes=15),
            "retry_policy": retry_policy,
        }

        try:
            # 1. Setup run directory and save manifest
            run_dir = await workflow.execute_activity(
                setup_run_directory, args=[req.run_id, req.model_dump()], **activity_defaults
            )

            # 2. Generate voiceover (if enabled)
            voiceover_path = ""
            if ENABLE_VOICEOVER_GEN:
                voiceover_path = await workflow.execute_activity(
                    generate_voiceover,
                    args=[req.run_id, req.script, req.language, req.elevenlabs_voice_id],
                    **activity_defaults,
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
            scene_prompts = await workflow.execute_activity(
                generate_scene_prompts,
                args=[req.run_id, req.script, image_style],
                **activity_defaults,
            )

            image_width = int(req.image_width) if req.image_width is not None else int(IMAGE_WIDTH)
            image_height = int(req.image_height) if req.image_height is not None else int(IMAGE_HEIGHT)

            # 4. Process each scene as a child workflow
            scene_processing_tasks = []
            workflow_filename = IMAGE_WORKFLOWS.get(image_style, IMAGE_WORKFLOWS["default"])
            workflow_path = f"{WORKFLOWS_BASE_PATH}/{workflow_filename}"

            # Map image_style to comfyui_workflow_name using the YAML config
            comfyui_workflow_name: str | None = IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)

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
                        comfyui_workflow_name,
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
            video_paths = []
            results = await asyncio.gather(*scene_processing_tasks)
            for result_list in results:
                video_paths.extend(result_list)

            if not video_paths:
                raise RuntimeError("No video clips were generated.")

            # 6. Stitch all video clips together with the voiceover
            stitched_video_path = await workflow.execute_activity(
                stitch_videos, args=[req.run_id, video_paths, voiceover_path], **activity_defaults
            )

            # 7. Burn subtitles into the final video
            final_video_path = await workflow.execute_activity(
                burn_subtitles_into_video, args=[req.run_id, stitched_video_path, req.language, voiceover_path], **activity_defaults
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

            # 8. Send completion webhook
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
                ],
                **activity_defaults,
            )

            workflow.logger.info(f"Workflow for run_id={req.run_id} completed successfully.")
            return final_video_path

        except Exception as e:
            workflow.logger.error(f"Workflow for run_id={req.run_id} failed: {e}")
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
                    str(e),
                ],
                **activity_defaults,
            )
            raise


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
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=15),
            "retry_policy": retry_policy,
        }

        try:
            # 1. Setup run directory and save manifest
            run_dir = await workflow.execute_activity(
                setup_run_directory, args=[req.video_id, req.model_dump()], **activity_defaults
            )

            # 2. Prepare and call Runpod upscaling
            upscale_job_id = await workflow.execute_activity(
                start_video_upscaling, args=[req.video_id, req.video_path, req.target_resolution], **activity_defaults
            )

            # 3. Poll for completion
            upscaled_video_b64 = await workflow.execute_activity(
                poll_upscale_status, args=[upscale_job_id], **activity_defaults
            )

            # Save upscaled video to shared directory
            video_data = base64.b64decode(upscaled_video_b64)
            upscaled_path = Path("/data/shared") / req.run_id / f"{req.video_id}_upscaled.mp4"
            upscaled_path.parent.mkdir(parents=True, exist_ok=True)
            with open(upscaled_path, "wb") as f:
                f.write(video_data)
            workflow.logger.info(f"Saved upscaled video to {upscaled_path}")

            # 4. Send completion webhook
            await workflow.execute_activity(
                send_upscale_completion_webhook,
                args=[
                    req.video_id,
                    "completed",
                    upscaled_video_b64,
                    req.workflow_id,
                    req.user_id,
                    None,
                ],
                **activity_defaults,
            )

            workflow.logger.info(f"Upscaling workflow for video_id={req.video_id} completed successfully.")
            return upscaled_video_b64

        except Exception as e:
            workflow.logger.error(f"Upscaling workflow for video_id={req.video_id} failed: {e}")
            # Send failure webhook
            await workflow.execute_activity(
                send_upscale_completion_webhook,
                args=[
                    req.video_id,
                    "failed",
                    "",
                    req.workflow_id,
                    req.user_id,
                    None,
                    str(e),
                ],
                **activity_defaults,
            )
            raise


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
            "start_to_close_timeout": timedelta(minutes=15),
            "retry_policy": retry_policy,
        }

        try:
            shared_dir = Path("/data/shared") / req.run_id
            run_dir = DATA_SHARED_BASE / req.run_id

            # List upscaled video files and sort by prefix number
            upscaled_files = sorted(shared_dir.glob("*_upscaled.mp4"), key=lambda p: p.name.split('_')[0])

            workflow.logger.info(f"Found {len(upscaled_files)} upscaled video files to stitch")

            voiceover_path = shared_dir / "voiceover.mp3"
            srt_path = shared_dir / "generated.srt"

            # Stitch videos with voiceover
            output_path = run_dir / "stitched_output.mp4"
            await workflow.execute_activity(
                stitch_videos, args=[req.run_id, [str(p) for p in upscaled_files], str(voiceover_path)], **activity_defaults
            )

            # Burn subtitles into video
            final_path = run_dir / "final_video.mp4"
            await workflow.execute_activity(
                burn_subtitles_into_video, args=[req.run_id, str(output_path), "pt", str(voiceover_path)], **activity_defaults
            )

            # Read final video and encode to base64
            with open(final_path, "rb") as f:
                final_video_data = f.read()
            final_video_b64 = base64.b64encode(final_video_data).decode('utf-8')

            # Send completion webhook
            await workflow.execute_activity(
                send_upscale_completion_webhook,
                args=[
                    req.run_id,
                    "completed",
                    final_video_b64,
                    req.workflow_id,
                    req.user_id,
                    None,
                ],
                **activity_defaults,
            )

            workflow.logger.info(f"Upscaling stitch workflow for run_id={req.run_id} completed successfully.")
            return final_video_b64

        except Exception as e:
            workflow.logger.error(f"Upscaling stitch workflow for run_id={req.run_id} failed: {e}")
            raise


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
            "start_to_close_timeout": timedelta(minutes=15),
            "retry_policy": retry_policy,
        }

        try:
            # List video files in shared directory
            shared_dir = Path("/data/shared") / req.run_id
            video_files = sorted(shared_dir.glob("[0-9][0-9][0-9]_*.mp4"))

            workflow.logger.info(f"Found {len(video_files)} video files to upscale")

            # Start child workflow for each video file in parallel
            futures = []
            for idx, video_file in enumerate(video_files):
                child_req = UpscaleChildRequest(
                    video_path=str(video_file),
                    video_id=video_file.stem,  # filename without extension
                    run_id=req.run_id,
                    user_id=req.user_id,
                    target_resolution=req.target_resolution,
                    workflow_id=req.workflow_id,
                )

                futures.append(workflow.execute_child_workflow(
                    VideoUpscalingChildWorkflow.run,
                    child_req,
                    id=f"upscale-child-{req.run_id}-{idx}",
                ))

            # Wait for all upscaling children to complete
            await asyncio.gather(*futures)

            # Start stitching workflow
            await workflow.execute_child_workflow(
                VideoUpscalingStitchWorkflow.run,
                UpscaleStitchRequest(
                    run_id=req.run_id,
                    user_id=req.user_id,
                    workflow_id=req.workflow_id,
                ),
                id=f"upscale-stitch-{req.run_id}",
            )

            workflow.logger.info(f"Parent upscaling workflow for run_id={req.run_id} completed all workflows.")
            return "completed"

        except Exception as e:
            workflow.logger.error(f"Parent upscaling workflow for run_id={req.run_id} failed: {e}")
            raise
