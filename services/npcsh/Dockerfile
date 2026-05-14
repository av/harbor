ARG HARBOR_NPCSH_BASE_IMAGE=python
ARG HARBOR_NPCSH_BASE_VERSION=3.12-slim

FROM ${HARBOR_NPCSH_BASE_IMAGE}:${HARBOR_NPCSH_BASE_VERSION}

ARG HARBOR_NPCSH_PACKAGE_VERSION

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libsqlite3-dev \
    && if [ "${HARBOR_NPCSH_PACKAGE_VERSION}" = "latest" ]; then \
        pip install --no-cache-dir "npcsh[lite]"; \
    else \
        pip install --no-cache-dir "npcsh[lite]==${HARBOR_NPCSH_PACKAGE_VERSION}"; \
    fi \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

EXPOSE 5337
