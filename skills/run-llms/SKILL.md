---
name: run-llms
description: Comprehensive guide for setting up and running local LLMs using Harbor. Use when user wants to run LLMs locally, set up or troubleshoot Ollama, Open WebUI, llama.cpp, vLLM, SearXNG, Open Terminal, or similar local AI services. Covers full setup from Docker prerequisites through running models, per-service configuration, VRAM optimization, GPU troubleshooting, web search integration, code execution, profiles, tunnels, and advanced features. Includes decision trees for autonomous agent workflows and step-by-step troubleshooting playbooks.
---

# Run LLMs Locally with Harbor

Harbor is a containerized LLM toolkit. This skill enables autonomous setup, configuration, troubleshooting, and operation of local LLM infrastructure.

## Agent Decision Trees

Use these decision trees to determine what action to take for common user requests.

### User wants to run an LLM

```
1. Is Harbor installed?
   → NO: Install Harbor (see Initial Setup)
   → YES: Continue
2. Is Docker running?
   → Run: docker info
   → FAIL: Start Docker daemon, check installation
   → OK: Continue
3. Does the user have a specific model in mind?
   → YES: Determine format (Ollama tag, GGUF, HF safetensors)
     → Ollama tag (e.g. qwen3:4b): harbor pull <model> && harbor up
     → GGUF from HuggingFace: harbor pull <org/repo> && harbor up llamacpp
     → Safetensors/HF model: harbor vllm model <user/repo> && harbor up vllm
   → NO: Recommend a small default: harbor pull qwen3:4b && harbor up
4. Verify: harbor ps → confirm services healthy
5. Open UI: harbor open
```

### User has GPU issues

```
1. Check NVIDIA drivers: nvidia-smi
   → FAIL: User needs to install NVIDIA drivers
   → OK: Continue
2. Check Container Toolkit: docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
   → FAIL: Install NVIDIA Container Toolkit, restart Docker
   → OK: Continue
3. Check service logs: harbor logs <service>  # ⚠️ TAILS INDEFINITELY! (Agents: use `docker logs harbor.<service>` instead)
   → Look for: "CUDA error", "out of memory", "no GPU"
   → OOM: See "Model won't load / OOM" troubleshooting
   → No GPU detected: Check /etc/docker/daemon.json for nvidia runtime
4. Restart: sudo systemctl restart docker && harbor down && harbor up
```

### User wants web search in chat

```
1. Start SearXNG: harbor up searxng
   → SearXNG auto-wires to Open WebUI when both run together
2. If WebUI was already running: harbor restart webui
3. Verify: harbor ps | grep searxng
4. Open UI: harbor open → Web search is now available in chat
```

### User wants to change the model

```
1. Which backend is running?
   → harbor ps → identify running backend
2. Apply correct command:
   → Ollama: harbor pull <model> → select in UI dropdown
   → llama.cpp (single model): harbor llamacpp model <url> → harbor restart llamacpp
   → llama.cpp (router mode): harbor pull <org/repo> → model auto-discovered
   → vLLM: harbor vllm model <user/repo> → harbor restart vllm
3. Verify: docker logs harbor.<backend> → wait for ready message
```

### User wants code execution in chat

```
1. Start Open Terminal: harbor up openterminal
   → Auto-wires to Open WebUI with shared bearer token
2. Verify: harbor ps | grep openterminal
3. Open UI: harbor open → Code blocks now have "Run" button
```

### User wants to expose Harbor to network/internet

```
1. LAN access:
   → harbor url --lan webui → get LAN URL
   → harbor qr webui → QR code for mobile
2. Internet tunnel:
   → harbor tunnel webui → creates cloudflared tunnel
   → Share the generated URL
   → harbor tunnel down → when done
```

## Initial Setup Workflow

1. Check prerequisites
2. Install Harbor CLI
3. Start default services (Ollama + Open WebUI)
4. Pull a model
5. Verify the setup

### Step 1: Check Prerequisites

```bash
docker --version        # Need Docker 20.10+
docker compose version  # Need Docker Compose 2.23.1+
git --version
```

**If Docker missing:**
- Linux: Install via official Docker repo
- macOS: Install Docker Desktop
- Windows: Install Docker Desktop + WSL2 (run all commands in WSL2)

**If Docker Compose too old:**
```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install docker-compose-plugin
```

**Linux permission fix (if docker commands fail):**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### Step 2: Install Harbor

```bash
# Check if installed
harbor --version

# Install if missing
curl https://av.codes/get-harbor.sh | bash
source ~/.bashrc  # or ~/.zshrc
```

Verify:
```bash
harbor doctor  # All checks should pass
```

### Step 3: Start Harbor

```bash
harbor up
```

First run downloads images (may take several minutes). Wait for healthy output:
```
✔ Container harbor.ollama  Healthy
✔ Container harbor.webui   Healthy
```

Open UI: `harbor open`

First launch requires creating a local admin account in the browser.

### Step 4: Pull a Model

```bash
# Recommended small model
harbor pull qwen3:4b

# Verify
harbor ollama list
```

### Step 5: Verify

1. `harbor open` — opens UI in browser
2. Select the pulled model from dropdown
3. Send a test message

