from fastapi import FastAPI
from contextlib import asynccontextmanager

from videomerge.routers.merge import router as merge_router
from videomerge.routers.stitch import router as stitch_router
from videomerge.routers.subtitles import router as subtitles_router
from videomerge.routers.health import router as health_router
from videomerge.routers.audio import router as audio_router
from videomerge.routers.orchestrate import router as orchestrate_router
from videomerge.utils.logging import get_logger
from videomerge.services.worker import Worker
from videomerge.services.redis_client import close_redis

logger = get_logger(__name__)


def create_app() -> FastAPI:
    worker = Worker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        await worker.start()
        logger.info("Application startup complete. Routers registered and worker started.")
        try:
            yield
        finally:
            # Shutdown
            await worker.stop()
            await close_redis()
            logger.info("Application shutdown complete. Worker stopped and Redis closed.")

    app = FastAPI(title="AI Video Generator", lifespan=lifespan)

    # Routers
    app.include_router(health_router)
    app.include_router(merge_router)
    app.include_router(stitch_router)
    app.include_router(subtitles_router)
    app.include_router(audio_router)
    app.include_router(orchestrate_router)

    return app


app = create_app()
