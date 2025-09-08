#!/usr/bin/env bash
set -euo pipefail

# ==== CONFIG ====
TARBALL="edit-video-image.tar"   # the file you uploaded
IMAGE_NAME="edit-video"
IMAGE_TAG="local"
CONTAINER_NAME="edit-video"
PORT=8086
DATA_SHARED="/data/shared"       # Runpod volume or local path inside pod
# Environment values (update as needed)
VOICEOVER_SERVICE_URL="http://..."
DATA_SHARED_BASE="/data/shared"
REDIS_URL="redis://..."
COMFYUI_URL="http://..."
ENABLE_IMAGE_GEN="true"
ENABLE_VOICEOVER_GEN="false"
COMFYUI_TIMEOUT_SECONDS="600"
COMFYUI_POLL_INTERVAL_SECONDS="15"
LOG_LEVEL="DEBUG"
UVICORN_LOG_LEVEL="debug"
TZ="Australia/Melbourne"
# ===============

echo "Loading image from ${TARBALL}..."
docker load -i "${TARBALL}"

echo "Ensuring ${DATA_SHARED} exists..."
mkdir -p "${DATA_SHARED}"

echo "Stopping existing container if running..."
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

echo "Starting container ${CONTAINER_NAME}..."
docker run -d --name "${CONTAINER_NAME}" \
  -p ${PORT}:8000 \
  -v "${DATA_SHARED}:/data/shared" \
  -e VOICEOVER_SERVICE_URL="${VOICEOVER_SERVICE_URL}" \
  -e DATA_SHARED_BASE="${DATA_SHARED_BASE}" \
  -e REDIS_URL="${REDIS_URL}" \
  -e COMFYUI_URL="${COMFYUI_URL}" \
  -e ENABLE_IMAGE_GEN="${ENABLE_IMAGE_GEN}" \
  -e ENABLE_VOICEOVER_GEN="${ENABLE_VOICEOVER_GEN}" \
  -e COMFYUI_TIMEOUT_SECONDS="${COMFYUI_TIMEOUT_SECONDS}" \
  -e COMFYUI_POLL_INTERVAL_SECONDS="${COMFYUI_POLL_INTERVAL_SECONDS}" \
  -e LOG_LEVEL="${LOG_LEVEL}" \
  -e UVICORN_LOG_LEVEL="${UVICORN_LOG_LEVEL}" \
  -e TZ="${TZ}" \
  "${IMAGE_NAME}:${IMAGE_TAG}" \
  uvicorn videomerge.main:app --host 0.0.0.0 --port 8000

echo "Container started. Logs:"
docker logs -f "${CONTAINER_NAME}"