## Core Commands

> ⚠️ **CRITICAL WARNING FOR AI AGENTS**: `harbor logs` tails indefinitely by default (passes `-f`). If you use this in your Bash tool, it will hang your execution until timeout. **ALWAYS use `docker logs harbor.<service>` instead** to read logs safely.

| Command | Purpose |
|---------|---------|
| `harbor up [services...]` | Start services (defaults + specified) |
| `harbor up --no-defaults <svc>` | Start only specified services |
| `harbor down` | Stop all services |
| `harbor ps` | Show running services |
| `harbor logs [service]` | ⚠️ TAILS INDEFINITELY (HANGS AGENTS). Use docker logs instead |
| `docker logs harbor.<service>` | Non-tailing logs (SAFE FOR AGENTS) |
| `harbor open [service]` | Open in browser |
| `harbor url [service]` | Print service URL |
| `harbor url --lan <service>` | Print LAN URL |
| `harbor url -i <service>` | Print Docker-internal URL |
| `harbor pull <model\|service>` | Download model or pull Docker image |
| `harbor restart [service]` | Restart service(s) |
| `harbor build <service>` | Build service image |
| `harbor shell <service>` | Interactive shell in container |
| `harbor exec <service> <cmd>` | Run command in container |
| `harbor run <service> <cmd>` | One-off command in fresh container |
| `harbor doctor` | System diagnostics |
| `harbor fixfs` | Fix file system ACLs for service volumes |
| `harbor top` | GPU monitoring via nvtop |
| `harbor size` | Show disk usage |
| `harbor find <pattern>` | Find files in caches |
| `harbor eject` | Export standalone docker-compose config |
| `harbor qr <service>` | Generate QR code for service URL |

## Model Management

### Pull Sources

```bash
# Ollama registry
harbor pull qwen3:4b
harbor pull llama3.2:3b
harbor pull gemma3:4b

# HuggingFace via Ollama (hf.co prefix)
harbor pull hf.co/bartowski/gemma-2-2b-it-GGUF:Q4_K_M

# HuggingFace for llama.cpp / vLLM (org/repo format)
harbor pull microsoft/Phi-3.5-mini-instruct-gguf
harbor pull microsoft/Phi-3.5-mini-instruct-gguf:Q4_K_M
```

Pull routing logic: specs with `/` are tried against HuggingFace first (HEAD request, 5s timeout), then fall through to Ollama if unreachable.

### Cross-Source Model Management

```bash
# List all models across Ollama, HuggingFace, and llama.cpp caches
harbor models ls

# List as JSON for scripting
harbor models ls --json

# Pull (auto-routes to HF or Ollama)
harbor models pull unsloth/Qwen3-4B-Instruct-GGUF

# Remove from all sources
harbor models rm qwen3.5:9b
harbor models rm unsloth/Qwen3-4B-Instruct-GGUF
```

### HuggingFace Tools

```bash
harbor hf scan-cache           # Show cache status
harbor hf token <token>        # Set token for gated models
harbor hf download user/repo   # Download model
harbor hf find gguf gemma      # Search HF in browser
harbor hf path user/repo       # Find local cache path
harbor hf cache                # Show cache location
harbor hf cache /path/to/cache # Change cache location
```

## Service: Ollama

> Handle: `ollama` | Port: 33821 | Default service (starts with `harbor up`)

Ergonomic wrapper around llama.cpp with model management, auto-pull, and OpenAI-compatible API.

### Ollama CLI

```bash
harbor ollama list              # List cached models
harbor ollama ls                # Alias for list
harbor ollama pull <model>      # Pull model from registry
harbor ollama rm <model>        # Remove model
harbor ollama run <model>       # Interactive chat in terminal
harbor ollama cp <src> <dst>    # Copy/alias a model
harbor ollama create -f <file> <name>  # Create from Modelfile
harbor ollama show <model> --modelfile # Show model's Modelfile
harbor ollama ps                # Show currently loaded models
harbor ollama ctx               # Get current context length
harbor ollama ctx <n>           # Set global context length
harbor ollama --help            # Full CLI help
harbor ollama version           # Show Ollama version
harbor ollama serve --help      # Show supported env vars
```

### Ollama Model Sources

**From Ollama registry:**
```bash
harbor pull phi4
harbor pull qwen3:4b
harbor pull llama3.2:3b
```

**From HuggingFace (hf.co prefix):**
```bash
harbor ollama pull hf.co/unsloth/DeepSeek-R1-Distill-Llama-8B-GGUF:Q8_0

# Copy to a shorter alias
harbor ollama cp hf.co/unsloth/DeepSeek-R1-Distill-Llama-8B-GGUF:Q8_0 r1-8b
```

### Ollama Custom Modelfiles

```bash
# Create a Modelfile
touch mymodel.Modelfile

# Edit with your settings (FROM, PARAMETER, SYSTEM, etc.)
# Import into Ollama (run from the directory containing the Modelfile)
harbor ollama create -f mymodel.Modelfile mymodel

# Source from existing model as template
harbor ollama show modelname:latest --modelfile > mymodel.Modelfile

# Test
harbor ollama run mymodel
```

