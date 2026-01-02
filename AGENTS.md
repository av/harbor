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

# harbor.yaml - Service Configuration (WIP)

## Overview

Harbor is evolving to support a unified **`harbor.yaml`** configuration file per service. This enables:
- Using **stock Docker Compose files** from upstream projects with zero modifications
- Declarative service metadata for the Harbor App
- Simplified config merging via init containers

This approach maintains **full backward compatibility** - existing services without `harbor.yaml` work exactly as before.

## File Structure

```
harbor/
  {service}/
    harbor.yaml                   # Service configuration - SINGLE SOURCE OF TRUTH
    upstream/                     # Git submodule or copy of upstream repo
      docker-compose.yaml         # UNTOUCHED stock file
    override.env                  # Harbor env overrides (optional)
  # NOTE: compose.{service}.yml is NO LONGER NEEDED for upstream services
  # All config is in harbor.yaml including overrides
```

## `harbor.yaml` Schema

```yaml
# Upstream compose transformation
# Use this when integrating stock Docker Compose files
upstream:
  # Path to stock compose file (relative to service directory)
  source: ./upstream/docker/docker-compose.yaml

  # Namespace for isolation (creates internal network + prefixed service names)
  namespace: dify2

  # Services to include/exclude (default: all)
  services:
    include:
      - api
      - worker
      - web
    exclude:
      - nginx

  # Services exposed on harbor-network (with {namespace}-{service} alias)
  # Other services stay internal-only
  expose:
    - api
    - web

  # Harbor-specific overrides (REPLACES compose.{service}.yml)
  # Keys are ORIGINAL service names, applied to prefixed services
  overrides:
    api:
      environment:
        - OPENAI_API_BASE=http://${HARBOR_CONTAINER_PREFIX}.ollama:11434/v1
    web:
      ports:
        - ${HARBOR_DIFY2_HOST_PORT:-3001}:3000

# Service metadata for Harbor App (future)
metadata:
  tags: [backend, api]
  wikiUrl: https://github.com/av/harbor/wiki/myservice

# Cross-service config merging (future)
configs:
  cross:
    ollama:
      api:
        environment:
          - OLLAMA_ENABLED=true
```

## Namespace Isolation via Internal Networks

The key insight is using **Docker Compose networks** for conflict prevention:

1. **Internal network**: `{namespace}-internal` - Services use original names (no compose changes needed)
2. **Shared network**: `harbor-network` - Exposed services get `{namespace}-{service}` alias

This means:
- **No env rewrites needed** - Internal services reference each other by original names
- **No compose modifications** - Upstream compose works as-is
- **No conflicts** - External services see prefixed aliases
- **Backward compatible** - Existing Harbor services unchanged

```yaml
# Example: dify2 services in merged compose
services:
  dify2-api:                # Prefixed service name (avoids collision)
    networks:
      dify2-internal:
        aliases:
          - api             # Internal: reachable as "api" (original name)
      harbor-network:
        aliases:
          - dify2-api       # External: reachable as "dify2-api"
```

## Upstream Transformation Rules

When `upstream:` is specified, the CLI automatically transforms the stock compose.

**Implementation**: Transformation is done via proper YAML parsing (`@std/yaml`), not regex. The stock compose is parsed into an object, transformed structurally, then merged. YAML anchors (`x-shared-env`, etc.) are resolved at parse time by the YAML library.

**Core module**: `routines/upstream.ts`
- `loadHarborConfig()` / `loadUpstreamConfig()` - Load and parse `harbor.yaml`
- `transformUpstreamCompose()` - Main transformation orchestrator
- `transformService()` - Per-service transformation (container_name, networks, etc.)
- `loadTransformedUpstream()` - Full pipeline for a service

**Transformation rules**:

| Original | Transformed |
|----------|-------------|
| Service `api` | `{namespace}-api` (prefixed to avoid collision) |
| `container_name: X` | `${HARBOR_CONTAINER_PREFIX}.{namespace}-{original}` |
| `depends_on: [redis]` | `depends_on: [{namespace}-redis]` (prefixed) |
| `network_mode: service:X` | `network_mode: service:{namespace}-X` (prefixed) |
| Volume `mydata` | `{namespace}-mydata` |
| Networks | Add `{namespace}-internal` (with original name alias) + `harbor-network` (for exposed) |
| `env_file` | Inject `.env` and `override.env` |
| `overrides` | Merged into transformed services (environment, ports, volumes append) |

## Migration Path

Existing services can be gradually migrated:

1. **No change needed** - Services without `harbor.yaml` work as before
2. **Add harbor.yaml** - For new services using stock compose files
3. **Migrate existing** - Replace manually-rewritten compose with `upstream:` config

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

## Future Directions

See [DISCUSSION_DRAFT.md](./DISCUSSION_DRAFT.md) for proposed extensions:
- **Declarative overlays**: `overlays:` section for cross-service integrations (replacing file-naming conventions)
- **Lifecycle hooks**: `hooks:` for pre_up, post_up, pre_down scripts
- **Secrets management**: `secrets:` for SOPS/age/Vault integration
- **Multi-environment**: `environments:` for dev/prod configurations