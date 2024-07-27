# Harbor

Developer-friendly containerized LLM setup. The main goal is to provide a reasonable starting point for developers to experiment with LLMs.

```bash
git clone git@github.com:av/harbor.git
cd harbor
docker compose up
```

## Components

| Component | Description |
| --- | --- |
| [Open WebUI](https://docs.openwebui.com/) | Extensible, self-hosted interface for AI that adapts to your workflow. |
| [Ollama](https://ollama.com/) | Ergonomic wrapper around llama.cpp with plenty of QoL features |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | LLM inference in C/C++ |
| [SearXNG](https://github.com/searxng/searxng) | A free internet metasearch engine which aggregates results from various search services and databases. |
| [openedai-speech](https://github.com/matatonic/openedai-speech) | An OpenAI API compatible text to speech server |
| [text-generation-inference](https://github.com/huggingface/text-generation-inference) | A Rust, Python and gRPC server for inference from HuggingFace |
| [lmdeploy](https://lmdeploy.readthedocs.io/en/latest/get_started.html) | A toolkit for deploying, and serving LLMs. |
| [litellm](https://docs.litellm.ai/docs/) | LLM API Proxy/Gateway |