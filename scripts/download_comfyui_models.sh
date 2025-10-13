#!/usr/bin/env bash
set -euo pipefail

# Download all models required by the following ComfyUI workflows:
# - videomerge/comfyui-workflows/I2V-Wan 2.2 Lightning.json
# - videomerge/comfyui-workflows/qwen-image-fast.Olivio.json
#
# Usage:
#   ./scripts/download_comfyui_models.sh [COMFYUI_DIR]
#
# If COMFYUI_DIR is not provided, defaults to ./ComfyUI
# Models will be placed under: "$COMFYUI_DIR/models/..."

COMFYUI_DIR=${1:-"./ComfyUI"}
MODELS_DIR="$COMFYUI_DIR/models"


# ------------------------------
# Helpers
# ------------------------------
clone_or_update() {
  # clone_or_update <repo_url> <dest_dir>
  local url="$1"
  local dest="$2"
  if [ -d "$dest/.git" ]; then
    echo "==> Updating repo: $dest"
    git -C "$dest" fetch --all --prune || true
    git -C "$dest" pull --rebase || true
  else
    echo "==> Cloning repo: $url -> $dest"
    git clone --depth 1 "$url" "$dest"
  fi
}

pip_install_req() {
  # pip_install_req <requirements_path>
  local req="$1"
  if [ -f "$req" ]; then
    echo "==> Installing requirements: $req"
    python -s -m pip install --upgrade pip
    python -s -m pip install -r "$req"
  else
    echo "==> Skip requirements (not found): $req"
  fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

download_file() {
  # download_file <url> <out_path>
  local url="$1"
  local out="$2"
  echo "==> Downloading $(basename "$out")"
  echo "    From: $url"
  echo "    To  : $out"
  mkdir -p "$(dirname "$out")"
  if [ -f "$out" ] && [ -s "$out" ]; then
    echo "    Skipping: already exists (non-empty)."
    return 0
  fi

  if have_cmd wget; then
    # Use wget with resume and robust retries
    wget -O "$out" --continue --tries=5 --waitretry=5 --retry-connrefused "$url"
  elif have_cmd curl; then
    # If file exists (partial), resume; otherwise do a normal download
    if [ -f "$out" ] && [ ! -s "$out" ]; then rm -f "$out"; fi
    if [ -f "$out" ]; then
      curl -L --fail --retry 5 --retry-delay 5 -C - -o "$out" "$url"
    else
      curl -L --fail --retry 5 --retry-delay 5 -o "$out" "$url"
    fi
  else
    echo "ERROR: Neither wget nor curl found on PATH. Please install one of them." >&2
    exit 1
  fi

  if [ ! -s "$out" ]; then
    echo "ERROR: Downloaded file is empty: $out" >&2
    exit 1
  fi
}


# ------------------------------
# Download models from list
# ------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
MODELS_LIST_FILE="$SCRIPT_DIR/models_to_download.txt"

if [ ! -f "$MODELS_LIST_FILE" ]; then
  echo "ERROR: Models list not found: $MODELS_LIST_FILE" >&2
  exit 1
fi

# Read the file line by line, skipping comments and empty lines
# and download files.
while IFS= read -r line || [[ -n "$line" ]]; do
  # Trim leading/trailing whitespace
  line=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

  # Skip empty lines and comments
  if [ -z "$line" ] || [[ "$line" == '#'* ]]; then
    continue
  fi

  # Parse URL and destination subdir
  url=$(echo "$line" | cut -d' ' -f1)
  dest_subdir=$(echo "$line" | cut -d' ' -f2-)

  if [ -z "$url" ] || [ -z "$dest_subdir" ]; then
    echo "WARNING: Skipping invalid line: '$line'" >&2
    continue
  fi

  filename=$(basename "$url")
  output_path="$MODELS_DIR/$dest_subdir/$filename"

  download_file "$url" "$output_path"
done < "$MODELS_LIST_FILE"

# ------------------------------
# Custom nodes required by workflows
# ------------------------------
CUSTOM_NODES_DIR="$COMFYUI_DIR/custom_nodes"
mkdir -p "$CUSTOM_NODES_DIR"

# 1) GGUF support (UnetLoaderGGUF, CLIPLoaderGGUF, OverrideCLIPDevice, etc.)
clone_or_update "https://github.com/city96/ComfyUI-GGUF" "$CUSTOM_NODES_DIR/ComfyUI-GGUF"
pip_install_req "$CUSTOM_NODES_DIR/ComfyUI-GGUF/requirements.txt"

# 2) Extra models utilities used by GGUF/Qwen setups
clone_or_update "https://github.com/city96/ComfyUI_ExtraModels" "$CUSTOM_NODES_DIR/ComfyUI_ExtraModels"
pip_install_req "$CUSTOM_NODES_DIR/ComfyUI_ExtraModels/requirements.txt"

# 3) Cleanup helpers providing VRAMCleanup/RAMCleanup nodes
# These names are common providers; install both to cover variants used in community workflows
clone_or_update "https://github.com/pythongosssss/ComfyUI-Custom-Scripts" "$CUSTOM_NODES_DIR/ComfyUI-Custom-Scripts"
pip_install_req "$CUSTOM_NODES_DIR/ComfyUI-Custom-Scripts/requirements.txt"

clone_or_update "https://github.com/rgthree/rgthree-comfy" "$CUSTOM_NODES_DIR/rgthree-comfy"
pip_install_req "$CUSTOM_NODES_DIR/rgthree-comfy/requirements.txt"

# 4) Unload Models node
git clone https://github.com/SeanScripts/ComfyUI-Unload-Model.git "$CUSTOM_NODES_DIR/ComfyUI-Unload-Models"


# 5) Easy-Use nodes (requires running its own installer)
EASY_USE_DIR="$CUSTOM_NODES_DIR/ComfyUI-Easy-Use"
clone_or_update "https://github.com/yolain/ComfyUI-Easy-Use" "$EASY_USE_DIR"
if [ -f "$EASY_USE_DIR/install.sh" ]; then
  echo "==> Running installer for ComfyUI-Easy-Use"
  (cd "$EASY_USE_DIR" && bash install.sh)
fi

cat <<EOF

All requested model downloads finished.

Placed into:
  - VAE             -> $MODELS_DIR/vae
  - UNET (GGUF)     -> $MODELS_DIR/diffusion_models
  - LoRA            -> $MODELS_DIR/loras
  - GGUF encoder    -> $MODELS_DIR/clip
  - Text encoders   -> $MODELS_DIR/text_encoders

If you run this on Windows, execute inside Git Bash or WSL.
To use another ComfyUI folder, pass it as the first argument:
  ./scripts/download_comfyui_models.sh /path/to/ComfyUI

EOF
