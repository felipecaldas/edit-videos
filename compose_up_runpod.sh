#!/usr/bin/env bash
set -euo pipefail

# Bring up the full stack
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting services..."
sudo docker compose up -d

echo "Services started. View logs with:\n  docker compose logs -f"
