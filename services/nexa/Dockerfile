ARG HARBOR_NEXA_IMAGE=ubuntu:22.04

FROM ${HARBOR_NEXA_IMAGE}
ARG HARBOR_NEXA_IMAGE=ubuntu:22.04

# This file will coerce nexa to install CUDA
# version when we're running with CUDA base image
COPY ./nvidia.sh /nvidia.sh
RUN chmod +x /nvidia.sh && /nvidia.sh

# Install nexa
RUN apt-get update && apt-get install -y curl
RUN curl -fsSL https://public-storage.nexa4ai.com/install.sh | sh

ENTRYPOINT [ "nexa" ]