#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/workspace/comfyui/models"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
MODELS_LIST_FILE="$SCRIPT_DIR/models_to_download.txt"

if [ ! -f "$MODELS_LIST_FILE" ]; then
  echo "ERROR: Models list not found: $MODELS_LIST_FILE" >&2
  exit 1
fi

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
    wget -O "$out" --continue --tries=5 --waitretry=5 --retry-connrefused "$url"
  elif have_cmd curl; then
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

while IFS= read -r line || [[ -n "$line" ]]; do
  line=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

  if [ -z "$line" ] || [[ "$line" == '#'* ]]; then
    continue
  fi

  url=$(echo "$line" | cut -d' ' -f1)
  dest_subdir=$(echo "$line" | cut -d' ' -f2-)

  if [ -z "$url" ] || [ -z "$dest_subdir" ]; then
    echo "WARNING: Skipping invalid line: '$line'" >&2
    continue
  fi

  filename=$(basename "$url")
  output_path="$BASE_DIR/$dest_subdir/$filename"

  download_file "$url" "$output_path"
done < "$MODELS_LIST_FILE"

echo "\nAll models downloaded to $BASE_DIR"