Modelfiles in `$(harbor home)/services/ollama/modelfiles/` can be referenced as:
```bash
harbor ollama create -f /modelfiles/mymodel.Modelfile mymodel
```

### Ollama Context Length

```bash
# Get current global default
harbor ollama ctx

# Set global default (applies to all models)
harbor ollama ctx 8192

# Alternative via env
harbor env ollama OLLAMA_CONTEXT_LENGTH 8192
```

Note: `harbor ollama ctx` syncs to env, but not vice versa.

### Ollama Configuration

```bash
# See all config keys
harbor config ls | grep OLLAMA

# Set version (docker tag)
harbor config set ollama.version 0.3.7-rc5-rocm

# Set env overrides
harbor env ollama OLLAMA_DEBUG 1
harbor env ollama OLLAMA_NUM_PARALLEL 4
```

| Config Key | Default | Purpose |
|------------|---------|---------|
| `OLLAMA_CACHE` | `~/.ollama` | Cache location (absolute or relative to harbor home) |
| `OLLAMA_HOST_PORT` | `33821` | Host port |
| `OLLAMA_VERSION` | `latest` | Docker image tag |
| `OLLAMA_INTERNAL_URL` | `http://ollama:11434` | URL given to connected services (change to use external Ollama) |
| `OLLAMA_DEFAULT_MODELS` | `mxbai-embed-large:latest` | Comma-separated models to pull on startup |
| `OLLAMA_CONTEXT_LENGTH` | `4096` | Global default context length |

### Switching to External Ollama

```bash
# Point all Harbor services to an external Ollama instance
# Use host.docker.internal or 172.17.0.1 instead of localhost
harbor config set ollama.internal_url http://172.17.0.1:11434
```

### Ollama Troubleshooting

**Model loading failures:**
```bash
docker logs harbor.ollama          # Check for errors
# Common: insufficient VRAM → try smaller quant
harbor pull model:q4_k_m    # Instead of larger quant
```

**Slow first inference:** Expected — model is loading into memory. Subsequent requests are fast.

**Context length issues:**
```bash
harbor ollama ctx 4096      # Reduce if OOM
harbor ollama ctx 131072    # Increase for large-context models
```

**Model not found after pull:**
```bash
harbor ollama list           # Verify model exists
harbor restart ollama        # Restart if needed
```

## Service: llama.cpp

> Handle: `llamacpp` | Port: 33831

LLM inference in C/C++. Bypasses Ollama's release cycle for access to latest models and features.

### llama.cpp Modes

**Single-model mode** — set a specific model, server loads it on start:
```bash
harbor llamacpp model https://huggingface.co/user/repo/blob/main/file.gguf
harbor up llamacpp
```

**Router mode** (default when no model specifier set) — auto-discovers all cached GGUF models, loads on demand:
```bash
# Clear model specifier to use router mode
harbor config set llamacpp.model.specifier ""
harbor up llamacpp
# All downloaded GGUFs are available
```

Router mode discovers models from:
- HuggingFace cache (mounted at `/root/.cache/huggingface`)
- Models directory: place GGUFs in `./llamacpp/data/models`
- Preset file: INI at `./llamacpp/data/models.ini`

### llama.cpp Pull Workflow

```bash
# Pull a GGUF model from HuggingFace
harbor pull bartowski/Qwen2.5-Coder-7B-Instruct-GGUF

# Pull with specific quantization
harbor pull unsloth/gemma-4-31B-it-GGUF:Q4_K_M

# Start llama.cpp (router mode auto-discovers the model)
harbor up llamacpp
```

### llama.cpp CLI

```bash
harbor llamacpp model              # Get current model
harbor llamacpp model <hf_url>     # Set model (HuggingFace URL)
harbor llamacpp gguf               # Get current GGUF path
harbor llamacpp gguf /path/to.gguf # Set local GGUF path
harbor llamacpp args               # Get current extra args
harbor llamacpp args '<args>'      # Set extra args
harbor llamacpp models             # List loaded models (when running)
harbor llamacpp build on           # Enable build from source
harbor llamacpp build off          # Disable build from source
harbor llamacpp build ref          # Get current build ref
harbor llamacpp build ref <ref>    # Set build ref (branch/tag/commit)
```

### llama.cpp Configuration

```bash
# Set extra CLI arguments
harbor llamacpp args '-c 4096 -n 512'

# See llama.cpp server help
harbor run llamacpp --server --help

# Access llama.cpp helper tools
harbor exec llamacpp ls
```

| Config Key | Default | Purpose |
|------------|---------|---------|
| `LLAMACPP_CACHE` | `~/.cache/llama.cpp` | Legacy cache path (models now stored in HF cache) |
| `LLAMACPP_HOST_PORT` | `33831` | Host port |
| `LLAMACPP_IMAGE_CPU` | `ghcr.io/ggml-org/llama.cpp:server` | CPU image |
| `LLAMACPP_IMAGE_NVIDIA` | `ghcr.io/ggml-org/llama.cpp:server-cuda` | NVIDIA GPU image |
| `LLAMACPP_IMAGE_ROCM` | `ghcr.io/ggml-org/llama.cpp:server-rocm` | AMD ROCm image |

