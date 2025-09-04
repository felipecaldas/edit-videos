from fastapi import FastAPI

from videomerge.routers.merge import router as merge_router
from videomerge.routers.stitch import router as stitch_router
from videomerge.routers.subtitles import router as subtitles_router
from videomerge.routers.health import router as health_router
from videomerge.routers.audio import router as audio_router
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Video Audio Merger")

    # Routers
    app.include_router(health_router)
    app.include_router(merge_router)
    app.include_router(stitch_router)
    app.include_router(subtitles_router)
    app.include_router(audio_router)

    logger.info("Application startup complete. Routers registered.")
    return app


app = create_app()
