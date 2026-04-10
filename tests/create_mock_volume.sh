#!/usr/bin/env bash
# Create a mock volume directory with fake model files so download_models.sh
# skips real downloads during testing.
set -euo pipefail

VOLUME_DIR="${1:-./test-volume}"

echo "Creating mock volume at ${VOLUME_DIR} ..."

# Model directories from extra_model_paths.yaml
MODEL_DIRS=(
    checkpoints
    clip
    clip_vision
    configs
    controlnet
    embeddings
    loras
    upscale_models
    vae
    unet
    SEEDVR2
)

for dir in "${MODEL_DIRS[@]}"; do
    mkdir -p "${VOLUME_DIR}/models/${dir}"
done

# Mock SEEDVR2 model files (1KB each) so download_models.sh sees them as present
for model in seedvr2_ema_7b_sharp_fp16.safetensors ema_vae_fp16.safetensors; do
    dest="${VOLUME_DIR}/models/SEEDVR2/${model}"
    if [ ! -f "$dest" ]; then
        dd if=/dev/zero of="$dest" bs=1024 count=1 2>/dev/null
        echo "  Created mock: ${dest}"
    else
        echo "  Already exists: ${dest}"
    fi
done

echo "Mock volume ready at ${VOLUME_DIR}"
