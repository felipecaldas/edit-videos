from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio

from videomerge.routers.merge import router as merge_router
from videomerge.routers.stitch import router as stitch_router
from videomerge.routers.subtitles import router as subtitles_router
from videomerge.routers.health import router as health_router
from videomerge.routers.audio import router as audio_router
from videomerge.routers.orchestrate import router as orchestrate_router
from videomerge.routers.tiktok import router as tiktok_router
from videomerge.utils.logging import get_logger
from videomerge.services.worker import Worker
from videomerge.services.redis_client import close_redis, get_redis
from videomerge.services.metrics import get_metrics_response, update_queue_depth

logger = get_logger(__name__)


def create_app() -> FastAPI:
    worker = Worker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        await worker.start()
        logger.info("Application startup complete. Routers registered and worker started.")

        # Start queue depth monitoring task
        redis = await get_redis()
        queue_monitor_task = asyncio.create_task(update_queue_depth(redis, interval_seconds=10))
        logger.info("Queue depth monitoring task started")

        try:
            yield
        finally:
            # Shutdown
            queue_monitor_task.cancel()
            try:
                await queue_monitor_task
            except asyncio.CancelledError:
                pass
            await worker.stop()
            await close_redis()
            logger.info("Application shutdown complete. Worker stopped and Redis closed.")

    app = FastAPI(title="AI Video Generator", lifespan=lifespan)

    # Add metrics endpoint for Prometheus scraping
    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint"""
        return get_metrics_response()

    # Routers
    app.include_router(health_router)
    app.include_router(merge_router)
    app.include_router(stitch_router)
    app.include_router(subtitles_router)
    app.include_router(audio_router)
    app.include_router(orchestrate_router)
    app.include_router(tiktok_router)

    return app


app = create_app()
