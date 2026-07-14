FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:ac55d124da4882b497f732d8dfd9a702d5447a5f29d08d56da6f64f0a1eb34bc

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/service/src \
    PIP_NO_CACHE_DIR=1 \
    DATA_ROOT=/data \
    WHISPERX_DEVICE=cuda \
    HF_HOME=/models/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /service
COPY services/whisperx_service/requirements.lock ./requirements.lock
RUN python3 -m pip install --break-system-packages -r requirements.lock

COPY services ./services
COPY src ./src
EXPOSE 8011

CMD ["python3", "-m", "uvicorn", "services.whisperx_service.app:app", "--host", "127.0.0.1", "--port", "8011"]
