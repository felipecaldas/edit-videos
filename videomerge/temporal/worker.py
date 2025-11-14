import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from videomerge.config import TEMPORAL_SERVER_URL
from videomerge.temporal.workflows import VideoGenerationWorkflow, ProcessSceneWorkflow
from videomerge.temporal import activities
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


async def main():
    """Entry point for the Temporal worker."""
    logger.info(f"Connecting to Temporal server at {TEMPORAL_SERVER_URL}")
    client = await Client.connect(TEMPORAL_SERVER_URL)

    # Create a worker that connects to the server and hosts the workflow and activities.
    worker = Worker(
        client,
        task_queue="video-generation-task-queue",
        workflows=[VideoGenerationWorkflow, ProcessSceneWorkflow],
        activities=[
            activities.setup_run_directory,
            activities.generate_voiceover,
            activities.generate_scene_prompts,
            activities.generate_image,
            activities.upload_image_for_video_generation,
            activities.generate_video_from_image,
            activities.stitch_videos,
            activities.burn_subtitles_into_video,
            activities.send_completion_webhook,
        ],
    )

    logger.info("Starting Temporal worker...")
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Temporal worker shutting down.")
