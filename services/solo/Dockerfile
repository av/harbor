FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    docker.io \
    build-essential \
    linux-libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Clone and install solo-cli
ARG GIT_REF=https://github.com/GetSoloTech/solo-cli#main
RUN git clone ${GIT_REF%#*} . && \
    git checkout ${GIT_REF#*#} || true && \
    uv pip install --system -e .

# Create a directory for solo config
RUN mkdir -p /root/.solo

ENTRYPOINT ["solo"]
CMD ["--help"]