To override a specific capability image:
```bash
harbor config set llamacpp.image.nvidia ghcr.io/your-org/llama.cpp:server-cuda
```

### llama.cpp Router Mode Details

```bash
# Configure model sources
harbor llamacpp args "--models-dir /app/data/models"
# Or use preset file
harbor llamacpp args "--models-preset /app/data/models.ini"
# Optional limits
harbor llamacpp args "--models-dir /app/data/models --models-max 4 --no-models-autoload"
```

Router API:
```bash
# List known models
curl http://localhost:33831/models

# Load a model
curl -X POST http://localhost:33831/models/load \
  -H "Content-Type: application/json" \
  -d '{"model":"ggml-org/gemma-3-4b-it-GGUF:Q4_K_M"}'
```

### llama.cpp Build from Source

When pre-built images lag behind releases:

```bash
# Enable build from source
harbor llamacpp build on

# Optionally pin to a specific ref
harbor llamacpp build ref b5678

# Build (auto-detects GPU, picks correct Dockerfile)
harbor build llamacpp

# Start as usual
harbor up llamacpp

# Switch back to pre-built
harbor llamacpp build off
harbor pull llamacpp
harbor up llamacpp
```

### llama.cpp with AMD Strix Halo (gfx1151)

AMD Strix Halo is a unified-memory APU requiring special images.

**Image selection:**
```bash
harbor config set llamacpp.image.rocm kyuz0/amd-strix-halo-toolboxes:rocm-7.2
```

Available tags: `rocm-7.2`, `rocm-6.4.4`, `vulkan-radv` (most stable for large models), `vulkan-amdvlk`.

**Mandatory extra args:**
```bash
harbor llamacpp args "llama-server -fa 1 --no-mmap"
```

**Recommended full configuration:**
```bash
harbor llamacpp args "llama-server -fa 1 --no-mmap -ngl 999 -c 65536 --cache-type-k q8_0 --cache-type-v q8_0 --batch-size 4096 --ubatch-size 512"
```

For MoE models, use `--cache-type-k q4_0 --cache-type-v q4_0 --ubatch-size 256`.

### llama.cpp Troubleshooting

**Router mode shows no models:**
```bash
# Need to pull a GGUF model first
harbor pull bartowski/Qwen2.5-Coder-7B-Instruct-GGUF
harbor restart llamacpp
```

**Model fails to load:**
```bash
docker logs harbor.llamacpp            # Check for errors
# Reduce GPU layers or context to fit VRAM
harbor llamacpp args '-c 2048 --n-gpu-layers 20'
harbor restart llamacpp
```

## Service: vLLM

> Handle: `vllm` | Port: 33911

High-throughput, memory-efficient inference engine. Best for production workloads with safetensors/HF models.

### vLLM CLI

```bash
harbor vllm model               # Get current model
harbor vllm model <user/repo>   # Set model
harbor vllm args                 # Get current extra args
harbor vllm args '<args>'        # Set extra args
harbor vllm version              # Get current version
harbor vllm version <tag>        # Set version (docker tag)
harbor run vllm --help           # Show engine CLI help
```

### vLLM Setup

```bash
# Set model
harbor vllm model Qwen/Qwen3.5-4B

# For gated models, set HF token first
harbor hf token <your-token>
harbor vllm model meta-llama/Llama-3.2-8B-Instruct

# Start (Harbor builds custom image with bitsandbytes)
harbor up vllm

# Monitor startup (wait for "Application startup complete")
docker logs harbor.vllm
```

### vLLM VRAM Optimization

These strategies are critical when models don't fit in VRAM. Apply in order of preference:

**1. Reduce context length (most effective):**
```bash
harbor vllm args '--max-model-len 4096'
```

**2. Quantize on load (significant VRAM savings):**
```bash
harbor vllm args '--load-format bitsandbytes --quantization bitsandbytes'
```

**3. Offload layers to CPU:**
```bash
harbor vllm args '--cpu-offload-gb 4'
```

**4. Disable CUDA graphs (saves VRAM spike at load, reduces speed):**
```bash
harbor vllm args '--enforce-eager'
```

**5. Tune GPU memory cap:**
```bash
harbor vllm args '--gpu-memory-utilization 0.85'
```

**6. CPU-only mode (very slow, last resort):**
```bash
harbor vllm args '--device cpu'
```

**Combined example for tight VRAM:**
```bash
harbor vllm args '--max-model-len 4096 --load-format bitsandbytes --quantization bitsandbytes --enforce-eager'
```

### vLLM Configuration

```bash
# Set version
harbor vllm version v0.9.1
harbor vllm version latest

# Set custom image
harbor config set vllm.image custom/vllm

# Force pull latest
docker pull $(harbor config get vllm.image):$(harbor config get vllm.version)

# Set host port
harbor config set vllm.host.port 4090
```

### vLLM Troubleshooting

**OOM on startup:**
```bash
docker logs harbor.vllm  # Look for "OutOfMemoryError"
# Apply VRAM optimization strategies above
harbor vllm args '--max-model-len 2048 --enforce-eager'
harbor restart vllm
```

