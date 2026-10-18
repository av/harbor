FROM docker:29-cli AS docker
FROM python:3.13-slim-bookworm

COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG AGENTEVAL_VERSION=0.24.0
RUN pip install --no-cache-dir "harbor==${AGENTEVAL_VERSION}"

COPY --chmod=755 cli.py /usr/local/bin/agenteval
