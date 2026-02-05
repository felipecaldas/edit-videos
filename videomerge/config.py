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


def _load_comfyui_defaults() -> tuple[str, bool, int, float, str, str | None, str | None, int, int, int]:
    """Load ComfyUI-related configuration values from the environment."""
    comfyui_url = os.getenv("COMFYUI_URL", "http://192.168.68.51:8188")
    enable_image_gen = _str_to_bool(os.getenv("ENABLE_IMAGE_GEN"), "true")
    timeout_seconds = int(os.getenv("COMFYUI_TIMEOUT_SECONDS", str(20 * 60)))
    poll_interval = float(os.getenv("COMFYUI_POLL_INTERVAL_SECONDS", "3"))
    run_env = os.getenv("RUN_ENV", "local").lower()
    image_instance_id = os.getenv("RUNPOD_IMAGE_INSTANCE_ID")
    video_instance_id = os.getenv("RUNPOD_VIDEO_INSTANCE_ID")
    image_width = int(os.getenv("IMAGE_WIDTH", "480"))
    image_height = int(os.getenv("IMAGE_HEIGHT", "480"))
    upscale_batch_size = int(os.getenv("UPSCALE_BATCH_SIZE", "21"))
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
        upscale_batch_size,
    )


def _load_misc_defaults() -> tuple[
    str,
    str | None,
    str | None,
    Path,
    str,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    float,
    int,
    float,
    int,
    float,
]:
    """Load miscellaneous configuration values from the environment."""
    voiceover_url = os.getenv("VOICEOVER_SERVICE_URL", "http://192.168.68.51:8083")
    voiceover_webhook_url = os.getenv("N8N_VOICEOVER_WEBHOOK_URL")
    voiceover_api_key = os.getenv("VOICEOVER_API_KEY")
    subtitle_path = Path(os.getenv("SUBTITLE_CONFIG_PATH", "subtitle_config.json"))
    temporal_url = os.getenv("TEMPORAL_SERVER_URL", "localhost:7233")
    generate_scenes_timeout_minutes = int(os.getenv("GENERATE_SCENES_TIMEOUT_MINUTES", "5"))
    default_activity_timeout_minutes = int(os.getenv("DEFAULT_ACTIVITY_TIMEOUT_MINUTES", "15"))
    stitch_timeout_minutes = int(os.getenv("STITCH_TIMEOUT_MINUTES", "7"))
    subtitles_timeout_minutes = int(os.getenv("SUBTITLES_TIMEOUT_MINUTES", "5"))
    n8n_webhook_timeout_seconds = int(os.getenv("N8N_WEBHOOK_TIMEOUT_SECONDS", "300"))
    setup_run_directory_timeout_seconds = int(os.getenv("SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS", "5"))
    activity_short_timeout_minutes = int(os.getenv("ACTIVITY_SHORT_TIMEOUT_MINUTES", "5"))

    temporal_image_generation_timeout_minutes = int(
        os.getenv("TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES", "15")
    )
    temporal_video_generation_timeout_minutes = int(
        os.getenv("TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES", "15")
    )
    temporal_upscale_generation_timeout_minutes = int(
        os.getenv("TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES", "30")
    )

    runpod_image_http_timeout_seconds = int(os.getenv("RUNPOD_IMAGE_HTTP_TIMEOUT_SECONDS", "30"))
    runpod_video_http_timeout_seconds = int(os.getenv("RUNPOD_VIDEO_HTTP_TIMEOUT_SECONDS", "30"))
    runpod_video_output_http_timeout_seconds = int(
        os.getenv("RUNPOD_VIDEO_OUTPUT_HTTP_TIMEOUT_SECONDS", "120")
    )
    runpod_upscale_http_timeout_seconds = int(os.getenv("RUNPOD_UPSCALE_HTTP_TIMEOUT_SECONDS", "30"))

    image_job_timeout_seconds = int(os.getenv("IMAGE_JOB_TIMEOUT_SECONDS", "600"))
    image_poll_interval_seconds = float(os.getenv("IMAGE_POLL_INTERVAL_SECONDS", "5"))
    video_job_timeout_seconds = int(os.getenv("VIDEO_JOB_TIMEOUT_SECONDS", "600"))
    video_poll_interval_seconds = float(os.getenv("VIDEO_POLL_INTERVAL_SECONDS", "5"))
    upscale_job_timeout_seconds = int(os.getenv("UPSCALE_JOB_TIMEOUT_SECONDS", "1800"))
    upscale_poll_interval_seconds = float(os.getenv("UPSCALE_POLL_INTERVAL_SECONDS", "5"))
    return (
        voiceover_url,
        voiceover_webhook_url,
        voiceover_api_key,
        subtitle_path,
        temporal_url,
        generate_scenes_timeout_minutes,
        default_activity_timeout_minutes,
        stitch_timeout_minutes,
        subtitles_timeout_minutes,
        n8n_webhook_timeout_seconds,
        setup_run_directory_timeout_seconds,
        activity_short_timeout_minutes,
        temporal_image_generation_timeout_minutes,
        temporal_video_generation_timeout_minutes,
        temporal_upscale_generation_timeout_minutes,
        runpod_image_http_timeout_seconds,
        runpod_video_http_timeout_seconds,
        runpod_video_output_http_timeout_seconds,
        runpod_upscale_http_timeout_seconds,
        image_job_timeout_seconds,
        image_poll_interval_seconds,
        video_job_timeout_seconds,
        video_poll_interval_seconds,
        upscale_job_timeout_seconds,
        upscale_poll_interval_seconds,
    )


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