**Model not loading (gated):**
```bash
harbor hf token <token>   # Set HF token
harbor restart vllm
```

**Slow startup:** Expected — vLLM compiles CUDA graphs on first run. Use `--enforce-eager` to skip (at inference speed cost).

## Service: Open WebUI

> Handle: `webui` | Port: 33801 | Default service (starts with `harbor up`)

Full-featured chat UI with model management, prompt library, persistent history, document RAG, web RAG, tools, and functions.

### Open WebUI Starting

```bash
# Starts automatically with defaults
harbor up

# Or explicitly
harbor up webui

# Pre-pull image
harbor pull webui
```

First launch requires creating an admin account in the browser.

### Open WebUI Auto-Wired Integrations

When started together, these services auto-connect to Open WebUI:

```bash
harbor up searxng          # Web search / Web RAG
harbor up comfyui          # Image generation
harbor up speaches         # TTS / STT
harbor up pipelines        # LLM orchestration pipelines
harbor up metamcp mcpo     # MCP tool servers
harbor up cognee           # Knowledge graph (MCP)
harbor up openterminal     # Terminal + notebook execution
```

### Open WebUI CLI

```bash
harbor webui version              # Get current version
harbor webui version dev-cuda     # Set version (docker tag)
harbor webui version main         # Use main branch
harbor webui name                 # Get UI display name
harbor webui name "My AI"         # Set UI display name
harbor webui secret               # Get JWT secret
harbor webui secret sk-203948     # Set JWT secret
harbor webui log                  # Get log level
harbor webui log DEBUG            # Set log level (DEBUG, INFO, WARNING, ERROR)
```

### Open WebUI Config Override

Harbor assembles config from integration pieces. To override without Harbor resetting:

```bash
# Edit the override file (applied last, always wins)
open $(harbor home)/services/webui/configs/config.override.json
```

### Open WebUI Configuration

| Config Key | Default | Purpose |
|------------|---------|---------|
| `WEBUI_HOST_PORT` | `33801` | Host port |
| `WEBUI_SECRET` | `h@rb0r` | JWT token secret |
| `WEBUI_NAME` | `Harbor` | UI display name |
| `WEBUI_LOG_LEVEL` | `INFO` | Log level |
| `WEBUI_VERSION` | `main` | Docker image tag |
| `HARBOR_WEBUI_IMAGE` | `ghcr.io/open-webui/open-webui:main` | Docker image |

```bash
# Set arbitrary env vars
harbor env webui ENABLE_REALTIME_CHAT_SAVE false
```

### Open WebUI Troubleshooting

**Can't create admin account:** Clear browser cache, try incognito. Check `docker logs harbor.webui`.

**Backend models not showing:** Check Settings → Connections in UI. Verify backend running with `harbor ps`.

**Config changes lost on restart:** Use `config.override.json` instead of the UI settings panel for persistent overrides.

## Service: SearXNG

> Handle: `searxng` | Port: 33811

Metasearch engine that aggregates results from multiple search services. Provides web search / Web RAG to Open WebUI and other frontends.

### SearXNG Setup

```bash
# Start — auto-connects to Open WebUI
harbor up searxng

# If WebUI was already running, restart to pick up connection
harbor restart webui

# Verify
harbor ps | grep searxng
harbor url searxng
```

### SearXNG Auto-Integrations

Auto-connects to: `webui`, `ldr`, `chatui`, `chatnio`, `perplexica`, `anythingllm`

### SearXNG Configuration

```bash
# Point Harbor to an external SearXNG instance
harbor config set searxng.internal_url http://external:8080
```

Config files are in `$(harbor home)/searxng/` (settings.yml, limiter.toml). See SearXNG configuration reference for engine customization.

| Config Key | Default | Purpose |
|------------|---------|---------|
| `SEARXNG_HOST_PORT` | `33811` | Host port |
| `SEARXNG_IMAGE` | `searxng/searxng` | Docker image |
| `SEARXNG_VERSION` | `latest` | Docker image tag |
| `SEARXNG_INTERNAL_URL` | `http://searxng:8080` | URL used by connected services |
| `SEARXNG_WORKSPACE` | `./searxng` | Config files location |

### SearXNG Troubleshooting

**Web search not appearing in WebUI:**
```bash
harbor ps | grep searxng       # Confirm running
docker logs harbor.searxng            # Check for errors
harbor restart webui           # Restart WebUI to pick up connection
```

## Service: Open Terminal

> Handle: `openterminal` | Port: 34771

Remote shell and file-management API for AI agents. Provides terminal + notebook execution capability to Open WebUI.

### Open Terminal Setup

```bash
# Start — auto-wires to Open WebUI
harbor up openterminal

# Start with WebUI explicitly
harbor up webui openterminal

# Check API key
harbor config get openterminal.api.key
```

When started with WebUI, Harbor auto-configures the bearer token and internal URL — no manual setup needed.

### Open Terminal Filesystem

- `/home/user` — Harbor-managed sandbox (default workspace, persists across restarts)
- `/workspace/host` — optional mount of a real host folder (opt-in)
- Docker socket mount is opt-in

### Open Terminal Package Installation

