import asyncio
from typing import Optional

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from temporalio.client import Client
from temporalio.worker import Worker

from videomerge.config import TEMPORAL_SERVER_URL
from videomerge.services.metrics import registry
from videomerge.temporal.workflows import VideoGenerationWorkflow, ProcessSceneWorkflow, VideoUpscalingWorkflow, VideoUpscalingChildWorkflow, VideoUpscalingStitchWorkflow
from videomerge.temporal import activities
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)

_METRICS_HOST = "0.0.0.0"
_METRICS_PORT = 9100


async def _handle_metrics(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single HTTP request to the worker metrics endpoint.

    This implements a minimal HTTP 1.1 server that serves ``/metrics`` using the
    shared Prometheus ``registry`` from ``videomerge.services.metrics``.
    """
    try:
        request_line = await reader.readline()
        if not request_line:
            return

        parts = request_line.split(maxsplit=2)
        if len(parts) < 2:
            return

        method, path = parts[0], parts[1]

        # Consume and ignore the rest of the request headers/body.
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        status_line: bytes
        headers: list[bytes]
        body: bytes

        if method == b"GET" and path in (b"/metrics", b"/metrics/"):
            body = generate_latest(registry)
            status_line = b"HTTP/1.1 200 OK"
            headers = [
                b"Content-Type: " + CONTENT_TYPE_LATEST.encode("ascii"),
                f"Content-Length: {len(body)}".encode("ascii"),
                b"Connection: close",
            ]
        else:
            body = b"Not Found"
            status_line = b"HTTP/1.1 404 Not Found"
            headers = [
                b"Content-Type: text/plain; charset=utf-8",
                f"Content-Length: {len(body)}".encode("ascii"),
                b"Connection: close",
            ]

        response_head = b"\r\n".join([status_line, *headers, b"", b""])
        writer.write(response_head + body)
        await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            # Best-effort cleanup; ignore socket errors during shutdown.
            pass


async def _start_metrics_server() -> Optional[asyncio.AbstractServer]:
    """Start the metrics HTTP server for the Temporal worker.

    Returns the created ``asyncio.AbstractServer`` instance, or ``None`` if the
    server fails to bind (for example if the port is already in use).
    """
    try:
        server = await asyncio.start_server(_handle_metrics, _METRICS_HOST, _METRICS_PORT)
    except OSError as exc:  # Port already in use or similar
        logger.warning("Failed to start worker metrics server on %s:%s: %s", _METRICS_HOST, _METRICS_PORT, exc)
        return None

    sockets = server.sockets or []
    bound_addrs = ", ".join(str(sock.getsockname()) for sock in sockets)
    logger.info("Worker metrics server listening on %s", bound_addrs)
    return server


async def main() -> None:
    """Entry point for the Temporal worker."""
    metrics_server = await _start_metrics_server()

    logger.info("Connecting to Temporal server at %s", TEMPORAL_SERVER_URL)
    client = await Client.connect(TEMPORAL_SERVER_URL)

    # Create workers for each task queue
    worker_gen = Worker(
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
            activities.start_video_upscaling,
            activities.poll_upscale_status,
            activities.send_upscale_completion_webhook,
        ],
    )

    worker_upscale = Worker(
        client,
        task_queue="video-upscaling-task-queue",
        workflows=[VideoUpscalingWorkflow, VideoUpscalingChildWorkflow, VideoUpscalingStitchWorkflow],
        activities=[
            activities.setup_run_directory,
            activities.start_video_upscaling,
            activities.poll_upscale_status,
            activities.stitch_videos,
            activities.burn_subtitles_into_video,
            activities.send_upscale_completion_webhook,
        ],
    )

    logger.info("Starting Temporal worker...")

    try:
        await asyncio.gather(worker_gen.run(), worker_upscale.run())
    finally:
        if metrics_server is not None:
            metrics_server.close()
            await metrics_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Temporal worker shutting down.")
