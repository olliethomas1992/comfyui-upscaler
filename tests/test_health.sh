#!/usr/bin/env bash
# Poll the RunPod handler health endpoint until it returns 200.
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
HEALTH_URL="${BASE_URL}/health"
MAX_ATTEMPTS=60
INTERVAL=5

echo "Polling health endpoint: ${HEALTH_URL}"

for i in $(seq 1 "$MAX_ATTEMPTS"); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || true)
    if [ "$STATUS" = "200" ]; then
        echo "Health check passed (attempt ${i}/${MAX_ATTEMPTS})"
        exit 0
    fi
    echo "  Attempt ${i}/${MAX_ATTEMPTS}: status=${STATUS:-timeout}, retrying in ${INTERVAL}s..."
    sleep "$INTERVAL"
done

echo "Health check FAILED after ${MAX_ATTEMPTS} attempts"
exit 1
