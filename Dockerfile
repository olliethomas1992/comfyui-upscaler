# =============================================================================
# RunPod ComfyUI Upscaler — layered on runpod/worker-comfyui base
# =============================================================================
# The base image (12 GB, likely pre-cached on RunPod) already includes:
#   - CUDA 12.6.3 + cuDNN runtime (Ubuntu 24.04)
#   - Python 3.12 + uv + venv at /opt/venv
#   - ComfyUI (latest at image build time) at /comfyui
#   - PyTorch + torchvision + torchaudio
#   - runpod SDK, requests, websocket-client
#   - comfy-cli, comfy-node-install, comfy-manager-set-mode
#   - start.sh, handler.py, network_volume.py, test_input.json
#   - git, wget, ffmpeg, openssh-server
#
# We ONLY add our custom layers on top (~2 GB):
#   - aria2 for parallel model downloads
#   - sageattention for DiT speed optimization
#   - Custom nodes (seedvr2, easy-use, essentials)
#   - Our handler, start script, and download script overrides
# =============================================================================

ARG BASE_IMAGE=runpod/worker-comfyui:5.8.5-base
FROM ${BASE_IMAGE}

# --- Extra system packages not in the base image ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Extra Python packages ---
RUN uv pip install sageattention

# --- Our custom model path config (overrides base) ---
WORKDIR /comfyui
ADD src/extra_model_paths.yaml ./
WORKDIR /

# --- Our application code (overrides base handler/start/scripts) ---
ADD src/start.sh src/download_models.sh src/network_volume.py handler.py test_input.json ./
RUN chmod +x /start.sh /download_models.sh

# --- Install custom nodes for SeedVR2 tile-upscale workflow ---
ENV PIP_NO_INPUT=1
RUN comfy-node-install \
    seedvr2_videoupscaler \
    comfyui-easy-use \
    comfyui_essentials

CMD ["/start.sh"]
