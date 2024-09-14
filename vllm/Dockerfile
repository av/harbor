ARG HARBOR_VLLM_VERSION=latest
FROM vllm/vllm-openai:${HARBOR_VLLM_VERSION}

# Install:
# - bitsandbytes for additional quantization support
RUN pip install bitsandbytes
