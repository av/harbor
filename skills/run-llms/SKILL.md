---
name: run-llms
description: Guide for setting up and running local LLMs using Harbor. Use when user wants to run LLMs locally, set up Ollama, Open WebUI, llama.cpp, vLLM, or similar local AI services. Covers full setup from Docker prerequisites through running models, configuration, profiles, tunnels, and advanced features.
---

# Run LLMs Locally with Harbor

Harbor is a containerized LLM toolkit. This skill guides through setup and usage of local LLM infrastructure.

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

First run downloads images (~5-10 min). Wait for healthy output:
```
✔ Container harbor.ollama  Healthy
✔ Container harbor.webui   Healthy
```

Open UI: `harbor open`

First launch requires creating a local admin account.

### Step 4: Pull a Model

```bash
# Recommended small model
harbor pull qwen3:4b

# Verify
harbor ollama list
```

### Step 5: Verify

1. `harbor open` - opens UI
2. Select pulled model from dropdown
3. Send test message

## Core Commands

| Command | Purpose |
|---------|---------|
| `harbor up` | Start services |
| `harbor down` | Stop all services |
| `harbor ps` | Show running services |
| `harbor logs [service]` | Tail logs |
| `harbor open [service]` | Open in browser |
| `harbor url [service]` | Print service URL |
| `harbor pull <model>` | Download model |
| `harbor restart` | Restart stack |

## Model Management

### Ollama Models

```bash
harbor ollama list          # List cached models
harbor ollama pull <model>  # Pull model
harbor ollama rm <model>    # Remove model
harbor ollama run <model>   # Interactive chat
harbor ollama ctx 8192      # Set context length
```

### Pull Sources

```bash
# Ollama registry
harbor pull qwen3:4b
harbor pull llama3.2:3b
harbor pull gemma3:4b

# HuggingFace via Ollama
harbor pull hf.co/bartowski/gemma-2-2b-it-GGUF:Q4_K_M

# llama.cpp from HuggingFace (GGUF)
harbor pull microsoft/Phi-3.5-mini-instruct-gguf:Q4_K_M
```

### HuggingFace Tools

```bash
harbor hf scan-cache           # Show cache status
harbor hf token <token>        # Set token for gated models
harbor hf download user/repo   # Download model
harbor hf find gguf gemma      # Search HF in browser
harbor hf path user/repo       # Find local cache path
```

## Adding Services

### Start Additional Services

```bash
# Add to current stack
harbor up searxng        # Web search
harbor up tts            # Text-to-speech
harbor up comfyui        # Image generation
harbor up llamacpp       # Alternative backend

# Multiple services
harbor up searxng tts llamacpp

# Skip defaults, only specified services
harbor up --no-defaults llamacpp
```

### Configure Defaults

```bash
harbor defaults           # Show default services
harbor defaults add tts   # Add to defaults
harbor defaults rm webui  # Remove from defaults
```

### Available Backends

| Backend | Command | Best For |
|---------|---------|----------|
| Ollama | `harbor ollama model` | Ease of use |
| llama.cpp | `harbor llamacpp model <url>` | GGUF models |
| vLLM | `harbor vllm model user/repo` | Production inference |
| TGI | `harbor tgi model user/repo` | HuggingFace models |
| SGLang | `harbor sglang model user/repo` | Fast inference |

### Backend Configuration Examples

```bash
# llama.cpp
harbor llamacpp model https://huggingface.co/user/repo/blob/main/model.gguf
harbor llamacpp args '-c 4096'

# vLLM
harbor vllm model google/gemma-2-2b-it
harbor vllm args '--max-model-len 4096'

# TGI
harbor tgi model meta-llama/Llama-3.2-3B-Instruct
harbor tgi quant awq
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
harbor env <service>                 # List env vars
harbor env <service> KEY value       # Set env var
```

### Profiles (Save/Load Configurations)

```bash
harbor profile ls                    # List profiles
harbor profile save mysetup          # Save current config
harbor profile use mysetup           # Load profile
harbor profile use <url>             # Load from URL
harbor profile rm mysetup            # Delete profile
```

### Cache Locations

```bash
harbor config ls | grep CACHE        # Show cache paths
harbor size                          # Show disk usage
harbor hf cache /path/to/cache       # Change HF cache
```

## Network & Access

### URLs

```bash
harbor url ollama           # Local URL
harbor url --lan ollama     # LAN URL
harbor url -i ollama        # Docker internal URL
harbor qr webui             # QR code for URL
```

### Tunnels (Internet Access)

```bash
harbor tunnel webui         # Create temporary tunnel
harbor tunnel down          # Stop tunnels
harbor tunnels add webui    # Auto-tunnel on startup
harbor tunnels ls           # List auto-tunnels
```

## Troubleshooting

### Diagnostics

```bash
harbor doctor               # System check
harbor ps                   # Container status
harbor logs                 # All logs
harbor logs -n 1000 ollama  # Extended logs
```

### Container Access

```bash
harbor shell ollama         # Interactive shell
harbor exec ollama <cmd>    # Run command
harbor run litellm --help   # One-off command
```

### Common Fixes

**Services won't start:**
```bash
harbor down
harbor up
```

**Permission errors on volumes (Linux):**
```bash
harbor fixfs
```

**GPU not detected:**
Install NVIDIA Container Toolkit, then restart Docker.

**Reset config:**
```bash
harbor config reset
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
harbor history             # Interactive history
harbor history ls          # List history
harbor history clear       # Clear history
```

### AI Help

```bash
harbor how to filter logs?   # AI-powered help (requires ollama running)
```

### File Search

```bash
harbor find .gguf            # Find GGUF files in caches
harbor find bartowski        # Find files by name
```

### Eject Config

```bash
harbor eject > docker-compose.yml  # Export standalone config
```

### GPU Monitoring

```bash
harbor top                   # nvtop for GPU usage
```

## Service Quick Reference

| Service | Handle | CLI | Purpose |
|---------|--------|-----|---------|
| Open WebUI | `webui` | `harbor webui` | Chat UI |
| Ollama | `ollama` | `harbor ollama` | LLM backend |
| llama.cpp | `llamacpp` | `harbor llamacpp` | GGUF backend |
| vLLM | `vllm` | `harbor vllm` | Production backend |
| SearXNG | `searxng` | - | Web search |
| ComfyUI | `comfyui` | `harbor comfyui` | Image generation |
| n8n | `n8n` | - | Workflow automation |
| LiteLLM | `litellm` | `harbor litellm` | API proxy |
| Aider | `aider` | `harbor aider` | AI coding |
| Jupyter | `jupyter` | `harbor jupyter` | Notebooks |
