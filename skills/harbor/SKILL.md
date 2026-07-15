---
name: harbor
description: CLI toolkit for managing containerized LLM services. Use when the user wants to start, stop, configure, or manage AI/LLM services like Ollama, Open WebUI, llama.cpp, vLLM, LiteLLM, ComfyUI, and 250+ others. Triggers on requests to "run a model", "start ollama", "set up an LLM", "configure harbor", "manage services", "check what's running", "harbor launch", Boost custom workflows, or any Docker-based AI service management task.
allowed-tools: Bash(harbor:*), Bash(docker:*)
---

# Harbor CLI

Harbor is a containerized LLM toolkit — a Docker Compose project with a CLI for managing 250+ AI services (backends, frontends, APIs, tools). Install via `npm i -g @avcodes/harbor` or clone from GitHub.

## Core Workflow

1. **Start services**: `harbor up ollama webui`
2. **Check status**: `harbor ps`
3. **Configure**: `harbor config set OLLAMA_MODEL llama3.2`
4. **Use**: `harbor open webui` or `harbor url webui`
5. **Stop**: `harbor down`

```bash
harbor up ollama webui
harbor ps
harbor open webui
harbor down
```

## Service Lifecycle

```bash
# Start / stop
harbor up <service> [service...]      # Start service(s)
harbor up --tail                       # Start and tail logs
harbor up --open                       # Start and open in browser
harbor up --no-defaults                # Start without default services
harbor down                            # Stop and remove all containers
harbor restart [service]               # Down then up

# Inspect
harbor ps                              # List running containers
harbor logs <service>                  # Tail logs (WARNING: hangs in non-interactive shells)
harbor stats                           # Resource usage statistics

# Build / pull
harbor build <service>                 # Build a service image
harbor pull <service>                  # Pull latest Docker images
harbor pull <model>                    # Pull Ollama or llama.cpp model

# Execute
harbor exec <service> <cmd>            # Run command in running container
harbor shell <service>                 # Interactive shell in container
harbor run <service> [cmd]             # One-off command in new container
harbor run <alias>                     # Run a saved alias
harbor attach <service>                # Attach to running container
```

## Configuration

Harbor uses a layered config system. **Never edit `.env` directly.**

```bash
# Global config
harbor config ls                       # List all config values
harbor config get <KEY>                # Get a value
harbor config set <KEY> <VALUE>        # Set a value
harbor config unset <KEY>              # Remove a value
harbor config search <query>           # Search keys and values
harbor config reset                    # Reset to defaults
harbor config update                   # Merge upstream default.env changes

# Per-service environment overrides
harbor env <service>                   # List override vars
harbor env <service> <key>             # Get a specific var
harbor env <service> <key> <value>     # Set a specific var
harbor env <service> unset <key>       # Remove a specific var
```

### Common Config Keys

```bash
# Default model for a service
harbor config set HARBOR_OLLAMA_MODEL llama3.2
harbor config set HARBOR_LLAMACPP_MODEL "bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"
harbor config set HARBOR_VLLM_MODEL "Qwen/Qwen2.5-3B-Instruct"

# Default services started with bare "harbor up"
harbor defaults ls
harbor defaults add ollama
harbor defaults add webui
harbor defaults rm webui
```

## Service Discovery

```bash
harbor ls                              # List all 250+ available services
harbor ls --active                     # List only active/configured services
harbor url <service>                   # Get localhost URL
harbor url --lan <service>             # Get LAN-accessible URL
harbor url --internal <service>        # Get Docker-internal URL
harbor open <service>                  # Open service in browser
harbor qr <service>                    # Print QR code for service URL
```

## Profiles

Save and restore full service configurations.

```bash
harbor profile ls                      # List saved profiles
harbor profile save <name>             # Save current config as profile
harbor profile load <name>             # Load a profile
harbor profile rm <name>               # Remove a profile
```

## Aliases

Define reusable command shortcuts.

```bash
harbor alias ls                        # List aliases
harbor alias get <name>                # Get an alias
harbor alias set <name> <command>      # Set an alias
harbor alias rm <name>                 # Remove an alias
harbor run <alias>                     # Execute an alias
```

