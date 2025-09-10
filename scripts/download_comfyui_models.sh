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

# Backwards-compat wrapper for existing calls in this script
curl_download() { download_file "$@"; }

# ------------------------------
# Wan 2.2 I2V (GGUF) + Lightning LoRAs + UMT5 encoder (GGUF)
# ------------------------------
# VAE
curl_download \
  "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" \
  "$MODELS_DIR/vae/wan_2.1_vae.safetensors"

# UNETs (GGUF)
curl_download \
  "https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_S.gguf" \
  "$MODELS_DIR/diffusion_models/Wan2.2-I2V-A14B-HighNoise-Q4_K_S.gguf"

curl_download \
  "https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/resolve/main/LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_0.gguf" \
  "$MODELS_DIR/diffusion_models/Wan2.2-I2V-A14B-LowNoise-Q4_0.gguf"

# Lightning LoRAs
curl_download \
  "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan22-Lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors" \
  "$MODELS_DIR/loras/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors"

curl_download \
  "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan22-Lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors" \
  "$MODELS_DIR/loras/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors"

# Text encoder (GGUF)
curl_download \
  "https://huggingface.co/city96/umt5-xxl-encoder-gguf/resolve/main/umt5-xxl-encoder-Q5_K_M.gguf" \
  "$MODELS_DIR/clip/umt5-xxl-encoder-Q5_K_M.gguf"

# ------------------------------
# Qwen Image (Distill GGUF) + VAE + Text Encoder (FP8 safetensors)
# ------------------------------
# VAE
curl_download \
  "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" \
  "$MODELS_DIR/vae/qwen_image_vae.safetensors"

# UNET (GGUF)
curl_download \
  "https://huggingface.co/QuantStack/Qwen-Image-Distill-GGUF/resolve/main/Qwen_Image_Distill-Q4_0.gguf" \
  "$MODELS_DIR/unet/Qwen_Image_Distill-Q4_0.gguf"

# Text encoder (FP8 safetensors)
curl_download \
  "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
  "$MODELS_DIR/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"

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

# ------------------------------
# Optional: RIFE VFI model (used by RIFE VFI node)
# Note: The RIFE custom node often attempts auto-download. If you want to fetch it now,
# uncomment one of the mirrors below and set a target folder you use with the node.
# Common choices:
#   - "$MODELS_DIR/frame_interpolation/rife/rife47.pth"
#   - or custom_nodes/ComfyUI-Frame-Interpolation/models/rife47.pth
#
# mkdir -p "$MODELS_DIR/frame_interpolation/rife"
# curl_download \
#   "https://huggingface.co/wavespeed/misc/resolve/main/rife/rife47.pth" \
#   "$MODELS_DIR/frame_interpolation/rife/rife47.pth"

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
