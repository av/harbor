FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone and install ros-mcp-server
ARG GIT_REF=https://github.com/robotmcp/ros-mcp-server#main
RUN git clone ${GIT_REF%#*} . && \
    git checkout ${GIT_REF#*#} || true && \
    pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir fastmcp mcp roslibpy asyncio opencv-python-headless numpy

# Set default env vars for rosbridge
ENV ROSBRIDGE_HOST=host.docker.internal
ENV ROSBRIDGE_PORT=9090

ENTRYPOINT ["python", "server.py"]
