ARG BASE_IMAGE=ubuntu:24.04

FROM ${BASE_IMAGE}

# Release tag from https://github.com/PrismML-Eng/llama.cpp/releases and the
# asset flavor suffix: ubuntu-x64, linux-cuda-12.8-x64, ubuntu-rocm-7.2-x64, ...
ARG PRISMML_VERSION
ARG PRISMML_ASSET=ubuntu-x64
# Runtime libraries the release binary links against that the base image lacks
# (the ROCm dev image ships without hipblas/rocblas)
ARG EXTRA_PACKAGES=""

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 ${EXTRA_PACKAGES} \
    && (apt-get install -y --no-install-recommends libcurl4t64 || apt-get install -y --no-install-recommends libcurl4) \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /tmp/prismml \
    && curl -fL "https://github.com/PrismML-Eng/llama.cpp/releases/download/${PRISMML_VERSION}/llama-${PRISMML_VERSION}-bin-${PRISMML_ASSET}.tar.gz" \
        | tar -xz -C /tmp/prismml \
    && mv /tmp/prismml/llama-${PRISMML_VERSION}/* /app/ \
    && rm -rf /tmp/prismml \
    && test -x /app/llama-server

# /opt/rocm/lib is where the ROCm base image keeps hipblas/rocblas; harmless elsewhere
ENV LD_LIBRARY_PATH=/app:/opt/rocm/lib
ENV LLAMA_ARG_HOST=0.0.0.0

WORKDIR /app

ENTRYPOINT ["/app/llama-server"]
