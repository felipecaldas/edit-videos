#!/usr/bin/env bash
set -euo pipefail

# ==== CONFIG ====
IMAGE_NAME="edit-video"
IMAGE_TAG="local"
TARBALL="edit-video-image.tar"
# ===============

echo "Building image ${IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

echo "Saving image to ${TARBALL}..."
docker save -o "${TARBALL}" "${IMAGE_NAME}:${IMAGE_TAG}"

echo "Done. Upload ${TARBALL} to your Runpod machine (e.g., scp/S3)."