```bash
# Install system packages (space-separated)
harbor config set openterminal.packages "ripgrep fd-find jq"

# Install Python packages (space-separated)
harbor config set openterminal.pip_packages "httpx polars pandas numpy"

# Restart to apply
harbor restart openterminal
```

### Open Terminal Host Workspace Mount

```bash
# Mount a real host folder at /workspace/host
harbor config set openterminal.host.workspace /absolute/path/to/project
harbor restart openterminal
```

### Open Terminal Docker Access

```bash
# Enable Docker socket (trusted environments only)
harbor config set openterminal.docker.socket true
harbor restart openterminal
```

### Open Terminal Configuration

| Config Key | Default | Purpose |
|------------|---------|---------|
| `HARBOR_OPENTERMINAL_HOST_PORT` | `34771` | Host port |
| `HARBOR_OPENTERMINAL_IMAGE` | `ghcr.io/open-webui/open-terminal` | Docker image |
| `HARBOR_OPENTERMINAL_VERSION` | `v0.10.2` | Image version |
| `HARBOR_OPENTERMINAL_WORKSPACE` | `./services/openterminal/data` | Persistent sandbox path |
| `HARBOR_OPENTERMINAL_API_KEY` | `""` (auto-generated) | Bearer token |
| `HARBOR_OPENTERMINAL_PACKAGES` | `""` | System packages to install on start |
| `HARBOR_OPENTERMINAL_PIP_PACKAGES` | `""` | Python packages to install on start |
| `HARBOR_OPENTERMINAL_EXECUTE_TIMEOUT` | `5` | Default wait timeout (seconds) |
| `HARBOR_OPENTERMINAL_ENABLE_TERMINAL` | `true` | Enable interactive terminal sessions |
| `HARBOR_OPENTERMINAL_ENABLE_NOTEBOOKS` | `true` | Enable notebook execution |
| `HARBOR_OPENTERMINAL_HOST_WORKSPACE` | `""` | Host folder mount (opt-in) |
| `HARBOR_OPENTERMINAL_DOCKER_SOCKET` | `false` | Docker socket access (opt-in) |

### Open Terminal Troubleshooting

```bash
docker logs harbor.openterminal                        # Check logs
curl http://localhost:34771/health              # Check health

# Reset sandbox
harbor down openterminal
rm -rf services/openterminal/data
harbor up openterminal
```

## Configuration

### Config Commands

```bash
harbor config ls                     # List all config
harbor config ls | grep OLLAMA       # Filter config
harbor config get webui.host.port    # Get value
harbor config set webui.name "My AI" # Set value
```

### Service-Specific Environment

```bash
harbor env <service>                 # List override env vars
harbor env <service> KEY             # Get a specific var
harbor env <service> KEY value       # Set an env var
```

### Defaults Management

```bash
harbor defaults                  # Show default services
harbor defaults ls               # Alias
harbor defaults add llamacpp     # Add to default services
harbor defaults rm webui         # Remove from defaults
```

### Profiles (Save/Load Configurations)

```bash
harbor profile ls                    # List profiles
harbor profile save mysetup         # Save current config
harbor profile use mysetup           # Load profile
harbor profile use <url>             # Load from remote URL
harbor profile rm mysetup            # Delete profile
```

Profiles are partial — only specify options you want to change. Changes after loading are not auto-saved; use `harbor profile save <name>` to persist.

### Cache Locations

```bash
harbor config ls | grep CACHE        # Show cache paths
harbor size                          # Show disk usage
harbor hf cache                      # Show HF cache location
harbor hf cache /path/to/cache       # Change HF cache location
```

## Network & Access

### URLs

```bash
harbor url webui            # Local URL
harbor url --lan webui      # LAN URL
harbor url -i webui         # Docker internal URL
harbor qr webui             # QR code for mobile
```

### Tunnels (Internet Access)

```bash
harbor tunnel webui         # Create temporary cloudflared tunnel
harbor tunnel down          # Stop tunnels
harbor tunnels add webui    # Auto-tunnel on startup
harbor tunnels ls           # List auto-tunnels
harbor tunnels rm webui     # Remove auto-tunnel
```

## Troubleshooting Playbooks

### Services Won't Start

```bash
# 1. Check container status
harbor ps

# 2. Check for errors in logs
harbor logs <service>  # ⚠️ TAILS INDEFINITELY! (Agents: use `docker logs harbor.<service>` instead)

# 3. Check for crash loops
docker ps -a | grep harbor

# 4. Full restart
harbor down && harbor up

# 5. Check Docker daemon health
docker info

# 6. Fix volume permissions (Linux)
harbor fixfs
```

### No GPU Detected / CUDA Errors

```bash
# 1. Verify NVIDIA drivers installed and working
nvidia-smi

# 2. Verify NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
# If this fails: install nvidia-container-toolkit, then restart Docker

# 3. Check Docker daemon GPU config
cat /etc/docker/daemon.json
# Should contain "nvidia" runtime or default-runtime

# 4. Restart Docker daemon
sudo systemctl restart docker

# 5. Restart Harbor
harbor down && harbor up
```

### Model Won't Load / OOM

