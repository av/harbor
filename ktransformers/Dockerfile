# Base image for some other Harbor services, reusing
ARG HARBOR_KTRANSFORMERS_IMAGE=pytorch/pytorch:2.3.1-cuda12.1-cudnn8-devel

FROM ${HARBOR_KTRANSFORMERS_IMAGE}

ARG HARBOR_KTRANSFORMERS_VERSION="0.1.4"
ENV CUDA_HOME /usr/local/cuda

WORKDIR /app
RUN apt-get update && apt-get install -y git
RUN pip install numpy cpufeature
RUN pip install flash_attn
RUN pip install https://github.com/kvcache-ai/ktransformers/releases/download/v${HARBOR_KTRANSFORMERS_VERSION}/ktransformers-${HARBOR_KTRANSFORMERS_VERSION}+cu121torch23avx2-cp310-cp310-linux_x86_64.whl --no-build-isolation
RUN ldconfig /usr/local/cuda-$(echo $CUDA_VERSION | cut -d. -f1,2)/compat/

ENTRYPOINT [ "ktransformers" ]