# Prometheus & Grafana Setup for Video Generation Pipeline

This directory contains a complete Prometheus and Grafana monitoring stack for the AI Video Generation service.

## Overview

- **Prometheus**: Collects metrics from the video generation pipeline
- **Grafana**: Visualizes metrics with pre-configured dashboards
- **Automatic Setup**: Provisioned datasources and dashboards

## Quick Start

### 1. Prerequisites

Make sure your video-merger container is running and exposing metrics on port 8000:

```powershell
# In your main project directory
docker-compose up -d
```

### 2. Start Monitoring Stack

```powershell
# In this prometheus/ directory
docker-compose up -d
```

### 3. Access Dashboards

- **Grafana**: http://localhost:9010 (admin/admin)
- **Prometheus**: http://localhost:9020

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Video Merger  │────│   Prometheus    │────│   Grafana       │
│   Container     │    │   Container     │    │   Container     │
│                 │    │                 │    │                 │
│ • /metrics      │◄───┤ • Scrapes       │────┤ • Visualizes    │
│ • Job metrics   │    │   metrics       │    │   dashboards    │
│ • Performance   │    │ • Stores TSDB   │    │ • Alerts        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Services

### Prometheus (port 9020)
- Scrapes metrics from `video-merger:8000/metrics` every 30 seconds
- Stores time-series data with 200h retention
- Web UI for querying metrics

### Grafana (port 9010)
- Pre-configured with Prometheus data source
- Auto-imported dashboard with key metrics
- Default credentials: **admin/admin**

## Metrics Collected

### Job Lifecycle
- `jobs_enqueued_total` - Total jobs submitted
- `jobs_started_total` - Jobs that began processing
- `jobs_completed_total` - Successfully completed jobs
- `jobs_failed_total` - Failed jobs (with reason labels)
- `job_total_seconds` - Total job processing time (histogram)

### Queue & Worker Status
- `queue_depth` - Current number of queued jobs
- `worker_active` - Worker status (0=idle, 1=active)

### Performance Metrics
- `voiceover_generation_seconds` - Voice synthesis time
- `image_generation_seconds` - Per-image generation time
- `video_generation_seconds` - Per-video generation time
- `total_images_generation_seconds` - Total time for all images
- `total_videos_generation_seconds` - Total time for all videos

### Processing Steps
- `stitch_seconds` - Video stitching time
- `subtitles_seconds` - Subtitle generation time

### External API (ComfyUI)
- `comfyui_requests_total` - HTTP request count by status
- `comfyui_request_seconds` - Request latency by endpoint

## Grafana Dashboard

The included dashboard provides:

### Overview Panel
- Job throughput (enqueued vs completed rates)
- Success rate percentage
- Queue depth and worker status

### Performance Panels
- P95 latencies for all major operations
- Generation rates for images and videos
- ComfyUI API performance

### Trend Analysis
- Queue depth over time
- Job status breakdown (pie chart)

## Configuration Files

- `prometheus.yml` - Prometheus scraping configuration
- `docker-compose.yml` - Complete stack definition
- `grafana-dashboard.json` - Pre-built dashboard
- `grafana/provisioning/` - Auto-configuration for datasources and dashboards

## Docker Network Setup

The setup uses two Docker networks:

1. **`monitoring`** - Internal network for Prometheus ↔ Grafana communication
2. **`tabario`** - External network connecting to your video-merger container

Make sure your video-merger container is on the `tabario` network:

```yaml
# In your main docker-compose.yml
networks:
  tabario:  # This network name must match
    driver: bridge

services:
  video-merger:
    networks:
      - tabario
```

## Customization

### Adding Alert Rules

Create `alert.rules.yml` and mount it:

```yaml
# In docker-compose.yml
volumes:
  - ./alert.rules.yml:/etc/prometheus/alert.rules.yml:ro
```

### Custom Dashboards

Add more dashboard JSON files to `./grafana/dashboards/` and they'll be auto-imported.

### Multiple Workers

For multiple worker processes, set:
```powershell
$env:PROMETHEUS_MULTIPROC_DIR="/tmp/prometheus-multiproc"
```

## Troubleshooting

### "Connection refused" errors
- Ensure video-merger container is running and on the correct network
- Check that metrics endpoint is accessible: `curl.exe http://video-merger:8000/metrics`

### No data in Grafana
- Verify Prometheus is scraping: Check http://localhost:9020/targets
- Confirm metrics are being generated: Check http://localhost:9020/graph

### Dashboard not loading
- Check Grafana logs: `docker compose logs grafana`
- Verify dashboard JSON is valid

## Security Notes

⚠️ **Change default credentials in production:**
```yaml
environment:
  - GF_SECURITY_ADMIN_PASSWORD=your_secure_password
  - GF_USERS_ALLOW_SIGN_UP=false
```

## Moving to New Project

This entire `./prometheus/` directory is self-contained and can be copied to any new project that needs the same monitoring setup.

## Support

For issues with the monitoring stack:
1. Check container logs: `docker compose logs`
2. Verify network connectivity
3. Test metrics endpoint directly
4. Check Prometheus targets page