def _load_notifications_defaults() -> tuple[str, str | None, str | None]:
    """Load webhook configuration values from the environment."""
    n8n_webhook = os.getenv(
        "VIDEO_COMPLETED_N8N_WEBHOOK_URL",
        "https://your-n8n-instance.com/webhook/job-complete",
    )
    prompts_webhook_url = os.getenv("N8N_PROMPTS_WEBHOOK_URL")
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    return n8n_webhook, prompts_webhook_url, webhook_secret


def _apply_config() -> None:
    """Populate module-level constants from current environment variables."""
    global TMP_BASE, DATA_SHARED_BASE, TIKTOK_VIDEOS_ARCHIVE_FOLDER
    TMP_BASE, DATA_SHARED_BASE, TIKTOK_VIDEOS_ARCHIVE_FOLDER = _load_paths()

    global VOICEOVER_SERVICE_URL, N8N_VOICEOVER_WEBHOOK_URL, VOICEOVER_API_KEY, SUBTITLE_CONFIG_PATH, TEMPORAL_SERVER_URL
    global GENERATE_SCENES_TIMEOUT_MINUTES, DEFAULT_ACTIVITY_TIMEOUT_MINUTES, STITCH_TIMEOUT_MINUTES
    global SUBTITLES_TIMEOUT_MINUTES, N8N_WEBHOOK_TIMEOUT_SECONDS, SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS
    global ACTIVITY_SHORT_TIMEOUT_MINUTES
    global TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES, TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES
    global TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES
    global RUNPOD_IMAGE_HTTP_TIMEOUT_SECONDS, RUNPOD_VIDEO_HTTP_TIMEOUT_SECONDS
    global RUNPOD_VIDEO_OUTPUT_HTTP_TIMEOUT_SECONDS, RUNPOD_UPSCALE_HTTP_TIMEOUT_SECONDS
    global IMAGE_JOB_TIMEOUT_SECONDS, IMAGE_POLL_INTERVAL_SECONDS
    global VIDEO_JOB_TIMEOUT_SECONDS, VIDEO_POLL_INTERVAL_SECONDS
    global UPSCALE_JOB_TIMEOUT_SECONDS, UPSCALE_POLL_INTERVAL_SECONDS
    (
        VOICEOVER_SERVICE_URL,
        N8N_VOICEOVER_WEBHOOK_URL,
        VOICEOVER_API_KEY,
        SUBTITLE_CONFIG_PATH,
        TEMPORAL_SERVER_URL,
        GENERATE_SCENES_TIMEOUT_MINUTES,
        DEFAULT_ACTIVITY_TIMEOUT_MINUTES,
        STITCH_TIMEOUT_MINUTES,
        SUBTITLES_TIMEOUT_MINUTES,
        N8N_WEBHOOK_TIMEOUT_SECONDS,
        SETUP_RUN_DIRECTORY_TIMEOUT_SECONDS,
        ACTIVITY_SHORT_TIMEOUT_MINUTES,
        TEMPORAL_IMAGE_GENERATION_TIMEOUT_MINUTES,
        TEMPORAL_VIDEO_GENERATION_TIMEOUT_MINUTES,
        TEMPORAL_UPSCALE_GENERATION_TIMEOUT_MINUTES,
        RUNPOD_IMAGE_HTTP_TIMEOUT_SECONDS,
        RUNPOD_VIDEO_HTTP_TIMEOUT_SECONDS,
        RUNPOD_VIDEO_OUTPUT_HTTP_TIMEOUT_SECONDS,
        RUNPOD_UPSCALE_HTTP_TIMEOUT_SECONDS,
        IMAGE_JOB_TIMEOUT_SECONDS,
        IMAGE_POLL_INTERVAL_SECONDS,
        VIDEO_JOB_TIMEOUT_SECONDS,
        VIDEO_POLL_INTERVAL_SECONDS,
        UPSCALE_JOB_TIMEOUT_SECONDS,
        UPSCALE_POLL_INTERVAL_SECONDS,
    ) = _load_misc_defaults()

    global ENABLE_VOICEOVER_GEN
    ENABLE_VOICEOVER_GEN = _str_to_bool(os.getenv("ENABLE_VOICEOVER_GEN"), "true")

    global COMFYUI_URL, ENABLE_IMAGE_GEN, COMFYUI_TIMEOUT_SECONDS, COMFYUI_POLL_INTERVAL_SECONDS
    global RUN_ENV, RUNPOD_IMAGE_INSTANCE_ID, RUNPOD_VIDEO_INSTANCE_ID
    global IMAGE_WIDTH, IMAGE_HEIGHT, UPSCALE_BATCH_SIZE
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
        UPSCALE_BATCH_SIZE,
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

    global VIDEO_COMPLETED_N8N_WEBHOOK_URL, N8N_PROMPTS_WEBHOOK_URL, WEBHOOK_SECRET
    (
        VIDEO_COMPLETED_N8N_WEBHOOK_URL,
        N8N_PROMPTS_WEBHOOK_URL,
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
