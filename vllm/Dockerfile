ARG HARBOR_VLLM_VERSION=latest
ARG HARBOR_VLLM_IMAGE=vllm/vllm-openai

FROM ${HARBOR_VLLM_IMAGE}:${HARBOR_VLLM_VERSION}

# Install:
# - bitsandbytes for additional quantization support
RUN pip install bitsandbytes
