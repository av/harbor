# Base image for parler/airllm/textgrad services, reusing
ARG HARBOR_JUPYTER_IMAGE=pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

FROM ${HARBOR_JUPYTER_IMAGE}
ARG HARBOR_JUPYTER_EXTRA_DEPS=""

WORKDIR /app
RUN pip install jupyterlab
RUN if [ "$HARBOR_JUPYTER_EXTRA_DEPS" = "" ] ; then \
    echo "No extra deps" ; \
  else \
    pip install $(echo ${HARBOR_JUPYTER_EXTRA_DEPS} | sed 's/;/ /g') ; \
  fi