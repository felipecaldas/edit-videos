#!/usr/bin/env bash
set -euo pipefail

# Bring up local environment using base + local override
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting services (local overrides)..."
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

echo "Services started. View logs with:\n  docker compose logs -f"