## Tunnels

Expose services to the internet via Cloudflare tunnels.

```bash
harbor tunnel <service>                # Expose a service
harbor tunnel down                     # Stop all tunnels
harbor tunnels ls                      # List auto-tunnel services
harbor tunnels add <service>           # Add to auto-tunnel list
harbor tunnels rm <service>            # Remove from auto-tunnel list
```

## Volumes

Mount custom host directories into service containers.

```bash
harbor volumes ls                      # Show all custom volumes
harbor volumes ls <service>            # Show volumes for a service
harbor volumes add <svc> <src>:<dest>  # Add a volume mount
harbor volumes rm <service> <index>    # Remove by index
harbor volumes clear <service>         # Remove all for a service
```

## Model Management

Unified model management across backends.

```bash
harbor models                          # Manage models across Ollama, HuggingFace, llama.cpp, DMR, MLX
harbor pull <model>                    # Pull a model (auto-detects backend)
harbor ollama <cmd>                    # Run Ollama CLI commands
```

## Service-Specific Configuration

Many services have dedicated subcommands for configuration.

```bash
# Backend configuration
harbor ollama <cmd>                    # Ollama CLI
harbor llamacpp <cmd>                  # llama.cpp config
harbor vllm <cmd>                      # vLLM config
harbor litellm <cmd>                   # LiteLLM config
harbor tgi <cmd>                       # Text Generation Inference config
harbor aphrodite <cmd>                 # Aphrodite config
harbor tabbyapi <cmd>                  # TabbyAPI config
harbor mistralrs <cmd>                 # mistral.rs config
harbor sglang <cmd>                    # SGLang CLI
harbor dmr <cmd>                       # Docker Model Runner config
harbor mlx <cmd>                       # MLX backend config
harbor kobold <cmd>                    # Koboldcpp config
harbor ktransformers <cmd>             # ktransformers config

# Frontend configuration
harbor webui <cmd>                     # Open WebUI config
harbor chatui <cmd>                    # HuggingFace ChatUI config
harbor comfyui <cmd>                   # ComfyUI config
harbor langflow <cmd>                  # Langflow config

# Tool configuration
harbor boost <cmd>                     # Harbor Boost LLM proxy
harbor openai <cmd>                    # OpenAI API keys/URLs
harbor jupyter <cmd>                   # Jupyter config
harbor mcp <cmd>                       # MCP service config
harbor hermes <cmd>                    # Hermes Agent config
```

## Harbor Boost — Agentic Modules

Harbor Boost is an LLM proxy (`harbor up boost`) that chains modules before the downstream completion. Agentic modules add web research, task anchoring, deliverable audits, and scope guards for coding agents. Full reference: `docs/5.2.3-Harbor-Boost-Modules.md`.

### Modules

| Module | Use when |
|--------|----------|
| `quickhop` | Fast web research before answering — API docs, release notes, error lookups. Low latency (2 searches). Skips acks and implementation-only turns. |
| `deephop` | Deeper two-hop research — migrations, version comparisons, breaking changes. Higher budgets; structured brief with uncertainties. |
| `caveman` | Terse output compression — injects caveman-style rules every completion (`lite`/`full`/`ultra`). Governs how the model talks. |
| `ponytail` | YAGNI minimal-code ladder — stdlib first, shortest diff wins. Governs what the model builds. |
| `autocheck` | Quality gate on coding **deliverable** turns — draft → audit → optional revise. Explanations and short acks pass through. |
| `diffscope` | User states file scope (`only X`, `don't touch Y`) — compares cited paths in the draft against constraints; one revision hop if out of scope. |

**Pairs:** `quickhop` for speed, `deephop` for depth. `caveman` + `ponytail` for terse/YAGNI style. `autocheck` + `diffscope` for scoped deliverable audits.

### `harbor launch --workflow`

One-shot wiring for Boost module workflows. Put launch options **before** the tool name; everything after the tool name passes through unchanged.

| Behavior | Detail |
|----------|--------|
| Starts | Boost + `--backend` (default: first running backend, else `llamacpp`) |
| Routes tool to | `<module>-<model>` (e.g. `quickhop-qwen2.5-coder:7b`) |
| Auto-starts SearXNG | when the workflow includes `quickhop` or `deephop` |

