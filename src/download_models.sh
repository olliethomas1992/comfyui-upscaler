#!/usr/bin/env bash
# Download SeedVR2 models to network volume if they don't already exist.
#
# Usage:
#   download_models.sh              # blocking download (foreground)
#   download_models.sh --background # fork download, return immediately
#   download_models.sh --check      # exit 0 if all models ready, 1 otherwise

set -euo pipefail

STATUS_FILE="/tmp/model_download_status"
LOG_FILE="/tmp/model_download.log"
VOLUME_MODELS_DIR="/runpod-volume/models/SEEDVR2"
WORKSPACE_MODELS_DIR="/runpod-volume/workspace/runpod-slim/ComfyUI/models/SEEDVR2"
HF_REPO="https://huggingface.co/numz/SeedVR2_comfyUI/resolve/main"

# Models required by the upscaler workflow
MODELS=(
    "seedvr2_ema_7b_sharp_fp16.safetensors"
    "ema_vae_fp16.safetensors"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    echo "download-models: $*"
}

log_err() {
    echo "download-models: ERROR: $*" >&2
}

set_status() {
    echo "$1" > "$STATUS_FILE"
}

find_model() {
    local filename="$1"
    for dir in "$VOLUME_MODELS_DIR" "$WORKSPACE_MODELS_DIR"; do
        if [ -f "${dir}/${filename}" ]; then
            echo "${dir}/${filename}"
            return 0
        fi
    done
    return 1
}

all_models_exist() {
    for model in "${MODELS[@]}"; do
        if ! find_model "$model" > /dev/null 2>&1; then
            return 1
        fi
    done
    return 0
}

# ---------------------------------------------------------------------------
# Download function — prefers aria2c (parallel), falls back to wget -c
# ---------------------------------------------------------------------------

download_file() {
    local url="$1"
    local dest="$2"
    local tmp="${dest}.part"

    if command -v aria2c &> /dev/null; then
        local dest_dir
        dest_dir=$(dirname "$dest")
        local tmp_name
        tmp_name=$(basename "$tmp")
        log "Using aria2c (8 connections) for $(basename "$dest")"
        aria2c \
            -x 8 -s 8 \
            --max-tries=5 \
            --retry-wait=10 \
            --continue=true \
            --auto-file-renaming=false \
            --allow-overwrite=true \
            -d "$dest_dir" \
            -o "$tmp_name" \
            --summary-interval=30 \
            "$url"
    else
        log "Using wget (aria2c not found) for $(basename "$dest")"
        wget -c --progress=dot:mega -O "$tmp" "$url"
    fi
}

download_model() {
    local filename="$1"
    local dest="${VOLUME_MODELS_DIR}/${filename}"
    local url="${HF_REPO}/${filename}"
    local tmp="${dest}.part"

    # Check if model exists in any known location
    local existing
    if existing=$(find_model "$filename"); then
        log "${filename} found at ${existing}, skipping"
        return 0
    fi

    log "Downloading ${filename}..."
    mkdir -p "$VOLUME_MODELS_DIR"

    local start_time
    start_time=$(date +%s)

    if download_file "$url" "$dest"; then
        mv "$tmp" "$dest"
        local elapsed=$(( $(date +%s) - start_time ))
        local size_mb
        size_mb=$(du -m "$dest" 2>/dev/null | cut -f1)
        log "${filename} downloaded successfully (${size_mb:-?}MB in ${elapsed}s)"
    else
        log_err "Failed to download ${filename}"
        # Don't remove .part — resume support means we can continue later
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main download logic (can run in foreground or as background worker)
# ---------------------------------------------------------------------------

do_downloads() {
    # Check if network volume is mounted
    if [ ! -d "/runpod-volume" ]; then
        log "No network volume mounted at /runpod-volume — skipping model download"
        log "Models will need to exist inside the container image"
        set_status "complete"
        return 0
    fi

    # Quick check — maybe everything is already there
    if all_models_exist; then
        log "All models already present"
        set_status "complete"
        return 0
    fi

    set_status "downloading"
    local failed=0

    for model in "${MODELS[@]}"; do
        if ! download_model "$model"; then
            failed=1
        fi
    done

    if [ "$failed" -eq 0 ]; then
        log "All models ready"
        set_status "complete"
    else
        log_err "Some models failed to download"
        set_status "error"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

case "${1:-}" in
    --check)
        # Quick readiness probe — no downloads, just check files
        if [ -f "$STATUS_FILE" ] && [ "$(cat "$STATUS_FILE")" = "complete" ]; then
            exit 0
        fi
        if all_models_exist; then
            set_status "complete"
            exit 0
        fi
        # Still downloading or not started
        status="unknown"
        [ -f "$STATUS_FILE" ] && status=$(cat "$STATUS_FILE")
        log "Models not ready (status: ${status})"
        exit 1
        ;;
    --background)
        log "Starting background model download (log: ${LOG_FILE})"
        set_status "downloading"
        # Fork the actual work into the background
        (
            do_downloads >> "$LOG_FILE" 2>&1
        ) &
        disown
        log "Background download PID: $!"
        exit 0
        ;;
    "")
        # Foreground (blocking) download
        do_downloads
        ;;
    *)
        echo "Usage: $0 [--background|--check]" >&2
        exit 1
        ;;
esac
