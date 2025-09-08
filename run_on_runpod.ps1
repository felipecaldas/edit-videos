Param(
  [string]$Tarball = "edit-video-image.tar",
  [string]$ImageName = "edit-video",
  [string]$ImageTag = "local",
  [string]$ContainerName = "edit-video",
  [int]$Port = 8000,
  [string]$DataShared = "/data/shared",
  # Env vars
  [string]$VOICEOVER_SERVICE_URL = "http://...",
  [string]$DATA_SHARED_BASE = "/data/shared",
  [string]$REDIS_URL = "redis://...",
  [string]$COMFYUI_URL = "http://...",
  [string]$ENABLE_IMAGE_GEN = "true",
  [string]$ENABLE_VOICEOVER_GEN = "false",
  [string]$COMFYUI_TIMEOUT_SECONDS = "600",
  [string]$COMFYUI_POLL_INTERVAL_SECONDS = "15",
  [string]$LOG_LEVEL = "DEBUG",
  [string]$UVICORN_LOG_LEVEL = "debug",
  [string]$TZ = "Australia/Melbourne"
)

Write-Host "Loading image from $Tarball..."
docker load -i "$Tarball"

Write-Host "Ensuring $DataShared exists..."
if (!(Test-Path $DataShared)) {
  New-Item -ItemType Directory -Path $DataShared | Out-Null
}

Write-Host "Stopping existing container if running..."
docker rm -f "$ContainerName" | Out-Null 2>&1

Write-Host "Starting container $ContainerName..."
docker run -d --name "$ContainerName" `
  -p $Port`:8000 `
  -v "$DataShared`:/data/shared" `
  -e "VOICEOVER_SERVICE_URL=$VOICEOVER_SERVICE_URL" `
  -e "DATA_SHARED_BASE=$DATA_SHARED_BASE" `
  -e "REDIS_URL=$REDIS_URL" `
  -e "COMFYUI_URL=$COMFYUI_URL" `
  -e "ENABLE_IMAGE_GEN=$ENABLE_IMAGE_GEN" `
  -e "ENABLE_VOICEOVER_GEN=$ENABLE_VOICEOVER_GEN" `
  -e "COMFYUI_TIMEOUT_SECONDS=$COMFYUI_TIMEOUT_SECONDS" `
  -e "COMFYUI_POLL_INTERVAL_SECONDS=$COMFYUI_POLL_INTERVAL_SECONDS" `
  -e "LOG_LEVEL=$LOG_LEVEL" `
  -e "UVICORN_LOG_LEVEL=$UVICORN_LOG_LEVEL" `
  -e "TZ=$TZ" `
  "$ImageName`:$ImageTag" `
  uvicorn videomerge.main:app --host 0.0.0.0 --port 8000

Write-Host "Tailing logs..."
docker logs -f "$ContainerName"