`--web` and `--workflow` cannot be combined. `claude` does not support Boost workflows (Anthropic API); use OpenAI-compatible host tools (`codex`, `opencode`, `copilot`, `droid`, `hermes`, `mi`, `openclaw`, `pi`, `pool`).

```bash
harbor launch --workflow quickhop --backend ollama --model qwen2.5-coder:7b codex
harbor launch --workflow autocheck --backend ollama --model qwen2.5-coder:7b opencode
```

Workflows that include `autocheck` or `diffscope` need a workspace bind mount (see Setup). Add `write_workspace_file` to `HARBOR_BOOST_TOOLS` and pass `--sandbox workspace-write` when you want the model to write files.

### Setup

```bash
# Start Boost with backend
harbor up ollama boost

# Enable agentic modules
harbor boost modules add tools quickhop deephop autocheck caveman ponytail

# Web research backend (pick one)
harbor config set HARBOR_BOOST_SEARXNG_URL http://searxng:8080
harbor up searxng
# or
harbor config set HARBOR_BOOST_TAVILY_API_KEY <key>

# Workspace bind mount + in-container jail root (Boost runs in Docker)
harbor config set boost.workspace "$(pwd)"
harbor config set boost.workspace.root /workspace

# Workspace tools for coding sandbox sessions
harbor config set HARBOR_BOOST_TOOLS 'read_workspace_file;grep_workspace;list_workspace_files;write_workspace_file'
harbor config update
harbor restart boost

# Point a coding agent at Boost (manual config)
harbor url boost   # OpenAI-compatible; model: <workflow-or-module>-<backend-model>
```

**Notes:** `autocheck` triggers only on deliverable turns (≥2 signals, e.g. coding keyword + file path). Define multi-step custom workflows via `HARBOR_BOOST_WORKFLOWS` or `workflows.yaml`.

### Debug Metrics (Troubleshooting)

When agentic modules skip or trigger unexpectedly, enable compact per-module debug metrics. Boost emits a one-line summary **before** the final completion so you can see what each module did on that turn.

**Global (all requests):**

```bash
harbor config set HARBOR_BOOST_DEBUG true
harbor restart boost
```

**Per request** — overrides `HARBOR_BOOST_DEBUG` for a single completion:

```bash
# OpenAI-compatible body (harbor url boost)
curl "$BOOST_URL/chat/completions" \
  -H "Authorization: Bearer $BOOST_KEY" \
  -d '{
    "model": "llama3.2",
    "messages": [{"role": "user", "content": "Fix the auth bug in src/api.ts"}],
    "@boost_debug": true
  }'

# Anthropic / Responses API — put @boost_ keys in metadata instead
```

Accepted truthy values: `true`, `1`, `yes`, `on`. Use `@boost_debug: false` to silence metrics when global debug is on.

**Example status line:**

```text
Debug: quickhop skipped (acknowledgment) 3ms | deephop skipped (implementation) 2ms | autocheck triggered 840ms +2calls [verdict=pass,outcome=delivered]
```

Each segment is one module: `triggered` or `skipped`, optional `(reason)`, wall-clock `duration_ms`, optional `+Ncalls` for extra LLM/tool hops, and `[key=value,...]` extras (e.g. `gate_reason`, `verdict`, `outcome`, `grounding_mode`).

**Common skip reasons:**

| Reason | Module | Meaning |
|--------|--------|---------|
| `acknowledgment` | quickhop, deephop | Short ack / non-research turn |
| `not_deliverable` | autocheck | Fewer than two deliverable signals |
| `empty_message` | any | No user content to process |

**Related:** `@boost_show_audit` (or `HARBOR_BOOST_AUTOCHECK_SHOW_AUDIT=true`) appends an autocheck audit footer and HTML findings artifact — use when you need full audit detail, not just the compact debug line.

## Launching Service CLIs

`harbor launch` starts a service CLI pre-configured to use running Harbor services. Runs from the directory you invoke it (preserves project context).

