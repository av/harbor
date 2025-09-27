# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv

# This is the Dockerfile for browser-use within Harbor, it bundles the following dependencies:
#     python3, pip, playwright, chromium, browser-use and its dependencies.
# Usage:
#     docker build browseruse/ -t harbor/browseruse --no-cache
#     docker run -v "$PWD/data":/data harbor/browseruse
#     docker run -v "$PWD/data":/data harbor/browseruse --version

FROM python:3.12-slim

LABEL name="harbor-browseruse" \
    maintainer="Harbor team" \
    description="Make websites accessible for AI agents. Automate tasks online with ease." \
    homepage="https://github.com/browser-use/browser-use" \
    documentation="https://docs.browser-use.com" \
    org.opencontainers.image.title="harbor-browseruse" \
    org.opencontainers.image.vendor="harbor" \
    org.opencontainers.image.description="Make websites accessible for AI agents. Automate tasks online with ease." \
    org.opencontainers.image.source="https://github.com/browser-use/browser-use" \
    com.docker.image.source.entrypoint="Dockerfile" \
    com.docker.desktop.extension.api.version=">= 1.4.7" \
    com.docker.desktop.extension.icon="https://avatars.githubusercontent.com/u/192012301?s=200&v=4" \
    com.docker.extension.publisher-url="https://browser-use.com" \
    com.docker.extension.screenshots='[{"alt": "Screenshot of CLI splashscreen", "url": "https://github.com/user-attachments/assets/3606d851-deb1-439e-ad90-774e7960ded8"}, {"alt": "Screenshot of CLI running", "url": "https://github.com/user-attachments/assets/d018b115-95a4-4ac5-8259-b750bc5f56ad"}]' \
    com.docker.extension.detailed-description='See here for detailed documentation: https://docs.browser-use.com' \
    com.docker.extension.changelog='See here for release notes: https://github.com/browser-use/browser-use/releases' \
    com.docker.extension.categories='web,utility-tools,ai'

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT

######### Environment Variables #################################

# Global system-level config
ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_PREFERENCE=only-system \
    npm_config_loglevel=error \
    IN_DOCKER=True

# User config
ENV BROWSERUSE_USER="browseruse" \
    DEFAULT_PUID=911 \
    DEFAULT_PGID=911

# Paths
ENV CODE_DIR=/app \
    DATA_DIR=/data \
    VENV_DIR=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Build shell config
SHELL ["/bin/bash", "-o", "pipefail", "-o", "errexit", "-o", "errtrace", "-o", "nounset", "-c"]

# Force apt to leave downloaded binaries in /var/cache/apt (massively speeds up Docker builds)
RUN echo 'Binary::apt::APT::Keep-Downloaded-Packages "1";' > /etc/apt/apt.conf.d/99keep-cache \
    && echo 'APT::Install-Recommends "0";' > /etc/apt/apt.conf.d/99no-intall-recommends \
    && echo 'APT::Install-Suggests "0";' > /etc/apt/apt.conf.d/99no-intall-suggests \
    && rm -f /etc/apt/apt.conf.d/docker-clean

# Create non-privileged user for browseruse and chrome
RUN echo "[*] Setting up $BROWSERUSE_USER user uid=${DEFAULT_PUID}..." \
    && groupadd --system $BROWSERUSE_USER \
    && useradd --system --create-home --gid $BROWSERUSE_USER --groups audio,video $BROWSERUSE_USER \
    && usermod -u "$DEFAULT_PUID" "$BROWSERUSE_USER" \
    && groupmod -g "$DEFAULT_PGID" "$BROWSERUSE_USER" \
    && mkdir -p /data \
    && mkdir -p /home/$BROWSERUSE_USER/.config \
    && chown -R $BROWSERUSE_USER:$BROWSERUSE_USER /home/$BROWSERUSE_USER \
    && ln -s $DATA_DIR /home/$BROWSERUSE_USER/.config/browseruse
    # DEFAULT_PUID and DEFAULT_PID are overridden by PUID and PGID in /bin/docker_entrypoint.sh at runtime
    # https://docs.linuxserver.io/general/understanding-puid-and-pgid