```bash
# 1. Check available VRAM
nvidia-smi

# 2. Check model size vs available VRAM

# 3. For Ollama: try smaller quantization
harbor pull model:q4_k_m

# 4. For vLLM: reduce context, quantize, or offload
harbor vllm args '--max-model-len 4096'
harbor vllm args '--load-format bitsandbytes --quantization bitsandbytes'
harbor vllm args '--cpu-offload-gb 4'
harbor vllm args '--enforce-eager'

# 5. For llama.cpp: reduce context or GPU layers
harbor llamacpp args '-c 2048 --n-gpu-layers 20'

# 6. Restart the backend
harbor restart <backend>
```

### Can't Access UI / Connection Refused

```bash
# 1. Confirm containers are running
harbor ps

# 2. Get correct URL
harbor url webui

# 3. Check port conflicts
ss -tlnp | grep 33801

# 4. Try direct access
harbor open
# Or navigate to http://localhost:33801
```

### Model Not Showing in UI

```bash
# 1. Confirm model exists (for Ollama)
harbor ollama list

# 2. Refresh the Open WebUI page in browser

# 3. Check Open WebUI connections
# Settings → Connections in the UI

# 4. Check for connection errors
docker logs harbor.webui

# 5. Restart WebUI if needed
harbor restart webui
```

### Web Search Not Working

```bash
# 1. Confirm SearXNG is running
harbor ps | grep searxng

# 2. Check SearXNG logs
docker logs harbor.searxng

# 3. If SearXNG started after WebUI, restart WebUI
harbor restart webui

# 4. Verify SearXNG is accessible
harbor url searxng
```

### Slow or Hanging Inference

```bash
# 1. Check GPU utilization
harbor top

# 2. Check if model is loading (first inference is slow)
docker logs harbor.<backend>

# 3. For Ollama: check if multiple models are loaded
harbor ollama ps

# 4. For vLLM: check if CUDA graphs are compiling
docker logs harbor.vllm
# Wait for "Application startup complete"

# 5. Check for CPU fallback (no GPU detected)
docker logs harbor.<backend> | grep -i "cpu\|gpu\|cuda"
```

## Common Workflows

### Run a Small Model Quickly

```bash
harbor up
harbor pull qwen3:4b
harbor open
# → Select model in UI dropdown, start chatting
```

### Run a Large Model with Limited VRAM (vLLM + Quantization)

```bash
# Set HF token if model is gated
harbor hf token <token>

# Set model
harbor vllm model meta-llama/Llama-3.2-8B-Instruct

# Apply VRAM optimizations
harbor vllm args '--max-model-len 4096 --load-format bitsandbytes --quantization bitsandbytes'

# Start
harbor up vllm

# Monitor startup
docker logs harbor.vllm  # Wait for "Application startup complete"
```

### Set Up Web-Augmented Chat

```bash
# Start SearXNG (auto-connects to Open WebUI)
harbor up searxng

# Open UI
harbor open
# → Web search is now available in chat
```

### Run llama.cpp with a Specific GGUF

```bash
# Pull the model
harbor pull bartowski/Qwen2.5-Coder-7B-Instruct-GGUF

# Start llama.cpp (router mode auto-discovers the model)
harbor up llamacpp

# Open UI
harbor open
# → Select the GGUF model from dropdown
```

### Enable Code Execution in Chat

```bash
# Start Open Terminal (auto-wires to Open WebUI)
harbor up openterminal

# Open UI
harbor open
# → Code blocks now have "Run" button
```

### Switch Between Backends

```bash
# Stop current backend
harbor down vllm

# Start different backend
harbor up llamacpp

# Open WebUI auto-discovers new backend
harbor open
```

### Save and Restore Configuration

```bash
# Save current config as a profile
harbor profile save my-dev-setup

# Later, restore
harbor profile use my-dev-setup

# Import from URL
harbor profile use https://example.com/path/to/profile.env
```

### Expose to Local Network

```bash
# Get LAN URL
harbor url --lan webui

# Generate QR code for mobile
harbor qr webui
```

### Create a Temporary Internet Tunnel

```bash
# Create cloudflared tunnel
harbor tunnel webui
# Share the generated URL

# When done
harbor tunnel down
```

### Full Setup with Web Search + Code Execution

```bash
harbor up searxng openterminal
harbor pull qwen3:4b
harbor open
# → Chat with web search and code execution enabled
```

## Advanced Features

### Aliases

```bash
harbor alias set myenv 'code $(harbor home)/.env'
harbor run myenv
harbor alias ls
harbor alias rm myenv
```

### History

```bash
harbor history             # Interactive history browser
harbor history ls          # List history
harbor history clear       # Clear history
```

### AI Help

```bash
harbor how to filter logs?   # AI-powered help (requires Ollama running)
```

### File Search

```bash
harbor find .gguf            # Find GGUF files in caches
harbor find bartowski        # Find files by name
```

### Eject Config

```bash
harbor eject > docker-compose.yml  # Export standalone compose config
```

### GPU Monitoring

```bash
harbor top                   # nvtop for GPU usage
```

## Available Backends Quick Reference

