# Testing Guide — ComfyUI SeedVR2 Tile-Upscaler

## Testing Overview

This project has four levels of testing, from fast/cheap to slow/thorough:

| Level | GPU? | Docker? | What it validates |
|---|---|---|---|
| Unit tests | No | No | Handler logic (input validation, image upload, error handling) with mocked ComfyUI |
| Build tests | No | Yes | Docker image builds without errors |
| Local integration | Yes | Yes | Full upscale pipeline against real ComfyUI with mock models |
| RunPod integration | Yes (remote) | Yes | End-to-end on actual RunPod serverless infrastructure |


## Prerequisites

Depending on which test level you want to run:

**Unit tests only:**
- Python 3.10+
- pip install pytest requests websocket-client runpod

**Build tests:**
- Docker (buildx recommended)

**Local integration:**
- Docker with nvidia-container-toolkit
- NVIDIA GPU with 16+ GB VRAM (24 GB recommended for 7B model)
- Real model weights OR mock volume (see below)

**RunPod integration:**
- RunPod account with API key
- Network volume with models already uploaded
- Deployed serverless endpoint


## Quick Start

```bash
# Unit tests (no GPU, no Docker)
cd /path/to/comfyui-upscaler
pip install pytest requests websocket-client runpod
pytest tests/ -v

# Build test (no GPU)
docker build --platform linux/amd64 -t comfyui-upscaler:test .

# Local integration (GPU required)
docker run --rm --gpus all \
  -v /path/to/models:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -p 8188:8188 \
  comfyui-upscaler:test

# Then in another terminal:
curl -X POST http://localhost:8188/runsync \
  -H "Content-Type: application/json" \
  -d @test_input.json
```


## Test Levels in Detail

### Level 1: Unit Tests (No GPU)

Test the handler logic with ComfyUI HTTP/WebSocket calls mocked out.

**What to test:**
- `validate_input()` — accepts valid input, rejects missing workflow, handles JSON strings
- `upload_images()` — base64 decoding, data URI stripping, error handling
- `check_server()` — retry logic, timeout behavior, PID file checking
- `queue_workflow()` — HTTP 400 error parsing, validation error messages
- `handler()` — full job lifecycle with mocked ComfyUI responses

**Example test structure:**

```
tests/
  test_validate_input.py
  test_upload_images.py
  test_check_server.py
  test_queue_workflow.py
  test_handler.py
  conftest.py          # shared fixtures (mock ComfyUI server, sample inputs)
```

**Example unit test:**

```python
# tests/test_validate_input.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from handler import validate_input

def test_missing_input():
    data, err = validate_input(None)
    assert err == "Please provide input"

def test_missing_workflow():
    data, err = validate_input({"images": []})
    assert err == "Missing 'workflow' parameter"

def test_valid_input():
    data, err = validate_input({"workflow": {"1": {}}})
    assert err is None
    assert data["workflow"] == {"1": {}}

def test_json_string_input():
    import json
    data, err = validate_input(json.dumps({"workflow": {"1": {}}}))
    assert err is None

def test_invalid_images():
    data, err = validate_input({"workflow": {}, "images": [{"bad": "data"}]})
    assert "images" in err.lower()
```


### Level 2: Build Tests (No GPU)

Verify the Docker image builds successfully. This catches dependency issues, broken COPY/ADD paths, and custom node install failures.

```bash
# Basic build test
docker build --platform linux/amd64 -t comfyui-upscaler:test . 2>&1 | tee build.log
echo "Exit code: $?"

# Build with specific ComfyUI version
docker build --platform linux/amd64 \
  --build-arg COMFYUI_VERSION=v0.3.30 \
  -t comfyui-upscaler:test .
```

**What to check in build output:**
- All three custom nodes installed: seedvr2_videoupscaler, comfyui-easy-use, comfyui_essentials
- No pip dependency conflicts
- sageattention installed successfully
- Final image size is reasonable (~15-25 GB)


### Level 3: Local Integration (GPU Required)

Run the full container locally with a GPU and send a real upscale job.

**Option A: With real models**

```bash
# Assumes models are at /data/models/unet/ and /data/models/vae/
docker run --rm --gpus all \
  -v /data:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -e COMFY_LOG_LEVEL=DEBUG \
  -p 8188:8188 \
  comfyui-upscaler:test
```

**Option B: With mock volume (smoke test only)**

See "Mock Volume" section below. This verifies the container starts and the handler initializes, but workflows will fail at model load since the mock models are empty files.

