# Harbor

Developer-friendly containerized LLM setup. The main goal is to provide a reasonable starting point for developers to experiment with LLMs.

## Quickstart

```bash
git clone https://github.com/av/harbor.git && cd harbor
./harbor.sh
```

## Features

- Reusing local cache for huggingface, ollama, and other services
- Service configuration is

## Getting Started

This project is a script around a pre-configured Docker Compose setup that connects various LLM-related projects together. It simplifies the portion where you have to link different services together to get a working setup.

## CLI Options

## Services Overview

### [Open WebUI](https://docs.openwebui.com/)
Extensible, self-hosted interface for AI that adapts to your workflow.
Configuration: `./open-webui/config.json`


| Service | Description |
| --- | --- |
| [Open WebUI](https://docs.openwebui.com/) | Extensible, self-hosted interface for AI that adapts to your workflow. |
| [Ollama](https://ollama.com/) | Ergonomic wrapper around llama.cpp with plenty of QoL features |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | LLM inference in C/C++ |
| [SearXNG](https://github.com/searxng/searxng) | A free internet metasearch engine which aggregates results from various search services and databases. |
| [openedai-speech](https://github.com/matatonic/openedai-speech) | An OpenAI API compatible text to speech server |
| [text-generation-inference](https://github.com/huggingface/text-generation-inference) | A Rust, Python and gRPC server for inference from HuggingFace |
| [lmdeploy](https://lmdeploy.readthedocs.io/en/latest/get_started.html) | A toolkit for deploying, and serving LLMs. |
| [litellm](https://docs.litellm.ai/docs/) | LLM API Proxy/Gateway |

