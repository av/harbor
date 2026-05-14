ARG HARBOR_NEEDLE_BASE_IMAGE=python
ARG HARBOR_NEEDLE_BASE_VERSION=3.12-slim

FROM ${HARBOR_NEEDLE_BASE_IMAGE}:${HARBOR_NEEDLE_BASE_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1 \
    HF_HUB_DISABLE_TELEMETRY=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

ARG HARBOR_NEEDLE_GIT_REF=https://github.com/cactus-compute/needle.git@main

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install fastapi "uvicorn[standard]" \
    && python -m pip install "git+${HARBOR_NEEDLE_GIT_REF}"

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