| Backend | Handle | Set Model | Best For |
|---------|--------|-----------|----------|
| Ollama | `ollama` | `harbor pull <model>` | Ease of use, Ollama registry |
| llama.cpp | `llamacpp` | `harbor llamacpp model <url>` | GGUF models, bleeding edge |
| vLLM | `vllm` | `harbor vllm model <user/repo>` | Production inference, HF models |
| TGI | `tgi` | `harbor tgi model <user/repo>` | HuggingFace ecosystem |
| SGLang | `sglang` | `harbor sglang model <user/repo>` | Fast inference |

## Service Handle Reference

| Service | Handle | Port | CLI | Purpose |
|---------|--------|------|-----|---------|
| Open WebUI | `webui` | 33801 | `harbor webui` | Chat UI (default) |
| Ollama | `ollama` | 33821 | `harbor ollama` | LLM backend (default) |
| llama.cpp | `llamacpp` | 33831 | `harbor llamacpp` | GGUF backend |
| vLLM | `vllm` | 33911 | `harbor vllm` | Production backend |
| SearXNG | `searxng` | 33811 | — | Web search |
| Open Terminal | `openterminal` | 34771 | — | Terminal + notebooks |
| ComfyUI | `comfyui` | — | `harbor comfyui` | Image generation |
| LiteLLM | `litellm` | — | `harbor litellm` | API proxy |
| TGI | `tgi` | — | `harbor tgi` | HuggingFace backend |
| SGLang | `sglang` | — | `harbor sglang` | Fast inference backend |
| Aider | `aider` | — | `harbor aider` | AI coding |
| n8n | `n8n` | — | — | Workflow automation |
| Jupyter | `jupyter` | — | `harbor jupyter` | Notebooks |
| Speaches | `speaches` | — | — | TTS / STT |

## Environment Variable Quick Reference

All variables below can be queried/set with `harbor config get/set <key>` (using dot notation) or found in `harbor config ls`.

| Variable | Default | Service | Purpose |
|----------|---------|---------|---------|
| `OLLAMA_CACHE` | `~/.ollama` | ollama | Model cache location |
| `OLLAMA_HOST_PORT` | `33821` | ollama | Host port |
| `OLLAMA_VERSION` | `latest` | ollama | Docker tag |
| `OLLAMA_INTERNAL_URL` | `http://ollama:11434` | ollama | URL for connected services |
| `OLLAMA_DEFAULT_MODELS` | `mxbai-embed-large:latest` | ollama | Models to pull on startup |
| `OLLAMA_CONTEXT_LENGTH` | `4096` | ollama | Global default context |
| `LLAMACPP_CACHE` | `~/.cache/llama.cpp` | llamacpp | Legacy cache path |
| `LLAMACPP_HOST_PORT` | `33831` | llamacpp | Host port |
| `LLAMACPP_IMAGE_CPU` | `ghcr.io/ggml-org/llama.cpp:server` | llamacpp | CPU image |
| `LLAMACPP_IMAGE_NVIDIA` | `ghcr.io/ggml-org/llama.cpp:server-cuda` | llamacpp | NVIDIA image |
| `LLAMACPP_IMAGE_ROCM` | `ghcr.io/ggml-org/llama.cpp:server-rocm` | llamacpp | ROCm image |
| `WEBUI_HOST_PORT` | `33801` | webui | Host port |
| `WEBUI_SECRET` | `h@rb0r` | webui | JWT secret |
| `WEBUI_NAME` | `Harbor` | webui | UI display name |
| `WEBUI_LOG_LEVEL` | `INFO` | webui | Log level |
| `WEBUI_VERSION` | `main` | webui | Docker tag |
| `HARBOR_WEBUI_IMAGE` | `ghcr.io/open-webui/open-webui:main` | webui | Docker image |
| `SEARXNG_HOST_PORT` | `33811` | searxng | Host port |
| `SEARXNG_IMAGE` | `searxng/searxng` | searxng | Docker image |
| `SEARXNG_VERSION` | `latest` | searxng | Docker tag |
| `SEARXNG_INTERNAL_URL` | `http://searxng:8080` | searxng | URL for connected services |
| `SEARXNG_WORKSPACE` | `./searxng` | searxng | Config files location |
| `HARBOR_OPENTERMINAL_HOST_PORT` | `34771` | openterminal | Host port |
| `HARBOR_OPENTERMINAL_API_KEY` | `""` | openterminal | Bearer token (auto-generated) |
| `HARBOR_OPENTERMINAL_PACKAGES` | `""` | openterminal | System packages |
| `HARBOR_OPENTERMINAL_PIP_PACKAGES` | `""` | openterminal | Python packages |
| `HARBOR_OPENTERMINAL_EXECUTE_TIMEOUT` | `5` | openterminal | Exec wait timeout (seconds) |
| `HARBOR_OPENTERMINAL_ENABLE_TERMINAL` | `true` | openterminal | Interactive terminal |
| `HARBOR_OPENTERMINAL_ENABLE_NOTEBOOKS` | `true` | openterminal | Notebook execution |
| `HARBOR_OPENTERMINAL_HOST_WORKSPACE` | `""` | openterminal | Host folder mount |
| `HARBOR_OPENTERMINAL_DOCKER_SOCKET` | `false` | openterminal | Docker access |
