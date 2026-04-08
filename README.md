# ComfyUI SeedVR2 Tile-Upscaler — RunPod Serverless Worker

RunPod serverless worker for 2x image upscaling using SeedVR2 with tiled VAE encoding/decoding. Based on [blib-la/runpod-worker-comfy](https://github.com/blib-la/runpod-worker-comfy).

## Models Required (on Network Volume)

Place these on your RunPod network volume under `/runpod-volume/models/unet/` and `/runpod-volume/models/vae/`:

- `seedvr2_ema_7b_sharp_fp16.safetensors` → `models/unet/`
- `ema_vae_fp16.safetensors` → `models/vae/`

## Custom Nodes Included

- **seedvr2_videoupscaler** — SeedVR2 ComfyUI nodes (DiT loader, VAE loader, upscaler)
- **comfyui-easy-use** — Utility nodes including `easy mathInt`
- **comfyui_essentials** — Essential utility nodes including `GetImageSize+`

## Build

```bash
docker build --platform linux/amd64 -t your-registry/comfyui-seedvr2-upscaler:latest .
```

To use a specific ComfyUI version:

```bash
docker build --platform linux/amd64 \
  --build-arg COMFYUI_VERSION=v0.3.30 \
  -t your-registry/comfyui-seedvr2-upscaler:latest .
```

## Push

```bash
docker push your-registry/comfyui-seedvr2-upscaler:latest
```

## Deploy on RunPod

1. Create a Serverless Endpoint on RunPod
2. Set the Docker image to your pushed image
3. Attach network volume `lma1bbhd7s` (EU-RO-1) with models
4. Set environment variables:
   - `BUCKET_ENDPOINT_URL` — (optional) S3-compatible endpoint for output upload
   - `BUCKET_ACCESS_KEY_ID` — (optional) S3 access key
   - `BUCKET_SECRET_ACCESS_KEY` — (optional) S3 secret key
   - `REFRESH_WORKER=true` — (recommended) clean state after each job

## Test Locally

```bash
docker run --rm --gpus all \
  -v /path/to/models:/runpod-volume \
  -e SERVE_API_LOCALLY=true \
  -p 8188:8188 \
  your-registry/comfyui-seedvr2-upscaler:latest
```

Then send `test_input.json` to `http://localhost:8188/runsync`.

## Workflow

The workflow performs a 2x tile-based upscale:

1. Load input image
2. Get image width, multiply by 2
3. Load SeedVR2 DiT model (7B sharp fp16) with sageattn_3
4. Load SeedVR2 VAE with tiled encode/decode (2048 tiles, 1024 overlap)
5. Run SeedVR2VideoUpscaler with wavelet color correction
6. Save output image

Max output resolution: 3328px on the long side.