```bash
# Create mock volume
mkdir -p test-volume/models/unet test-volume/models/vae
touch test-volume/models/unet/seedvr2_ema_7b_sharp_fp16.safetensors
touch test-volume/models/vae/ema_vae_fp16.safetensors

docker run --rm --gpus all \
  -v $(pwd)/test-volume:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -e NETWORK_VOLUME_DEBUG=true \
  -p 8188:8188 \
  comfyui-upscaler:test
```

**Sending a test request:**

```bash
# Wait for "Starting RunPod Handler" in the container logs, then:
curl -s -X POST http://localhost:8188/runsync \
  -H "Content-Type: application/json" \
  -d @test_input.json | python -m json.tool
```

**Expected success response:**
```json
{
  "images": [
    {
      "filename": "ComfyUI_00001_.png",
      "type": "base64",
      "data": "<base64 string>"
    }
  ]
}
```


### Level 4: RunPod Integration

Test against a deployed RunPod serverless endpoint.

```bash
RUNPOD_ENDPOINT_ID="your-endpoint-id"
RUNPOD_API_KEY="your-api-key"

curl -s -X POST "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/runsync" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @test_input.json | python -m json.tool
```

For async jobs (recommended for upscaling which takes 30-120s):
```bash
# Submit
JOB_ID=$(curl -s -X POST "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/run" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @test_input.json | python -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "Job ID: $JOB_ID"

# Poll for status
curl -s "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/status/${JOB_ID}" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" | python -m json.tool
```


## Mock Volume

For build and smoke tests where you don't have (or don't want to download) the real 14 GB+ model files, create a mock volume:

```bash
mkdir -p test-volume/models/unet test-volume/models/vae
# Create zero-byte placeholder files
touch test-volume/models/unet/seedvr2_ema_7b_sharp_fp16.safetensors
touch test-volume/models/vae/ema_vae_fp16.safetensors
```

**What works with mock models:**
- Container startup and GPU check
- ComfyUI server initialization
- Handler startup and API availability check
- Network volume diagnostics (set NETWORK_VOLUME_DEBUG=true)
- Image upload endpoint
- Workflow validation (ComfyUI will see the files exist)

**What fails with mock models:**
- Actual model loading (files are empty, not valid safetensors)
- Any workflow execution that touches the DiT or VAE models
- The upscale pipeline itself

This is still useful for verifying the container plumbing without burning GPU time on a full inference run.


## Debugging

### Docker build logs

```bash
# Save full build output
docker build --platform linux/amd64 --progress=plain -t comfyui-upscaler:test . 2>&1 | tee build.log

# Check for errors
grep -i "error\|failed\|exception" build.log
```

### Container logs (runtime)

```bash
# Run in foreground to see all output
docker run --rm --gpus all \
  -v /data:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -e COMFY_LOG_LEVEL=DEBUG \
  -p 8188:8188 \
  comfyui-upscaler:test

# Or run detached and tail
docker run -d --name upscaler-test --gpus all \
  -v /data:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -p 8188:8188 \
  comfyui-upscaler:test

docker logs -f upscaler-test
```

### Log sources inside the container

The container runs two processes (both log to stdout):

1. **ComfyUI** (python /comfyui/main.py) — model loading, workflow execution, node errors
2. **Handler** (python /handler.py) — job processing, image upload/download, WebSocket communication

Handler log lines are prefixed with `worker-comfyui -` for easy filtering:
```bash
docker logs upscaler-test 2>&1 | grep "worker-comfyui"
```

### Network volume diagnostics

Set `NETWORK_VOLUME_DEBUG=true` to get a detailed report on the first job:

```bash
docker run --rm --gpus all \
  -v /data:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -e NETWORK_VOLUME_DEBUG=true \
  -p 8188:8188 \
  comfyui-upscaler:test
```

This prints: volume mount status, directory structure, model files found with sizes, and expected vs actual layout.

### Exec into running container

```bash
docker exec -it upscaler-test bash

# Check ComfyUI is running
ps aux | grep main.py

# Check model paths
ls -la /runpod-volume/models/unet/
ls -la /runpod-volume/models/vae/

# Check ComfyUI saw the models
cat /comfyui/extra_model_paths.yaml

# Check GPU
python -c "import torch; print(torch.cuda.get_device_name(0))"

# Hit the API directly
curl -s http://127.0.0.1:8188/object_info | python -m json.tool | head -50
```

### Common Failure Modes

