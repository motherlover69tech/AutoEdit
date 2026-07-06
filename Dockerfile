# AUTOEDIT Docker image
# Build:  docker build -t autoedit .
# Run:    docker run -p 8000:8000 --env-file .env autoedit

FROM python:3.12-slim

WORKDIR /app

# System deps for ffmpeg, scipy, numpy, Intel QSV.
# python:3.12-slim currently tracks Debian Trixie, where
# intel-media-va-driver-non-free is no longer available as a package name.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    intel-media-va-driver \
    vainfo \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --no-dev

# App code
COPY src/ ./src/
COPY scripts/ ./scripts/

ENV PYTHONPATH=/app/src
ENV DATA_ROOT=/data

EXPOSE 8000

CMD uv run uvicorn autoedit.api:app --host 0.0.0.0 --port ${PORT:-8000}
