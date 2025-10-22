import asyncio
from datetime import timedelta
from typing import List

from temporalio import workflow
from temporalio.common import RetryPolicy

from videomerge.config import IMAGE_WORKFLOWS, WORKFLOWS_BASE_PATH, ENABLE_VOICEOVER_GEN
from videomerge.models import OrchestrateStartRequest, PromptItem

# Import all activities from the activities module
with workflow.unsafe.imports_passed_through():
    from videomerge.temporal.activities import (
        setup_run_directory,
        generate_voiceover,
        generate_image,
        upload_image_for_video_generation,
        generate_video_from_image,
        stitch_videos,
        burn_subtitles_into_video,
        send_completion_webhook,
    )


@workflow.defn
class ProcessSceneWorkflow:
    @workflow.run
    async def run(self, run_id: str, prompt: PromptItem, workflow_path: str, index: int) -> List[str]:
        """Workflow to process a single scene (image -> video)."""
        activity_defaults = {
            "start_to_close_timeout": timedelta(minutes=15),
            "retry_policy": RetryPolicy(maximum_attempts=3),
        }

        # 1. Generate image
        image_hint = ""
        if prompt.image_prompt:
            image_hint = await workflow.execute_activity(
                generate_image, args=[prompt.image_prompt, workflow_path, index], **activity_defaults
            )

        if not image_hint:
            workflow.logger.warning(f"Skipping scene {index} as no image was generated.")
            return []

        # 2. Upload image for video generation
        uploaded_image_name = await workflow.execute_activity(
            upload_image_for_video_generation, args=[image_hint], **activity_defaults
        )

        # 3. Generate video from image
        video_paths = []
        if prompt.video_prompt:
            video_paths = await workflow.execute_activity(
                generate_video_from_image, args=[run_id, prompt.video_prompt, uploaded_image_name, index], **activity_defaults
            )

        return video_paths


@workflow.defn
class VideoGenerationWorkflow:
    @workflow.run
    async def run(self, req: OrchestrateStartRequest) -> str:
        """Main workflow execution method."""
        workflow.logger.info(f"Starting video generation workflow for run_id={req.run_id}")

        # Define a retry policy for activities that might fail due to transient issues.
        retry_policy = RetryPolicy(
            maximum_attempts=3,
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
                    generate_voiceover, args=[req.run_id, req.script], **activity_defaults
                )
            else:
                workflow.logger.info("Skipping voiceover generation as ENABLE_VOICEOVER_GEN is false.")

            # 3. Process each scene as a child workflow
            scene_processing_tasks = []
            image_style = req.image_style or "default"
            workflow_filename = IMAGE_WORKFLOWS.get(image_style, IMAGE_WORKFLOWS["default"])
            workflow_path = f"{WORKFLOWS_BASE_PATH}/{workflow_filename}"

            for i, prompt in enumerate(req.prompts):
                # Each scene gets its own child workflow for better isolation and resumability
                child_id = f"{req.run_id}-scene-{i}"
                task = workflow.start_child_workflow(
                    ProcessSceneWorkflow.run, 
                    args=[req.run_id, prompt, workflow_path, i], 
                    id=child_id
                )
                scene_processing_tasks.append(task)

            # Collect all video file paths from the child workflows
            video_paths = []
            all_results = await asyncio.gather(*scene_processing_tasks)
            for result_list in all_results:
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

            # 8. Send completion webhook
            await workflow.execute_activity(
                send_completion_webhook, args=[req.run_id, "completed", final_video_path], **activity_defaults
            )

            workflow.logger.info(f"Workflow for run_id={req.run_id} completed successfully.")
            return final_video_path

        except Exception as e:
            workflow.logger.error(f"Workflow for run_id={req.run_id} failed: {e}")
            # Send failure webhook
            await workflow.execute_activity(
                send_completion_webhook, args=[req.run_id, "failed", ""], **activity_defaults
            )
            raise
