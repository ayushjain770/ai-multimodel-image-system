# syntax=docker/dockerfile:1
# ComfyUI image generation backend (GPU / prod only).
# Built on a CUDA-enabled PyTorch base so Juggernaut (SDXL) runs on the EC2 GPU.
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    COMFYUI_VERSION=master

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git
WORKDIR /opt/ComfyUI
RUN pip install --no-cache-dir -r requirements.txt

# Ship a reference workflow (the backend submits its own copy at runtime).
COPY workflows/ /opt/ComfyUI/user/default/workflows/

EXPOSE 8188

# `models/` is bind-mounted from the host (holds checkpoints/juggernautXL.safetensors).
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
