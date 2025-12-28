#!/bin/bash

# Restart script for video-merger and temporal-worker services
# This script will stop, build, and start the specified services
# If any command fails, the script will exit immediately

set -e  # Exit immediately if any command fails

echo "Stopping video-merger and temporal-worker services..."
sudo docker compose -f docker-compose.yml -f docker-compose.runpod.yml stop video-merger temporal-worker

echo "Building video-merger and temporal-worker services..."
sudo docker compose -f docker-compose.yml -f docker-compose.runpod.yml build video-merger temporal-worker

echo "Starting video-merger and temporal-worker services..."
sudo docker compose -f docker-compose.yml -f docker-compose.runpod.yml up -d video-merger temporal-worker

echo "Services restarted successfully!"
