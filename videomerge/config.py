from pathlib import Path
import os
from typing import Optional, Dict
from dotenv import load_dotenv
import yaml


def _str_to_bool(value: str | None, default: str) -> bool:
    """Convert an environment variable string to a boolean value."""
    normalized = (value or default).lower()
    return normalized in {"1", "true", "yes", "on"}


_BASE_DIR = Path(__file__).parent.parent
_ENV_PATH = _BASE_DIR / ".env"
_LAST_ENV_MTIME: Optional[float] = None


def _load_paths() -> tuple[Path, Path, Path]:
    """Load path-based configuration values from the environment."""
    tmp_base = Path(os.getenv("TMP_BASE", "/tmp/media"))
    data_shared_base = Path(os.getenv("DATA_SHARED_BASE", "/data/shared"))
    archive_folder = Path(os.getenv("TIKTOK_VIDEOS_ARCHIVE_FOLDER", "/data/shared/archived"))
    return tmp_base, data_shared_base, archive_folder


def _load_comfyui_defaults() -> tuple[str, bool, int, float, str, str | None, str | None, int, int]:
    """Load ComfyUI-related configuration values from the environment."""
    comfyui_url = os.getenv("COMFYUI_URL", "http://192.168.68.51:8188")
    enable_image_gen = _str_to_bool(os.getenv("ENABLE_IMAGE_GEN"), "true")
    timeout_seconds = int(os.getenv("COMFYUI_TIMEOUT_SECONDS", str(20 * 60)))
    poll_interval = float(os.getenv("COMFYUI_POLL_INTERVAL_SECONDS", "2"))
    run_env = os.getenv("RUN_ENV", "local").lower()
    image_instance_id = os.getenv("RUNPOD_IMAGE_INSTANCE_ID")
    video_instance_id = os.getenv("RUNPOD_VIDEO_INSTANCE_ID")
    image_width = int(os.getenv("IMAGE_WIDTH", "480"))
    image_height = int(os.getenv("IMAGE_HEIGHT", "480"))
    return (
        comfyui_url,
        enable_image_gen,
        timeout_seconds,
        poll_interval,
        run_env,
        image_instance_id,
        video_instance_id,
        image_width,
        image_height,
    )


def _load_misc_defaults() -> tuple[str, str | None, Path, str]:
    """Load miscellaneous configuration values from the environment."""
    voiceover_url = os.getenv("VOICEOVER_SERVICE_URL", "http://192.168.68.51:8083")
    voiceover_api_key = os.getenv("VOICEOVER_API_KEY")
    subtitle_path = Path(os.getenv("SUBTITLE_CONFIG_PATH", "subtitle_config.json"))
    temporal_url = os.getenv("TEMPORAL_SERVER_URL", "localhost:7233")
    return voiceover_url, voiceover_api_key, subtitle_path, temporal_url


def _load_image_style_mapping() -> Dict[str, str]:
    """Load image style to ComfyUI workflow name mapping from YAML."""
    mapping_path = Path(__file__).parent / "image_style_mapping.yaml"
    try:
        with mapping_path.open("r", encoding="utf-8") as f:
            mapping = yaml.safe_load(f)
            if not isinstance(mapping, dict):
                raise ValueError("Image style mapping must be a dictionary")
            return mapping
    except FileNotFoundError:
        # Fallback to hardcoded defaults if YAML file is missing
        return {
            "cinematic": "image_qwen_t2i",
            "disney": "image_disneyizt_t2i",
            "crayon-drawing": "crayon-drawing",
            "anime": "T2I_ChromaAnimaAIO",
        }
    except Exception as e:
        raise RuntimeError(f"Failed to load image style mapping: {e}")


def _load_workflow_config(run_env: str) -> tuple[dict[str, str], Path, str, Path, str]:
    """Load workflow-related configuration values from the environment."""

    def _base_workflows() -> dict[str, str]:
        defaults = {
            "crayon_drawing": "crayon-drawing.json",
            "anime": "T2I_ChromaAnimaAIO.json",
        }

        defaults["default"] = (
            "runpod-t2i-fluxdev.json" if run_env == "runpod" else "qwen-image-fast-local.json"
        )
        return defaults

    workflows = _base_workflows()
    workflows_base_path = Path("videomerge/comfyui-workflows")
    default_i2v_workflow = (
        "I2V-Wan-2.2-Lightning-runpod.json" if run_env == "runpod" else "I2V-Wan-2.2-Lightning-local.json"
    )
    workflow_i2v_path = Path(
        os.getenv(
            "WORKFLOW_I2V_PATH",
            f"videomerge/comfyui-workflows/{default_i2v_workflow}",
        )
    )
    
    # Default I2V workflow name for RunPod API
    default_i2v_workflow_name = "video_wan2_2_14B_i2v"

    return workflows, workflows_base_path, default_i2v_workflow, workflow_i2v_path, default_i2v_workflow_name


