#!/usr/bin/env bash
set -euo pipefail

# Bring up runpod environment using base + runpod override
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting services (runpod overrides)..."
docker compose -f docker-compose.yml -f docker-compose.runpod.yml up -d

echo "Services started. View logs with:\n  docker compose logs -f"
