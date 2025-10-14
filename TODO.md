# Metrics to Time-Series Backend

This document outlines the plan to push application metrics to a time-series backend for observability across orchestration steps (voiceover, image generation, queue/worker).

## Recommended Stack
- Prometheus (scrape) + Grafana for visualization and alerting.
- Optional: OpenTelemetry (OTel) metrics with OTLP exporter to an OTel Collector, then Prometheus/Grafana or a vendor backend.

## Key Metrics
- Voiceover
  - Histogram: `voiceover_generation_seconds`
  - Counter: `voiceover_failures_total`
- Image Generation (ComfyUI)
  - Histogram: `image_generation_seconds` (labels: `step=text2image`, `workflow=name`)
  - Counter: `image_generation_failures_total` (labels: `reason=timeout|error`)
  - Histogram: `total_images_generation_seconds`
  - Counter: `images_generated_total`
- Queue/Worker (Redis)
  - Gauge: `queue_depth` (LLEN of `video_orchestrator:queue`)
  - Counter: `jobs_enqueued_total`, `jobs_started_total`, `jobs_completed_total`, `jobs_failed_total`
  - Histogram: `job_total_seconds`
  - Gauge: `worker_active` (0/1)
- External Calls
  - Counter: `comfyui_requests_total` (labels: `endpoint=/prompt|/history`, `status=2xx|4xx|5xx`)
  - Histogram: `comfyui_request_seconds`
  - Counter: `redis_errors_total`

## Labeling Guidelines
- Avoid high-cardinality labels. Do NOT include `run_id`, `job_id`, or filenames in labels.
- Safe labels include: `step`, `workflow/model`, `status` (success|failure), `reason` (timeout|error).

## Instrumentation Points
- `videomerge/services/worker.py`
  - Observe histograms and increment counters around:
    - `synthesize_voice()` timing and errors
    - Per-image generation (submit + poll) timing and errors
    - Total images loop timing
    - Job start/completion/failure and total job time
- `videomerge/services/comfyui.py`
  - Wrap HTTP requests to `/prompt` and `/history` to record counters and latencies.
- `videomerge/services/queue.py`
  - Increment `jobs_enqueued_total` when enqueueing.
- Queue depth sampling task
  - Periodically (e.g., every 5–15s), `LLEN video_orchestrator:queue` and set `queue_depth` gauge.

## Export Method
- Prometheus scrape preferred:
  - Add a `/metrics` endpoint using the Prometheus Python client.
  - Configure Prometheus to scrape `video-merger` at `:8000/metrics`.
- Alternative (if needed):
  - Pushgateway (not ideal for long-lived workers) or OTel Collector with OTLP.

## Buckets (initial proposal)
- `voiceover_generation_seconds`: [1, 2, 5, 10, 20, 40, 60, 120]
- `image_generation_seconds`: [10, 20, 40, 60, 120, 300, 600, 1200]
- `job_total_seconds`: [10, 30, 60, 120, 300, 600, 1200, 3600]

## Dashboard (Grafana) Ideas
- Latency percentiles (P50/P95/P99) for voiceover, per-image, job total.
- Throughput (rate): jobs enqueued vs completed.
- Reliability: job failures, ComfyUI HTTP errors.
- Capacity: queue depth over time; worker active status.

## Alerting Suggestions
- Queue depth > N for >10 minutes.
- Image generation P95 > 15 minutes.
- Job failure rate > X% over 15 minutes.
- Worker inactive or container restarts spike.

## Config & Deployment
- Environment flags (optional):
  - `ENABLE_METRICS=true`
  - `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc` (if multiple workers/processes)
- Docker compose updates:
  - Expose `/metrics` on the same app port (8000).
  - Add Prometheus service if needed, or configure external Prometheus.

## Implementation Tasks
- [ ] Add metrics module (`videomerge/services/metrics.py`) and initialize Prometheus client.
- [ ] Expose `/metrics` endpoint (e.g., `prometheus_client.make_asgi_app()` or FastAPI middleware/route).
- [ ] Define histograms/counters/gauges per the Key Metrics.
- [ ] Instrument worker steps (voiceover, per-image, totals, job lifecycle).
- [ ] Instrument ComfyUI HTTP client.
- [ ] Add background task to sample Redis `LLEN` for `queue_depth`.
- [ ] Create Grafana dashboard (JSON) with panels for key metrics.
- [ ] Add alert rules (Prometheus alertmanager or Grafana alerts).

# Service Discovery for ComfyUI URL

This task outlines the plan to dynamically manage the ComfyUI URL to avoid manual updates and service restarts.

## Implementation Tasks

- [ ] **Prerequisite**: Expose the Redis server to be accessible by both the `video-merger` service and the ComfyUI pod.
- [ ] **ComfyUI Startup Script**: Create a script that runs when the ComfyUI pod starts. This script will:
  - Get the pod's unique, dynamic URL.
  - Write this URL to a specific key in Redis (e.g., `SET current_comfyui_url "<the-dynamic-url>"`).
- [ ] **Refactor `video-merger`**: Modify the application logic in `videomerge/config.py` or `videomerge/services/comfyui.py` to:
  - On startup, or on a regular interval, fetch the `current_comfyui_url` value from Redis.
  - Use this fetched URL for all API calls to ComfyUI.
  - Implement a caching strategy (e.g., cache the URL for 60 seconds) to avoid querying Redis on every single request.

## Future Enhancements
- OpenTelemetry traces for cross-step correlation.
- Distinguish timeouts vs other errors in metrics labels.
- Separate queues for priority traffic with additional metrics.