def _load_notifications_defaults() -> tuple[str, str | None]:
    """Load webhook configuration values from the environment."""
    n8n_webhook = os.getenv(
        "VIDEO_COMPLETED_N8N_WEBHOOK_URL",
        "https://your-n8n-instance.com/webhook/job-complete",
    )
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    return n8n_webhook, webhook_secret


def _apply_config() -> None:
    """Populate module-level constants from current environment variables."""
    global TMP_BASE, DATA_SHARED_BASE, TIKTOK_VIDEOS_ARCHIVE_FOLDER
    TMP_BASE, DATA_SHARED_BASE, TIKTOK_VIDEOS_ARCHIVE_FOLDER = _load_paths()

    global VOICEOVER_SERVICE_URL, VOICEOVER_API_KEY, SUBTITLE_CONFIG_PATH, TEMPORAL_SERVER_URL
    (
        VOICEOVER_SERVICE_URL,
        VOICEOVER_API_KEY,
        SUBTITLE_CONFIG_PATH,
        TEMPORAL_SERVER_URL,
    ) = _load_misc_defaults()

    global ENABLE_VOICEOVER_GEN
    ENABLE_VOICEOVER_GEN = _str_to_bool(os.getenv("ENABLE_VOICEOVER_GEN"), "true")

    global COMFYUI_URL, ENABLE_IMAGE_GEN, COMFYUI_TIMEOUT_SECONDS, COMFYUI_POLL_INTERVAL_SECONDS
    global RUN_ENV, RUNPOD_IMAGE_INSTANCE_ID, RUNPOD_VIDEO_INSTANCE_ID
    global IMAGE_WIDTH, IMAGE_HEIGHT
    (
        COMFYUI_URL,
        ENABLE_IMAGE_GEN,
        COMFYUI_TIMEOUT_SECONDS,
        COMFYUI_POLL_INTERVAL_SECONDS,
        RUN_ENV,
        RUNPOD_IMAGE_INSTANCE_ID,
        RUNPOD_VIDEO_INSTANCE_ID,
        IMAGE_WIDTH,
        IMAGE_HEIGHT,
    ) = _load_comfyui_defaults()

    global RUNPOD_API_KEY, COMFY_ORG_API_KEY, RUNPOD_BASE_URL
    RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
    RUNPOD_BASE_URL = os.getenv("RUNPOD_BASE_URL", "https://api.runpod.ai")
    COMFY_ORG_API_KEY = os.getenv(
        "COMFY_ORG_API_KEY",
        "comfyui-67e0362fbb7d9989c297e9d6d0b7e3ea0a08214897b4a0be25146e16ec22ea4f",
    )

    global IMAGE_WORKFLOWS, WORKFLOWS_BASE_PATH, DEFAULT_I2V_WORKFLOW, WORKFLOW_I2V_PATH, DEFAULT_I2V_WORKFLOW_NAME
    (
        IMAGE_WORKFLOWS,
        WORKFLOWS_BASE_PATH,
        DEFAULT_I2V_WORKFLOW,
        WORKFLOW_I2V_PATH,
        DEFAULT_I2V_WORKFLOW_NAME,
    ) = _load_workflow_config(RUN_ENV)

    global IMAGE_STYLE_TO_WORKFLOW_MAPPING
    IMAGE_STYLE_TO_WORKFLOW_MAPPING = _load_image_style_mapping()

    global VIDEO_COMPLETED_N8N_WEBHOOK_URL, WEBHOOK_SECRET
    (
        VIDEO_COMPLETED_N8N_WEBHOOK_URL,
        WEBHOOK_SECRET,
    ) = _load_notifications_defaults()


def _load_env() -> None:
    """Load environment variables from the .env file if present."""
    global _LAST_ENV_MTIME

    try:
        if _ENV_PATH.exists():
            load_dotenv(dotenv_path=_ENV_PATH, override=True)
            _LAST_ENV_MTIME = _ENV_PATH.stat().st_mtime
            return
    except OSError:
        # If the workflow sandbox restricts filesystem access we fall back to defaults
        pass

    load_dotenv(override=True)
    _LAST_ENV_MTIME = None


def reload_config() -> None:
    """Reload environment variables and refresh module-level configuration constants."""
    _load_env()
    _apply_config()


def ensure_config_current() -> None:
    """Ensure in-memory configuration matches the .env file on disk."""
    try:
        if not _ENV_PATH.exists():
            return

        current_mtime = _ENV_PATH.stat().st_mtime
    except OSError:
        return

    if _LAST_ENV_MTIME is None or current_mtime > _LAST_ENV_MTIME:
        reload_config()


_load_env()
_apply_config()
