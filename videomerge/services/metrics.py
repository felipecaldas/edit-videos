"""
Prometheus metrics for the AI Video Generator service.

This module defines all metrics as specified in TODO.md for observability
across the video generation pipeline: voiceover, image generation, queue/worker,
and external API calls.
"""
import os
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    ProcessCollector,
    GCCollector,
    PlatformCollector
)
from fastapi import Response
from videomerge.config import RUN_ENV

# Create a custom registry to avoid conflicts with other Prometheus clients
registry = CollectorRegistry()

# Add default Python collectors
ProcessCollector(registry=registry)
GCCollector(registry=registry)
PlatformCollector(registry=registry)

# Voiceover metrics
voiceover_generation_seconds = Histogram(
    'voiceover_generation_seconds',
    'Time spent generating voiceover audio',
    buckets=[1, 2, 5, 10, 20, 40, 60, 120],
    registry=registry
)

voiceover_failures_total = Counter(
    'voiceover_failures_total',
    'Total number of voiceover generation failures',
    labelnames=['reason'],
    registry=registry
)

# Image Generation metrics (ComfyUI)
image_generation_seconds = Histogram(
    'image_generation_seconds',
    'Time spent per image generation',
    labelnames=['step', 'workflow'],
    buckets=[10, 20, 40, 60, 120, 300, 600, 1200],
    registry=registry
)

image_generation_failures_total = Counter(
    'image_generation_failures_total',
    'Total number of image generation failures',
    labelnames=['reason', 'workflow'],
    registry=registry
)

total_images_generation_seconds = Histogram(
    'total_images_generation_seconds',
    'Total time spent generating all images for a job',
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
    registry=registry
)

images_generated_total = Counter(
    'images_generated_total',
    'Total number of images successfully generated',
    labelnames=['workflow'],
    registry=registry
)

# Video Generation metrics (ComfyUI I2V)
video_generation_seconds = Histogram(
    'video_generation_seconds',
    'Time spent per video generation',
    labelnames=['workflow'],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
    registry=registry
)

total_videos_generation_seconds = Histogram(
    'total_videos_generation_seconds',
    'Total time spent generating all videos for a job',
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
    registry=registry
)

videos_generated_total = Counter(
    'videos_generated_total',
    'Total number of videos successfully generated',
    labelnames=['workflow'],
    registry=registry
)

# Stitching and Subtitles metrics
stitch_seconds = Histogram(
    'stitch_seconds',
    'Time spent stitching videos together',
    buckets=[1, 5, 10, 30, 60, 120, 300],
    registry=registry
)

subtitles_seconds = Histogram(
    'subtitles_seconds',
    'Time spent generating and burning subtitles',
    buckets=[1, 5, 10, 30, 60, 120, 300],
    registry=registry
)


jobs_enqueued_total = Counter(
    'jobs_enqueued_total',
    'Total number of jobs enqueued',
    registry=registry
)

jobs_started_total = Counter(
    'jobs_started_total',
    'Total number of jobs started processing',
    registry=registry
)

jobs_completed_total = Counter(
    'jobs_completed_total',
    'Total number of jobs completed successfully',
    registry=registry
)

jobs_failed_total = Counter(
    'jobs_failed_total',
    'Total number of jobs that failed',
    labelnames=['reason'],
    registry=registry
)

job_total_seconds = Histogram(
    'job_total_seconds',
    'Total time spent processing a job',
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
    registry=registry
)

worker_active = Gauge(
    'worker_active',
    'Whether the worker is currently active (1) or idle (0)',
    registry=registry
)

# External API metrics (ComfyUI)
comfyui_requests_total = Counter(
    'comfyui_requests_total',
    'Total number of HTTP requests to ComfyUI',
    labelnames=['endpoint', 'status'],
    registry=registry
)

comfyui_request_seconds = Histogram(
    'comfyui_request_seconds',
    'Time spent on HTTP requests to ComfyUI',
    labelnames=['endpoint'],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
    registry=registry
)


# Environment label for all metrics
def add_environment_labels(func):
    """Decorator to add environment label to metrics"""
    def wrapper(*args, **kwargs):
        # Add environment label if not already present
        if not hasattr(func, '_environment_added'):
            func._environment_added = True
        return func(*args, **kwargs)
    return wrapper


def get_metrics_response() -> Response:
    """Generate Prometheus metrics response"""
    data = generate_latest(registry)
    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
        headers={"Cache-Control": "no-cache"}
    )