```bash
harbor launch <tool> [args]            # Launch with auto-detected backends
harbor launch --backend <svc> <tool>   # Override backend
harbor launch --model <model> <tool>   # Override model
harbor launch --workflow <module> <tool>  # Single Boost module workflow — see Harbor Boost section
harbor launch --web <tool>             # Generated boost-web workflow + SearXNG (mutually exclusive with --workflow)
harbor launch --config <tool>          # Print/write config without starting tool

# Direct CLI shortcuts (service must be running)
harbor aider                           # Aider coding assistant
harbor aichat                          # aichat CLI
harbor fabric                          # Fabric CLI
harbor opint                           # Open Interpreter
harbor plandex                         # Plandex CLI
harbor gptme                           # gptme CLI
harbor nanobot                         # nanobot CLI
harbor repopack                        # Repopack CLI
harbor facts                           # facts CLI
harbor mi                              # mi agent CLI
```

## HuggingFace Integration

```bash
harbor hf <cmd>                        # HuggingFace CLI (extended)
harbor hf dl <spec>                    # Download model files
harbor hf find <query>                 # Search HF Hub
harbor hf path <spec>                  # Print local cache path
harbor hf token [value]                # Get/set HF token
harbor hf cachedir [path]              # Get/set HF cache path
harbor hf parse-url <url>              # Parse HF file URL
```

## Diagnostics and Utilities

```bash
harbor info                            # System information for debugging
harbor doctor                          # Troubleshooting checks
harbor smi                             # NVIDIA GPU information
harbor top                             # GPU usage monitor (nvtop)
harbor size                            # Cache size report
harbor find <file>                     # Find file in Harbor caches
harbor how <question>                  # Ask questions about Harbor CLI
harbor history                         # Command history (interactive)
harbor eject                           # Output standalone Compose config
harbor home                            # Print Harbor workspace path
harbor vscode                          # Open workspace in VS Code
harbor fixfs                           # Fix file system ACLs
```

## Compose Integration

Harbor generates Docker Compose configurations dynamically. Use `harbor cmd` and `harbor eject` for direct Compose access.

```bash
$(harbor cmd <service>)                # Raw docker compose command for a service
harbor eject                           # Standalone Compose config for current selection
```

## Common Patterns

### Quick Start with Ollama + Web UI

```bash
harbor up ollama webui
harbor pull llama3.2
harbor open webui
```

### Run llama.cpp with a Specific Model

```bash
harbor config set HARBOR_LLAMACPP_MODEL "bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"
harbor up llamacpp webui
harbor open webui
```

### Multi-Backend Setup

```bash
harbor up ollama vllm litellm webui
harbor config set HARBOR_VLLM_MODEL "Qwen/Qwen2.5-3B-Instruct"
harbor pull llama3.2
harbor open webui
```

### Expose a Service to the Internet

```bash
harbor up ollama webui
harbor tunnel webui
```

### Use a Profile for Reproducible Setups

```bash
harbor up ollama webui
harbor config set HARBOR_OLLAMA_MODEL llama3.2
harbor profile save my-setup

# Later, restore everything
harbor profile load my-setup
harbor up
```

### Run Evaluations

```bash
harbor eval                            # Run promptfoo evaluation
harbor bench                           # Run Harbor Bench
harbor k6                              # Run K6 load testing
harbor promptfoo <cmd>                 # Promptfoo CLI
harbor lmeval <cmd>                    # LM Evaluation Harness
```

### Launch Coding Assistants

```bash
harbor up ollama
harbor pull qwen2.5-coder:7b
harbor launch --model qwen2.5-coder:7b aider
harbor launch --workflow quickhop --backend ollama --model qwen2.5-coder:7b codex
harbor launch --workflow autocheck --backend ollama --model qwen2.5-coder:7b opencode
```

## Important Notes

- **Logs hang**: `harbor logs` tails by default — in scripts/agents, use `docker logs <container>` with `--tail` flag instead.
- **Config not .env**: Never edit `.env` directly. Use `harbor config get/set`.
- **Default services**: `harbor up` with no args starts services listed in `harbor defaults ls`.
- **Service names**: Use `harbor ls` to discover exact service handles.
- **Docker required**: Harbor requires Docker and Docker Compose. Run `harbor doctor` to verify.
