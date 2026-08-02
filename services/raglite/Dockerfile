FROM python:3.11

RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake && rm -rf /var/lib/apt/lists/*
RUN pip install raglite[chainlit,pandoc,ragas]
# raglite imports llama-cpp-python lazily but unconditionally at CLI startup
# (RAGLiteConfig default llm probes llama_supports_gpu_offload), and the
# raglite package no longer declares it as a hard dependency.
RUN pip install llama-cpp-python
RUN pip install --upgrade litellm

CMD raglite chainlit