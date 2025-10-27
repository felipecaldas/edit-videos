from pathlib import Path
import os

# Base temp directory for transient work
TMP_BASE = Path(os.getenv("TMP_BASE", "/tmp/media"))

# Shared data directory where orchestrations persist outputs
DATA_SHARED_BASE = Path(os.getenv("DATA_SHARED_BASE", "/data/shared"))

# TikTok videos archive folder
TIKTOK_VIDEOS_ARCHIVE_FOLDER = Path(os.getenv("TIKTOK_VIDEOS_ARCHIVE_FOLDER", "/data/shared/archived"))

# Voiceover service endpoint
VOICEOVER_SERVICE_URL = os.getenv("VOICEOVER_SERVICE_URL", "http://192.168.68.51:8083")

# Optional API key for voiceover service
VOICEOVER_API_KEY = os.getenv("VOICEOVER_API_KEY")
# Toggle voiceover generation inside this service. Default: disabled (handled externally via n8n)
ENABLE_VOICEOVER_GEN = os.getenv("ENABLE_VOICEOVER_GEN", "false").lower() in {"1", "true", "yes", "on"}

# Subtitle configuration path
SUBTITLE_CONFIG_PATH = Path(os.getenv("SUBTITLE_CONFIG_PATH", "subtitle_config.json"))

# Temporal server URL
TEMPORAL_SERVER_URL = os.getenv("TEMPORAL_SERVER_URL", "localhost:7233")

# ComfyUI configuration
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://192.168.68.51:8188")
ENABLE_IMAGE_GEN = os.getenv("ENABLE_IMAGE_GEN", "true").lower() in {"1", "true", "yes", "on"}
# Allow long-running generations (e.g., 10+ minutes)
COMFYUI_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_TIMEOUT_SECONDS", str(20 * 60)))
COMFYUI_POLL_INTERVAL_SECONDS = float(os.getenv("COMFYUI_POLL_INTERVAL_SECONDS", "2"))
# Environment indicator (e.g., "local" or "runpod"). Defaults to local.
RUN_ENV = os.getenv("RUN_ENV", "local").lower()
# RunPod instance IDs for serverless API (required when RUN_ENV=runpod)
RUNPOD_IMAGE_INSTANCE_ID = os.getenv("RUNPOD_IMAGE_INSTANCE_ID")
RUNPOD_VIDEO_INSTANCE_ID = os.getenv("RUNPOD_VIDEO_INSTANCE_ID")

# RunPod API key for serverless authentication (required when RUN_ENV=runpod)
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")

# Mapping of image styles to their corresponding workflow files (environment-aware).
def get_image_workflows():
    base_workflows = {
        "crayon_drawing": "crayon-drawing.json",
        "anime": "T2I_ChromaAnimaAIO.json",
    }
    
    if RUN_ENV == "runpod":
        base_workflows["default"] = "runpod-t2i-fluxdev.json"
    else:
        base_workflows["default"] = "qwen-image-fast-local.json"
    
    return base_workflows

IMAGE_WORKFLOWS = get_image_workflows()

# The base path for the ComfyUI workflow files.
WORKFLOWS_BASE_PATH = "videomerge/comfyui-workflows"

# Image-to-Video workflow template path
DEFAULT_I2V_WORKFLOW = (
    "runpod-i2v-wan22-engui-studio.json" if RUN_ENV == "runpod" else "I2V-Wan-2.2-Lightning-local.json"
)
WORKFLOW_I2V_PATH = Path(os.getenv(
    "WORKFLOW_I2V_PATH",
    f"videomerge/comfyui-workflows/{DEFAULT_I2V_WORKFLOW}",
))

# Webhook configuration for N8N notifications
VIDEO_COMPLETED_N8N_WEBHOOK_URL = os.getenv("VIDEO_COMPLETED_N8N_WEBHOOK_URL", "https://your-n8n-instance.com/webhook/job-complete")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # Optional secret for webhook verification
