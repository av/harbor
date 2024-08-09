# This is a base image for "parler" service,
# so trying to increase the likelyhood of the layers
# already being cached and reused
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

WORKDIR /app

# AirLLM + friends for the OpenAI server
RUN pip install airllm flask pydantic bitsandbytes
COPY ./server.py ./server.py

ENTRYPOINT [ "python", "/app/server.py" ]

