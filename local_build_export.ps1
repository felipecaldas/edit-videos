Param(
  [string]$ImageName = "edit-video",
  [string]$ImageTag = "local",
  [string]$Tarball = "edit-video-image.tar"
)

Write-Host "Building image $ImageName:$ImageTag..."
docker build -t "$ImageName`:$ImageTag" .

Write-Host "Saving image to $Tarball..."
docker save -o "$Tarball" "$ImageName`:$ImageTag"

Write-Host "Done. Upload $Tarball to your Runpod machine."
