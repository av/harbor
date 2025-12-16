You will not confuse this project with the Harbor container registry. This is a different project with the same name.
Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease.
Harbor is in essence a very large Docker Compose project with extra conventions and tools for managing it.
When adding new service, read [instructions for adding new service](./.github/copilot-new-service.md).
When user shows you a new or not obvious command for you - document it in this AGENTS.md file.

Important locations:
- '.' - root, also referred to as `$(harbor home)`
- `harbor.sh` - the main CLI script, it is very large and complex, but it contains the main entry point for the CLI
- `/app` - the Tauri app that provides a GUI for managing services
- `/docs` - documentation for the project and services
- `/routines` - part of the CLI that was rewritten in Deno
- `/.scripts` - scripts for development tasks, written in Deno and Bash

The CLI is already installed globally for your tests, you may run `harbor <command>` directly.

```bash
harbor help
harbor build <service>
harbor logs <service> # tails by default
# Raw compose command for the service
$(harbor cmd <service>)
```

Refer to [CLI Reference](./docs/3.-Harbor-CLI-Reference.md) for more details.

---

# Upstream Compose Integration (WIP)

## Overview

Harbor is evolving to support **stock Docker Compose files** from upstream projects with minimal or zero modifications. This enables easier integration of third-party services while maintaining Harbor's dynamic compose layering system.

## Core Design

### Problem Statement

Current Harbor services require:
1. Rewriting compose files with Harbor conventions (prefixed service names, harbor-network, etc.)
2. Custom entrypoints for config merging (webui, litellm)
3. Manual sync when upstream projects update

### Solution: Upstream Compose Transformation

A preprocessing step that:
1. **Reads** stock compose files from upstream projects
2. **Transforms** service names, volumes, networks, and references
3. **Merges** with Harbor's overlay files
4. **Optionally runs init containers** for config preparation

### File Structure Convention

```
harbor/
  {service}/
    upstream/                     # Git submodule or copy of upstream repo
      docker-compose.yaml         # UNTOUCHED stock file
    harbor.upstream.yaml          # Transformation metadata
    override.env                  # Harbor env overrides
  compose.{service}.yml           # Harbor overlay (cross-service integration)
```

### `harbor.upstream.yaml` Schema

```yaml
# Required: path to stock compose file
source: ./upstream/docker/docker-compose.yaml

# Required: prefix for service/volume names
prefix: dify2

# Optional: which services to include (default: all)
include:
  - api
  - worker
  - web

# Optional: which services to exclude
exclude:
  - nginx

# Optional: init container for config preparation
init:
  image: python:3.11-alpine
  script: ./scripts/prepare-config.sh
  volumes:
    - ./configs:/input
    - {prefix}-shared:/output
```

### Transformation Rules

| Original | Transformed |
|----------|-------------|
| Service `api` | `{prefix}-api` |
| `container_name: X` | `${HARBOR_CONTAINER_PREFIX}.{prefix}-{original}` |
| `depends_on: [redis]` | `depends_on: [{prefix}-redis]` |
| `network_mode: service:X` | `network_mode: service:{prefix}-X` |
| Volume `mydata` | `{prefix}-mydata` |
| Networks | Add `harbor-network` to all services |

### Init Container Pattern (Option A)

For services needing runtime config assembly:

```yaml
init:
  image: python:3.11-alpine
  script: ./scripts/merge-configs.sh
  volumes:
    - ./configs:/input
    - {prefix}-config:/output
  # Runs before main services, exits on completion
```

Main services then mount the shared volume:
```yaml
services:
  {prefix}-api:
    volumes:
      - {prefix}-config:/app/config
    depends_on:
      {prefix}-init:
        condition: service_completed_successfully
```

## Implementation Status

See [Progress.md](./Progress.md) for current development status.

## Stock Compose Compatibility Matrix

| Project | Services | Complexity | Status |
|---------|----------|------------|--------|
| Dify | 10+ | High (YAML anchors, init container) | 🔄 In Progress |
| Langflow | 2 | Low | ⏳ Planned |
| Open-WebUI | 2 | Low | ⏳ Planned |
| Flowise | 1 | Low | ⏳ Planned |
| Lobe-Chat | 7+ | High (network_mode) | ⏳ Planned |