| Symptom | Cause | Fix |
|---|---|---|
| Container exits immediately | GPU not available / CUDA init fails | Check nvidia-smi, ensure --gpus all is passed |
| "ComfyUI server not reachable" | ComfyUI crashed during startup | Check logs for Python import errors or OOM |
| "Workflow validation failed" | Model file missing or wrong name | Check model filenames match workflow exactly |
| WebSocket connection closed | ComfyUI OOM-killed during inference | Use smaller input image or increase GPU VRAM |
| Build fails at comfy-node-install | Custom node has dependency conflict | Check node compatibility with ComfyUI version |
| "No checkpoint models appear to be available" | Network volume not mounted | Verify -v mount path, check /runpod-volume exists |
| Timeout on large images | Input exceeds 3328px max output resolution | Resize input so 2x output stays under 3328px |
| sageattention import error | CUDA version mismatch | Check BASE_IMAGE CUDA version matches PyTorch |


## CI/CD Recommendations

### GitHub Actions example

```yaml
name: CI
on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pytest requests websocket-client runpod
      - run: pytest tests/ -v

  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: false
          tags: comfyui-upscaler:ci

  # GPU integration tests — run manually or on a self-hosted GPU runner
  integration:
    runs-on: [self-hosted, gpu]
    if: github.event_name == 'workflow_dispatch'
    needs: [unit-tests, build-test]
    steps:
      - uses: actions/checkout@v4
      - run: |
          docker build -t comfyui-upscaler:ci .
          docker run --rm --gpus all \
            -v ${{ secrets.MODEL_PATH }}:/runpod-volume \
            -e SERVE_API_LOCALLY=true \
            -d --name ci-test -p 8188:8188 \
            comfyui-upscaler:ci
          sleep 120  # wait for ComfyUI to load models
          curl -f -X POST http://localhost:8188/runsync \
            -H "Content-Type: application/json" \
            -d @test_input.json
          docker stop ci-test
```

### Recommended pipeline

1. **Every push:** Unit tests + build test (fast, no GPU)
2. **Every PR merge to main:** Build + push to staging registry
3. **Manual/nightly:** Full GPU integration test on self-hosted runner
4. **Pre-deploy:** RunPod integration test against staging endpoint


## Architecture Diagram

```
+------------------------------------------------------------------+
|                        Test Levels                                |
|                                                                   |
|  Level 1: Unit Tests              Level 2: Build Tests           |
|  +-------------------------+      +-------------------------+    |
|  | pytest                  |      | docker build            |    |
|  |   handler.py functions  |      |   Dockerfile            |    |
|  |   mocked HTTP/WS calls  |      |   custom node install   |    |
|  |   no Docker, no GPU     |      |   dependency resolution |    |
|  +-------------------------+      +-------------------------+    |
|                                                                   |
|  Level 3: Local Integration       Level 4: RunPod Integration    |
|  +-------------------------+      +-------------------------+    |
|  | docker run --gpus all   |      | RunPod API              |    |
|  |  +-------------------+  |      |  +-------------------+  |    |
|  |  | ComfyUI (8188)    |  |      |  | Serverless Worker |  |    |
|  |  |   + custom nodes  |  |      |  |   (your image)    |  |    |
|  |  +-------------------+  |      |  +-------------------+  |    |
|  |  +-------------------+  |      |  +-------------------+  |    |
|  |  | handler.py        |  |      |  | Network Volume    |  |    |
|  |  |   RunPod handler  |  |      |  |   real models     |  |    |
|  |  +-------------------+  |      |  +-------------------+  |    |
|  |  +-------------------+  |      +-------------------------+    |
|  |  | /runpod-volume    |  |                                     |
|  |  |  models (or mock) |  |                                     |
|  |  +-------------------+  |                                     |
|  +-------------------------+                                     |
+------------------------------------------------------------------+

Container internals (Levels 3 & 4):

  +--start.sh------------------------------------------------------+
  |                                                                 |
  |  1. GPU check (torch.cuda.init)                                |
  |  2. Download models (download_models.sh)                       |
  |  3. Set ComfyUI-Manager to offline mode                        |
  |  4. Launch ComfyUI (main.py) ---------> port 8188              |
  |  5. Launch handler.py                                          |
  |       |                                                        |
  |       +-- check_server() polls http://127.0.0.1:8188/          |
  |       +-- validate_input()                                     |
  |       +-- upload_images() --> POST /upload/image                |
  |       +-- queue_workflow() --> POST /prompt                     |
  |       +-- WebSocket ws://127.0.0.1:8188/ws (execution status)  |
  |       +-- get_history() --> GET /history/{id}                   |
  |       +-- get_image_data() --> GET /view?filename=...           |
  |       +-- base64 encode or S3 upload                           |
  |                                                                 |
  +-----------------------------------------------------------------+
```
