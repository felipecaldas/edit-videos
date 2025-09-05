from pathlib import Path
import os

# Base temp directory for transient work
TMP_BASE = Path(os.getenv("TMP_BASE", "/tmp/media"))

# Shared data directory where orchestrations persist outputs
DATA_SHARED_BASE = Path(os.getenv("DATA_SHARED_BASE", "/data/shared"))

# Voiceover service endpoint
VOICEOVER_SERVICE_URL = os.getenv("VOICEOVER_SERVICE_URL", "http://192.168.68.51:8083")

# Optional API key for voiceover service
VOICEOVER_API_KEY = os.getenv("VOICEOVER_API_KEY")

# Subtitle configuration path
SUBTITLE_CONFIG_PATH = Path(os.getenv("SUBTITLE_CONFIG_PATH", "subtitle_config.json"))

# Redis connection string (use database 0 by default)
REDIS_URL = os.getenv("REDIS_URL", "redis://192.168.68.51:8061/0")

# ComfyUI configuration
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://192.168.68.51:8188")
ENABLE_IMAGE_GEN = os.getenv("ENABLE_IMAGE_GEN", "true").lower() in {"1", "true", "yes", "on"}
# Allow long-running generations (e.g., 10+ minutes)
COMFYUI_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_TIMEOUT_SECONDS", str(20 * 60)))
COMFYUI_POLL_INTERVAL_SECONDS = float(os.getenv("COMFYUI_POLL_INTERVAL_SECONDS", "2"))
WORKFLOW_IMAGE_PATH = Path(os.getenv(
    "WORKFLOW_IMAGE_PATH",
    str(Path(__file__).resolve().parent / "comfyui-workflows" / "qwen-image-fast.Olivio.json"),
))
