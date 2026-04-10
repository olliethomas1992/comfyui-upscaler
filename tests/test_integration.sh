#!/usr/bin/env bash
# Full integration test: wait for handler, submit a job, verify output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BASE_URL="${1:-http://localhost:8000}"
HEALTH_URL="${BASE_URL}/health"
RUNSYNC_URL="${BASE_URL}/runsync"
TEST_INPUT="${PROJECT_DIR}/test_input.json"

MAX_HEALTH_ATTEMPTS=60   # 5 minutes at 5s intervals
HEALTH_INTERVAL=5

# --- Wait for handler to be ready ---
echo "=== Waiting for handler to be ready ==="
READY=0
for i in $(seq 1 "$MAX_HEALTH_ATTEMPTS"); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || true)
    if [ "$STATUS" = "200" ]; then
        echo "Handler ready (attempt ${i}/${MAX_HEALTH_ATTEMPTS})"
        READY=1
        break
    fi
    echo "  Attempt ${i}/${MAX_HEALTH_ATTEMPTS}: status=${STATUS:-timeout}, retrying in ${HEALTH_INTERVAL}s..."
    sleep "$HEALTH_INTERVAL"
done

if [ "$READY" -eq 0 ]; then
    echo "FAIL: Handler did not become ready within timeout"
    exit 1
fi

# --- Submit test job ---
echo "=== Submitting test job to ${RUNSYNC_URL} ==="
RESPONSE=$(curl -s -X POST "$RUNSYNC_URL" \
    -H "Content-Type: application/json" \
    -d @"$TEST_INPUT")

echo "Response (first 500 chars): ${RESPONSE:0:500}"

# --- Check for errors ---
if echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'error' in data and data['error']:
    print(f'ERROR: {data[\"error\"]}')
    sys.exit(1)
status = data.get('status', '')
if status == 'FAILED':
    print(f'Job FAILED: {data}')
    sys.exit(1)
"; then
    echo "No errors in response"
else
    echo "FAIL: Response contains errors"
    exit 1
fi

# --- Verify output images ---
echo "=== Checking for output images ==="
HAS_IMAGES=$(echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
output = data.get('output', {})
images = output.get('images', [])
if images:
    print(len(images))
else:
    message = output.get('message', '')
    if message:
        print('0')
    else:
        print('0')
" 2>/dev/null || echo "0")

if [ "$HAS_IMAGES" = "0" ]; then
    echo "WARNING: No images found in output"
    echo "Full response: ${RESPONSE}"
else
    echo "Found ${HAS_IMAGES} image(s) in output"
fi

# --- Save first image if base64 ---
echo "$RESPONSE" | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
images = data.get('output', {}).get('images', [])
if images and isinstance(images[0], dict):
    img_data = images[0].get('image', '')
    if img_data:
        raw = base64.b64decode(img_data)
        with open('/tmp/test_output.png', 'wb') as f:
            f.write(raw)
        print('Saved result image to /tmp/test_output.png')
elif images and isinstance(images[0], str):
    raw = base64.b64decode(images[0])
    with open('/tmp/test_output.png', 'wb') as f:
        f.write(raw)
    print('Saved result image to /tmp/test_output.png')
else:
    print('No base64 image data to save')
" 2>/dev/null || true

echo "=== Integration test complete ==="
