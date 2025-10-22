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
from videomerge.services.metrics import get_metrics_response

logger = get_logger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logger.info("Application startup complete.")
        yield
        # Shutdown
        logger.info("Application shutdown complete.")

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
