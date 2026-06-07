# History Scanner — marker-powered OCR web app.
#
# Default build targets CPU so it runs anywhere. For GPU acceleration, see the
# note at the bottom of this file and docker-compose.yml.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    DATA_DIR=/data

# System libraries marker / its OCR & PDF stack rely on at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install a CPU-only build of PyTorch first to keep the image lean. Remove this
# line (and rebuild from a CUDA base image) when targeting a GPU.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# marker downloads its models on first use; persist them on a volume so they are
# fetched only once.
RUN mkdir -p /models /data
VOLUME ["/models", "/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── GPU note ──────────────────────────────────────────────────────────────────
# For NVIDIA GPU acceleration:
#   1. Base this image on nvidia/cuda:12.x-cudnn-runtime-ubuntu22.04 + python.
#   2. Drop the CPU torch line above (let marker-pdf pull the CUDA build).
#   3. Run with `docker compose --profile gpu up` (see docker-compose.yml).
