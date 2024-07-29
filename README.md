# Harbor

Developer-friendly containerized LLM setup. The main goal is to provide a reasonable starting point for developers to experiment with LLMs.

## Quickstart

```bash
git clone https://github.com/av/harbor.git && cd harbor

# [Optional] make available globally
# Creates a symlink in User's local bin directory
./harbor.sh ln

# Start default services
harbor up

# [Optional] open in the browser
harbor open webui
# Alternatively, just visit http://localhost:33801/ directly
```

> [!NOTE]
> First open will require you to create a local admin account. Harbor keeps auth requirement by default because it also supports exposing your local stack to the internet.

## Why?

If you're comfortable with Docker and Linux administration - you likely don't need Harbor to manage your LLM setup. However, you're also likely to arrive to a somewhat similar solution eventually.

Harbor is not designed as a deployment solution, but rather as a helper for the local LLM development environment. It's a good starting point for experimenting with LLMs and related services.

You can later eject from Harbor and use the services in your own setup, or continue using Harbor as a base for your own configuration.

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Features](#features)
- [Getting Started](#getting-started)
- [Harbor CLI Reference](#harbor-cli-reference)
  - [`harbor ln`](#harbor-ln)
  - [`harbor up <services>`](#harbor-up-services)
- [Services Overview](#services-overview)
  - [Open WebUI](#open-webui)
  - [Ollama](#ollama)
  - [llama.cpp](#llamacpp)

## Features

- Services are pre-configured to work together
- Reused local cache - huggingface, ollama, etc.
- All configuration in one place
- Access required CLIs via Docker without installing them

## Getting Started

This project is a script around a pre-configured Docker Compose setup that connects various LLM-related projects together. It simplifies the initial configuration and can serve as a base for your own customized setup.

## Harbor CLI Reference

### `harbor ln`

Creates a symlink to the `harbor.sh` script in the `/usr/local/bin` directory. This allows you to run the script from any directory.

```bash
# Puts the script in the /usr/local/bin directory
harbor ln
```

### `harbor up <services>`

Starts selected services. See the list of available services here. Run `harbor defaults` to see the default list
of services that will be started.

```bash
# Start default services
harbor up
```

```bash
# ------------------------------
# Docker Compose helpers:


# Start services in the default configuration
harbor up <services>

# Stop all running services
harbor down

# Proxy helpers for compose
harbor ps
harbor logs

# Display CLI help
harbor help

```

## Services Overview

| Service | Option / Default URL | Description |
| --- | --- | --- |
| [Open WebUI](https://docs.openwebui.com/) | `webui` | Extensible, self-hosted interface for AI that adapts to your workflow. |
| [Ollama](https://ollama.com/) | `ollama` |  Ergonomic wrapper around llama.cpp with plenty of QoL features |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | `llamacpp` | LLM inference in C/C++ |
| [SearXNG](https://github.com/searxng/searxng) | `searxng` | A free internet metasearch engine which aggregates results from various search services and databases. |
| [openedai-speech](https://github.com/matatonic/openedai-speech) | `tts` | An OpenAI API compatible text to speech server |
| [litellm](https://docs.litellm.ai/docs/) | `litellm`| LLM API Proxy/Gateway |
| [text-generation-inference](https://github.com/huggingface/text-generation-inference) | `tgi` | A Rust, Python and gRPC server for inference from HuggingFace |
| [lmdeploy](https://lmdeploy.readthedocs.io/en/latest/get_started.html) | `lmdeploy` | A toolkit for deploying, and serving LLMs. |

---

### [Open WebUI](https://docs.openwebui.com/)
Extensible, self-hosted interface for AI that adapts to your workflow. Open WebUI provides plenty of features and QoL goodies for working with LLMs. Notably:
- Model management - create model instances with pre-configured settings, chat with multiple models at once
- Prompt library
- Persistent chat history
- Document RAG

You can configure Open WebUI in three ways:
- Via WebUI itself: changes are saved in the `webui/config.json` file
- Via the `webui/config.json` file: changes are applied after restarting the Harbor
- Via [environment variables](https://docs.openwebui.com/getting-started/env-configuration/): changes are applied after restarting the Harbor


---

### [Ollama](https://ollama.com/)
Ergonomic wrapper around llama.cpp with plenty of QoL features.

You can manage Ollama models right from the [Admin Settings](http://localhost:33801/admin/settings/) in the Open WebUI. The models are stored in the global ollama cache on your local machine.

---

### [llama.cpp](https://github.com/ggerganov/llama.cpp)
LLM inference in C/C++. Allows to bypass Ollama release cycle when needed - to get access to the latest models or features.

Harbor launches llama.cpp server that can be configured via the `llamacpp/.env` file. Downloaded models are stored in the global HuggingFace cache on your local machine. The server can only run one model at a time and must be restarted to switch models.