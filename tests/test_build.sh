#!/usr/bin/env bash
# Build the Docker image and verify key files exist inside it.
set -euo pipefail

IMAGE="comfyui-upscaler:test"

echo "=== Building Docker image (linux/amd64) ==="
docker build --platform linux/amd64 -t "$IMAGE" .

REQUIRED_FILES=(
    /start.sh
    /download_models.sh
    /handler.py
    /comfyui/extra_model_paths.yaml
)

echo "=== Verifying files in image ==="
FAILED=0
for f in "${REQUIRED_FILES[@]}"; do
    if docker run --rm "$IMAGE" test -f "$f"; then
        echo "  OK: $f"
    else
        echo "  MISSING: $f"
        FAILED=1
    fi
done

if [ "$FAILED" -eq 1 ]; then
    echo "BUILD VERIFICATION FAILED"
    exit 1
fi

echo "=== Build verification passed ==="