# Install base apt dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    echo "[+] Installing APT base system dependencies for $TARGETPLATFORM..." \
    && mkdir -p /etc/apt/keyrings \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        # 1. packaging dependencies
        apt-transport-https ca-certificates apt-utils gnupg2 unzip curl wget grep \
        # 2. frivolous CLI helpers to make debugging easier
        nano iputils-ping dnsutils jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Chromium browser directly from system packages
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    echo "[+] Installing chromium browser from system packages..." \
    && apt-get update -qq \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-unifont \
        fonts-liberation \
        fonts-dejavu-core \
        fonts-freefont-ttf \
        fonts-noto-core \
        xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/chromium /usr/bin/chromium-browser \
    && ln -s /usr/bin/chromium /app/chromium-browser \
    && mkdir -p "/home/${BROWSERUSE_USER}/.config/chromium/Crash Reports/pending/" \
    && chown -R "$BROWSERUSE_USER:$BROWSERUSE_USER" "/home/${BROWSERUSE_USER}/.config"

# Setup Python virtual environment
WORKDIR /app
RUN echo "[+] Setting up venv using uv in $VENV_DIR..." \
    && uv venv

# Create a pyproject.toml file for browser-use installation
RUN echo '[project]' > pyproject.toml \
    && echo 'name = "harbor-browseruse"' >> pyproject.toml \
    && echo 'version = "0.1.0"' >> pyproject.toml \
    && echo 'description = "Harbor browser-use service"' >> pyproject.toml \
    && echo 'requires-python = ">=3.10"' >> pyproject.toml \
    && echo 'dependencies = [' >> pyproject.toml \
    && echo '    "browser-use[all]",' >> pyproject.toml \
    && echo '    "fastapi",' >> pyproject.toml \
    && echo '    "uvicorn",' >> pyproject.toml \
    && echo ']' >> pyproject.toml

# Install browser-use and its dependencies
RUN --mount=type=cache,target=/root/.cache,sharing=locked,id=cache-$TARGETARCH$TARGETVARIANT \
    echo "[+] Installing browser-use and dependencies..." \
    && uv sync --all-extras

# Create a simple FastAPI server for browser-use
COPY <<'EOF' /app/server.py
import os
import uvicorn
from fastapi import FastAPI
from browser_use import Agent, Browser
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/browse")
async def browse_task(task: dict):
    """Execute a browser task"""
    try:
        # Initialize browser and agent
        browser = Browser()
        agent = Agent(task=task.get("task", ""), browser=browser)

        # Run the task
        result = await agent.run()

        await browser.close()

        return {"success": True, "result": str(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=7788,
        reload=False
    )
EOF

RUN mkdir -p "$DATA_DIR/profiles/default" \
    && chown -R $BROWSERUSE_USER:$BROWSERUSE_USER "$DATA_DIR" \
    && chmod +x /app/server.py

# Create entrypoint script
COPY <<'EOF' /app/entrypoint.sh
#!/bin/bash
set -e

# Start Xvfb for headless display
Xvfb :99 -screen 0 1920x1080x24 &

# Set display
export DISPLAY=:99

# Switch to browseruse user and run the server
exec python /app/server.py
EOF

RUN chmod +x /app/entrypoint.sh

USER "$BROWSERUSE_USER"
VOLUME "$DATA_DIR"
EXPOSE 7788
EXPOSE 6080
EXPOSE 5901
EXPOSE 9222

HEALTHCHECK --interval=30s --timeout=20s --retries=15 \
    CMD curl --silent 'http://localhost:7788/health' | grep -q 'healthy'

ENTRYPOINT ["/app/entrypoint.sh"]
