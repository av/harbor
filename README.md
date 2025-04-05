![Harbor project logo](https://github.com/av/harbor/raw/main/docs/harbor-2.png)

[![GitHub Tag](https://img.shields.io/github/v/tag/av/harbor)](https://github.com/av/harbor/releases)
[![NPM Version](https://img.shields.io/npm/v/%40avcodes%2Fharbor?labelColor=red&color=white)](https://www.npmjs.com/package/@avcodes/harbor)
[![PyPI - Version](https://img.shields.io/pypi/v/llm-harbor?labelColor=blue)](https://pypi.org/project/llm-harbor/)
![GitHub repo size](https://img.shields.io/github/repo-size/av/harbor)
![GitHub repo file or directory count](https://img.shields.io/github/directory-file-count/av/harbor?type=file&extension=yml&label=compose%20files&color=orange)
[![Visitors](https://api.visitorbadge.io/api/visitors?path=av%2Fharbor&countColor=%23263759&style=flat)](https://visitorbadge.io/status?path=av%2Fharbor)
![GitHub language count](https://img.shields.io/github/languages/count/av/harbor)
[![Discord](https://img.shields.io/badge/Discord-Harbor-blue?logo=discord&logoColor=white)](https://discord.gg/8nDRphrhSF)
![Harbor Ko-fi](https://img.shields.io/badge/Ko--fi-white?style=social&logo=kofi)

Effortlessly run LLM backends, APIs, frontends, and services with one command.

Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease.

![Screenshot of Harbor CLI and App together](https://github.com/av/harbor/wiki/harbor-app-3.png)

## What can Harbor do?

![Diagram outlining Harbor's service structure](https://raw.githubusercontent.com/wiki/av/harbor/harbor-arch-diag.png)

| What | Overview | Links |
|---|---|---|
|Local LLMs | Run LLMs and related services locally, with no or minimal configuration, typically in a single command or click. | [Harbor CLI](https://github.com/av/harbor/wiki/3.-Harbor-CLI-Reference), [Harbor App](https://github.com/av/harbor/wiki/1.1-Harbor-App)|
|Cutting Edge Inference|Harbor supports most of the major inference engines as well as a few of the lesser-known ones. | [Inference Backends](#backends) |
| Tool Use | Enjoy the benefits of MCP ecosystem, extend it to your use-cases | [`Harbor Tools`](./docs/1.2-Tools) |
|Generate Images| ComfyUI + Flux + Open WebUI integration. | [`harbor up comfyui`](./docs/2.1.2-Frontend&colon-ComfyUI) |
| Local Perplexity | Harbor includes SearXNG that is pre-connected to a lot of services out of the box. Connect your LLM to the Web. | [`harbor up searxng`](./docs/2.3.1-Satellite&colon-SearXNG) |
| LLM Workflows | Harbor includes multiple services for build LLM-based data and chat workflows: [Dify](./docs/2.3.3-Satellite&colon-Dify), [LitLytics](./docs/2.3.21-Satellite&colon-LitLytics), [n8n](./docs/2.3.23-Satellite&colon-n8n), [Open WebUI Pipelines](./docs/2.3.25-Satellite&colon-Open-WebUI-Pipelines), [FloWise](./docs/2.3.31-Satellite&colon-Flowise), [LangFlow](./docs/2.3.32-Satellite&colon-LangFlow) | [`harbor up dify`](./docs/2.3.3-Satellite&colon-Dify) |
| Talk to your LLM | Setup voice chats with your LLM in a single command. Open WebUI + Speaches  | [`harbor up speaches`](./docs/2.2.14-Backend&colon-Speaches) |
| Chat from the phone | You can access Harbor services from your phone with a QR code. Easily get links for local, LAN or Docker access. | [`harbor qr`](./docs/3.-Harbor-CLI-Reference#harbor-qr), [`harbor url`](./docs/3.-Harbor-CLI-Reference#harbor-url-service) |
| Chat from anywhere | Harbor includes a built-in tunneling service to expose your Harbor to the internet. | [`harbor tunnel`](./docs/3.-Harbor-CLI-Reference#harbor-tunnels) |
| LLM Scripting | [Harbor Boost](./docs/5.2.-Harbor-Boost) allows you to [easily script workflows](./docs/5.2.1.-Harbor-Boost-Custom-Modules) and interactions with downstream LLMs. | [`harbor up boost`](./docs/5.2.-Harbor-Boost) |
| Config Profiles | Save and manage configuration profiles for different scenarios. For example - save [llama.cpp](./docs/2.2.2-Backend&colon-llama.cpp) args for different models and contexts and switch between them easily. | [`harbor profile`](./docs/3.-Harbor-CLI-Reference#harbor-profile), [Harbor App](https://github.com/av/harbor/wiki/1.1-Harbor-App) |
| Command History | Harbor keeps a local-only history of recent commands. Look up and re-run easily, standalone from the system shell history. | [`harbor history`](./docs/3.-Harbor-CLI-Reference#harbor-history) |
| Eject | Ready to move to your own setup? Harbor will give you a docker-compose file replicating your setup. | [`harbor eject`](./docs/3.-Harbor-CLI-Reference#harbor-eject) |
|  | Harbor includes a lot more services and features. Check the [Documentation](#documentation) links below. | |


## Services

##### UIs
[Open WebUI](https://github.com/av/harbor/wiki/2.1.1-Frontend:-Open-WebUI) ⦁︎
[ComfyUI](https://github.com/av/harbor/wiki/2.1.2-Frontend:-ComfyUI) ⦁︎
[LibreChat](https://github.com/av/harbor/wiki/2.1.3-Frontend:-LibreChat) ⦁︎
[HuggingFace ChatUI](https://github.com/av/harbor/wiki/2.1.4-Frontend:-ChatUI) ⦁︎
[Lobe Chat](https://github.com/av/harbor/wiki/2.1.5-Frontend:-Lobe-Chat) ⦁︎
[Hollama](https://github.com/av/harbor/wiki/2.1.6-Frontend:-hollama) ⦁︎
[parllama](https://github.com/av/harbor/wiki/2.1.7-Frontend:-parllama) ⦁︎
[BionicGPT](https://github.com/av/harbor/wiki/2.1.8-Frontend:-BionicGPT) ⦁︎
[AnythingLLM](https://github.com/av/harbor/wiki/2.1.9-Frontend:-AnythingLLM) ⦁︎
[Chat Nio](https://github.com/av/harbor/wiki/2.1.10-Frontend:-Chat-Nio) ⦁︎
[mikupad](https://github.com/av/harbor/wiki/2.1.11-Frontend:-Mikupad) ⦁︎
[oterm](https://github.com/av/harbor/wiki/2.1.12-Frontend-oterm)

##### Backends
[Ollama](https://github.com/av/harbor/wiki/2.2.1-Backend:-Ollama) ⦁︎
[llama.cpp](https://github.com/av/harbor/wiki/2.2.2-Backend:-llama.cpp) ⦁︎
[vLLM](https://github.com/av/harbor/wiki/2.2.3-Backend:-vLLM) ⦁︎
[TabbyAPI](https://github.com/av/harbor/wiki/2.2.4-Backend:-TabbyAPI) ⦁︎
[Aphrodite Engine](https://github.com/av/harbor/wiki/2.2.5-Backend:-Aphrodite-Engine) ⦁︎
[mistral.rs](https://github.com/av/harbor/wiki/2.2.6-Backend:-mistral.rs) ⦁︎
[openedai-speech](https://github.com/av/harbor/wiki/2.2.7-Backend:-openedai-speech) ⦁︎
[Speaches](https://github.com/av/harbor/wiki/2.2.14-Backend:-Speaches) ⦁︎
[Parler](https://github.com/av/harbor/wiki/2.2.8-Backend:-Parler) ⦁︎
[text-generation-inference](https://github.com/av/harbor/wiki/2.2.9-Backend:-text-generation-inference) ⦁︎
[LMDeploy](https://github.com/av/harbor/wiki/2.2.10-Backend:-lmdeploy) ⦁︎
[AirLLM](https://github.com/av/harbor/wiki/2.2.11-Backend:-AirLLM) ⦁︎
[SGLang](https://github.com/av/harbor/wiki/2.2.12-Backend:-SGLang) ⦁︎
[KTransformers](https://github.com/av/harbor/wiki/2.2.13-Backend:-KTransformers) ⦁︎
[Nexa SDK](https://github.com/av/harbor/wiki/2.2.15-Backend:-Nexa-SDK) ⦁︎
[KoboldCpp](https://github.com/av/harbor/wiki/2.2.16-Backend:-KoboldCpp)

##### Satellites
[Harbor Bench](https://github.com/av/harbor/wiki/5.1.-Harbor-Bench) ⦁︎
[Harbor Boost](https://github.com/av/harbor/wiki/5.2.-Harbor-Boost) ⦁︎
[SearXNG](https://github.com/av/harbor/wiki/2.3.1-Satellite:-SearXNG) ⦁︎
[Perplexica](https://github.com/av/harbor/wiki/2.3.2-Satellite:-Perplexica) ⦁︎
[Dify](https://github.com/av/harbor/wiki/2.3.3-Satellite:-Dify) ⦁︎
[Plandex](https://github.com/av/harbor/wiki/2.3.4-Satellite:-Plandex) ⦁︎
[LiteLLM](https://github.com/av/harbor/wiki/2.3.5-Satellite:-LiteLLM) ⦁︎
[LangFuse](https://github.com/av/harbor/wiki/2.3.6-Satellite:-langfuse) ⦁︎
[Open Interpreter](https://github.com/av/harbor/wiki/2.3.7-Satellite:-Open-Interpreter) ⦁
︎[cloudflared](https://github.com/av/harbor/wiki/2.3.8-Satellite:-cloudflared) ⦁︎
[cmdh](https://github.com/av/harbor/wiki/2.3.9-Satellite:-cmdh) ⦁︎
[fabric](https://github.com/av/harbor/wiki/2.3.10-Satellite:-fabric) ⦁︎
[txtai RAG](https://github.com/av/harbor/wiki/2.3.11-Satellite:-txtai-RAG) ⦁︎
[TextGrad](https://github.com/av/harbor/wiki/2.3.12-Satellite:-TextGrad) ⦁︎
[Aider](https://github.com/av/harbor/wiki/2.3.13-Satellite:-aider) ⦁︎
[aichat](https://github.com/av/harbor/wiki/2.3.14-Satellite:-aichat) ⦁︎
[omnichain](https://github.com/av/harbor/wiki/2.3.16-Satellite:-omnichain) ⦁︎
[lm-evaluation-harness](https://github.com/av/harbor/wiki/2.3.17-Satellite:-lm-evaluation-harness) ⦁︎
[JupyterLab](https://github.com/av/harbor/wiki/2.3.18-Satellite:-JupyterLab) ⦁︎
[ol1](https://github.com/av/harbor/wiki/2.3.19-Satellite:-ol1) ⦁︎
[OpenHands](https://github.com/av/harbor/wiki/2.3.20-Satellite:-OpenHands) ⦁︎
[LitLytics](https://github.com/av/harbor/wiki/2.3.21-Satellite:-LitLytics) ⦁︎
[Repopack](https://github.com/av/harbor/wiki/2.3.22-Satellite:-Repopack) ⦁︎
[n8n](https://github.com/av/harbor/wiki/2.3.23-Satellite:-n8n) ⦁︎
[Bolt.new](https://github.com/av/harbor/wiki/2.3.24-Satellite:-Bolt.new) ⦁︎
[Open WebUI Pipelines](https://github.com/av/harbor/wiki/2.3.25-Satellite:-Open-WebUI-Pipelines) ⦁︎
[Qdrant](https://github.com/av/harbor/wiki/2.3.26-Satellite:-Qdrant) ⦁︎
[K6](https://github.com/av/harbor/wiki/2.3.27-Satellite:-K6) ⦁︎
[Promptfoo](https://github.com/av/harbor/wiki/2.3.28-Satellite:-Promptfoo) ⦁︎
[Webtop](https://github.com/av/harbor/wiki/2.3.29-Satellite:-Webtop) ⦁︎
[OmniParser](https://github.com/av/harbor/wiki/2.3.30-Satellite:-OmniParser) ⦁︎
[Flowise](https://github.com/av/harbor/wiki/2.3.31-Satellite:-Flowise) ⦁︎
[Langflow](https://github.com/av/harbor/wiki/2.3.32-Satellite:-LangFlow) ⦁︎
[OptiLLM](https://github.com/av/harbor/wiki/2.3.33-Satellite:-OptiLLM) ⦁︎
[Morphic](https://github.com/av/harbor/wiki/2.3.34-Satellite-Morphic) ⦁︎
[SQL Chat](https://github.com/av/harbor/wiki/2.3.35-Satellite-SQL-Chat) ⦁︎
[gptme](https://github.com/av/harbor/wiki/2.3.36-Satellite-gptme) ⦁︎
[traefik](https://github.com/av/harbor/wiki/2.3.37-Satellite-traefik) ⦁︎
[Latent Scope](https://github.com/av/harbor/wiki/2.3.38-Satellite-Latent-Scope) ⦁︎
[RAGLite](https://github.com/av/harbor/wiki/2.3.39-Satellite-RAGLite) ⦁︎
[llama-swap](https://github.com/av/harbor/wiki/2.3.40-Satellite-llamaswap) ⦁︎
[LibreTranslate](https://github.com/av/harbor/wiki/2.3.41-Satellite-LibreTranslate) ⦁︎
[MetaMCP](https://github.com/av/harbor/wiki/2.3.42-Satellite-MetaMCP) ⦁︎
[mcpo](https://github.com/av/harbor/wiki/2.3.43-Satellite-mcpo)


See [services documentation](https://github.com/av/harbor/wiki/2.-Services) for a brief overview of each.

## CLI Tour

```bash
# Run Harbor with default services:
# Open WebUI and Ollama
harbor up

# Run Harbor with additional services
# Running SearXNG automatically enables Web RAG in Open WebUI
harbor up searxng

# Speaches includes OpenAI-compatible SST and TTS
# and connected to Open WebUI out of the box
harbor up speaches

# Run additional/alternative LLM Inference backends
# Open Webui is automatically connected to them.
harbor up llamacpp tgi litellm vllm tabbyapi aphrodite sglang ktransformers

# Run different Frontends
harbor up librechat chatui bionicgpt hollama

# Get a free quality boost with
# built-in optimizing proxy
harbor up boost

# Use FLUX in Open WebUI in one command
harbor up comfyui

# Use custom models for supported backends
harbor llamacpp model https://huggingface.co/user/repo/model.gguf

# Access service CLIs without installing them
# Caches are shared between services where possible
harbor hf scan-cache
harbor hf download google/gemma-2-2b-it
harbor ollama list

# Shortcut to HF Hub to find the models
harbor hf find gguf gemma-2
# Use HFDownloader and official HF CLI to download models
harbor hf dl -m google/gemma-2-2b-it -c 10 -s ./hf
harbor hf download google/gemma-2-2b-it

# Where possible, cache is shared between the services
harbor tgi model google/gemma-2-2b-it
harbor vllm model google/gemma-2-2b-it
harbor aphrodite model google/gemma-2-2b-it
harbor tabbyapi model google/gemma-2-2b-it-exl2
harbor mistralrs model google/gemma-2-2b-it
harbor opint model google/gemma-2-2b-it
harbor sglang model google/gemma-2-2b-it

# Convenience tools for docker setup
harbor logs llamacpp
harbor exec llamacpp ./scripts/llama-bench --help
harbor shell vllm

# Tell your shell exactly what you think about it
harbor opint
harbor aider
harbor aichat
harbor cmdh

# Use fabric to LLM-ify your linux pipes
cat ./file.md | harbor fabric --pattern extract_extraordinary_claims | grep "LK99"

# Open services from the CLI
harbor open webui
harbor open llamacpp
# Print yourself a QR to quickly open the
# service on your phone
harbor qr
# Feeling adventurous? Expose your Harbor
# to the internet
harbor tunnel

# Config management
harbor config list
harbor config set webui.host.port 8080

# Create and manage config profiles
harbor profile save l370b
harbor profile use default

# Lookup recently used harbor commands
harbor history

# Eject from Harbor into a standalone Docker Compose setup
# Will export related services and variables into a standalone file.
harbor eject searxng llamacpp > docker-compose.harbor.yml

# Run a built-in LLM benchmark with
# your own tasks
harbor bench run

# Gimmick/Fun Area

# Argument scrambling, below commands are all the same as above
# Harbor doesn't care if it's "vllm model" or "model vllm", it'll
# figure it out.
harbor model vllm
harbor vllm model

harbor config get webui.name
harbor get config webui_name

harbor tabbyapi shell
harbor shell tabbyapi

# 50% gimmick, 50% useful
# Ask harbor about itself
harbor how to ping ollama container from the webui?
```

## Harbor App Demo

https://github.com/user-attachments/assets/a5cd2ef1-3208-400a-8866-7abd85808503

In the demo, Harbor App is used to launch a default stack with [Ollama](./2.2.1-Backend:-Ollama) and [Open WebUI](./2.1.1-Frontend:-Open-WebUI) services. Later, [SearXNG](./2.3.1-Satellite:-SearXNG) is also started, and WebUI can connect to it for the Web RAG right out of the box. After that, [Harbor Boost](./5.2.-Harbor-Boost) is also started and connected to the WebUI automatically to induce more creative outputs. As a final step, Harbor config is adjusted in the App for the [`klmbr`](./5.2.-Harbor-Boost#klmbr---boost-llm-creativity) module in the [Harbor Boost](./5.2.-Harbor-Boost), which makes the output unparsable for the LLM (yet still undetstandable for humans).

## Documentation

- [Installing Harbor](https://github.com/av/harbor/wiki/1.0.-Installing-Harbor)<br/>
  Guides to install Harbor CLI and App
- [Harbor User Guide](https://github.com/av/harbor/wiki/1.-Harbor-User-Guide)<br/>
  High-level overview of working with Harbor
- [Harbor App](https://github.com/av/harbor/wiki/1.1-Harbor-App)<br/>
  Overview and manual for the Harbor companion application
- [Harbor Services](https://github.com/av/harbor/wiki/2.-Services)<br/>
  Catalog of services available in Harbor
- [Harbor CLI Reference](https://github.com/av/harbor/wiki/3.-Harbor-CLI-Reference)<br/>
  Read more about Harbor CLI commands and options.
  Read about supported services and the ways to configure them.
- [Compatibility](https://github.com/av/harbor/wiki/4.-Compatibility)<br/>
  Known compatibility issues between the services and models as well as possible workarounds.
- [Harbor Bench](https://github.com/av/harbor/wiki/5.1.-Harbor-Bench)<br/>
  Documentation for the built-in LLM benchmarking service.
- [Harbor Boost](https://github.com/av/harbor/wiki/5.2.-Harbor-Boost)<br/>
  Documentation for the built-in LLM optimiser proxy.
- [Harbor Compose Setup](https://github.com/av/harbor/wiki/6.-Harbor-Compose-Setup)<br/>
  Read about the way Harbor uses Docker Compose to manage services.
- [Adding A New Service](https://github.com/av/harbor/wiki/7.-Adding-A-New-Service)<br/>
  Documentation on bringing more services into the Harbor toolkit.
- [Join our Discord](https://discord.gg/8nDRphrhSF0)<br/>
  Get help, share your experience, and contribute to the project.

## Why?

- If you're comfortable with Docker and Linux administration - you likely don't need Harbor to manage your local LLM environment. However, while growing it - you're also likely to eventually arrive to a similar solution. I know this for a fact, since that's exactly how Harbor came to be.
- Harbor is not designed as a deployment solution, but rather as a helper for the local LLM development environment. It's a good starting point for experimenting with LLMs and related services.
- Workflow/setup centralisation - you can be sure where to find a specific config or service, logs, data and configuration files.
- Convenience factor - single CLI with a lot of services and features, accessible from anywhere on your host.

## Supporters

![@av's wife](https://ui-avatars.com/api/?size=32&name=KN&rounded=true&background=ffaaaa&color=ff4444)
![@burnth3heretic](https://ui-avatars.com/api/?size=32&name=BTH&rounded=true)