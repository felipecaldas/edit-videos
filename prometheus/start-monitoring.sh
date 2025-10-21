#!/bin/bash

# Prometheus & Grafana Setup Startup Script
# This script helps you quickly start the monitoring stack

Write-Host "🚀 Starting Prometheus & Grafana monitoring stack..." -ForegroundColor Green
Write-Host ""

# Check if docker-compose is available
if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker is required but not installed." -ForegroundColor Red
    Write-Host "Please install Docker Desktop for Windows and try again." -ForegroundColor Yellow
    exit 1
}

# Check if video-merger container is running
$containerRunning = docker ps --filter "name=video-merger" --filter "status=running" | Measure-Object | Select-Object -ExpandProperty Count
if ($containerRunning -eq 0) {
    Write-Host "⚠️  Warning: video-merger container not detected." -ForegroundColor Yellow
    Write-Host "Make sure your main application is running before starting monitoring." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "📊 Starting services..." -ForegroundColor Green
docker compose up -d

Write-Host ""
Write-Host "✅ Monitoring stack started successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "🌐 Access Grafana: http://localhost:9010 (admin/admin)" -ForegroundColor Cyan
Write-Host "🔍 Access Prometheus: http://localhost:9020" -ForegroundColor Cyan
Write-Host ""
Write-Host "📈 Dashboard will auto-import with video generation metrics" -ForegroundColor Green
Write-Host "🔄 Prometheus scrapes video-merger:8000/metrics every 30 seconds" -ForegroundColor Green
Write-Host ""
Write-Host "To view logs: docker compose logs -f" -ForegroundColor Yellow
Write-Host "To stop: docker compose down" -ForegroundColor Yellow
