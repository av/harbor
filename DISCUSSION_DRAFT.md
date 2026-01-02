# GitHub Discussion Reply - Stock Docker Compose Integration

**In reply to:** [Discussion #202](https://github.com/av/harbor/discussions/202)

---

Thanks for the thoughtful response and sorry for my delayed reply!

## On the TypeScript SDK approach

I think this makes a lot of sense. The SDK could serve as the programmatic layer that YAML configs are built on - similar to how Elestio uses `elestio.yaml` as a meta-manifest. Users who want simple configs use YAML, power users who need conditionals/loops/type-safety use the SDK directly.

## Summary of what I've built

I've been iterating on this with AI-assisted coding (Claude). Here's the full `harbor.yaml` schema:

```yaml
upstream:
  # Path to stock compose file (can be a git submodule)
  source: ./upstream/docker/docker-compose.yaml
  
  # Namespace for isolation (creates internal network)
  namespace: dify2
  
  # Services to include/exclude from stock compose
  services:
    exclude: [nginx, certbot]
  
  # Services exposed on harbor-network
  # - Simple string: uses original name (matches upstream)
  # - Object {service: alias}: uses custom alias (e.g., for conflict avoidance)
  expose:
    - api                    # exposed as "api" (original name)
    - web: dify2-web         # exposed as "dify2-web" (prefixed when conflict expected)
  
  # Harbor-specific overrides (REPLACES compose.{service}.yml)
  # Keys are ORIGINAL service names, applied to prefixed services
  overrides:
    api:
      environment:
        - OPENAI_API_BASE=http://${HARBOR_CONTAINER_PREFIX}.ollama:11434/v1
    web:
      ports:
        - ${HARBOR_DIFY2_HOST_PORT:-3001}:3000

# Future sections (not yet implemented):
metadata:
  tags: [backend, api]

configs:
  cross:
    ollama:
      api:
        environment:
          - OLLAMA_ENABLED=true
```

## What's implemented

- ✅ `upstream.source` - Stock compose path
- ✅ `upstream.namespace` - Internal network isolation
- ✅ `upstream.services.include/exclude` - Service filtering
- ✅ `upstream.expose` - Harbor-network aliases (default: original name, custom alias when needed)
- ✅ `upstream.overrides` - Harbor-specific config (replaces `compose.{service}.yml`)

## Not yet implemented

- ⏳ `metadata:` - Service tags, wiki URL
- ⏳ `configs.cross:` - Conditional cross-service config merging
- ⏳ System variable syntax (e.g., `{{service:ollama}}`) - currently using Harbor env conventions

## Key insight: Namespace isolation via internal networks

The initial approach required rewriting environment variables (`DB_HOST=dify2-db`, etc.) which was fragile. The breakthrough was using Docker Compose networks:

| Network | Service reachable as | Used by |
|---------|---------------------|---------|
| `dify2-internal` | `api`, `db`, `redis` (original names) | Internal services |
| `harbor-network` | `api`, `web` (or custom alias) | Other Harbor services |

Service names in the merged compose are prefixed (`dify2-api`) to avoid collision between upstream stacks, but original names are available as aliases on both networks by default.

**Transformation rules:**

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

## Benefits

- **No env rewrites needed** - upstream compose works as-is
- **No service name conflicts** between upstream stacks
- **`harbor.yaml` is single source of truth** - no separate `compose.{service}.yml` needed

This has been running Dify (10 services) and verified working today.

## Compatibility & Gradual Migration

This was a key design goal. The implementation is **fully backward compatible**:

1. **Existing services unchanged** - Services without `harbor.yaml` work exactly as before
2. **No breaking changes** - The transformation only activates when `harbor.yaml` exists
3. **Gradual adoption** - New services can use `harbor.yaml`, existing ones can migrate incrementally

## Tested scenarios

- ✅ `harbor up dify2` - Services start correctly
- ✅ Internal DNS resolution verified (`redis`, `db_postgres`, `sandbox` resolve correctly)
- ✅ Overrides applied (environment, ports)
- ✅ Profiles passthrough (`--profile postgresql`)

## Not yet tested

I haven't gone through the entire `harbor.sh` CLI - commands like `harbor build`, `harbor exec`, `harbor shell`, etc. **Is this approach compatible with the full CLI?** Are there specific commands I should verify?

## PR ready for review

I've created [PR #204](https://github.com/av/harbor/pull/204) with the full implementation. Happy to adjust based on your feedback, especially regarding the SDK direction - this could become the first "backend" that the SDK targets, or remain as a simpler YAML alternative for basic cases.

---

## Future Directions (not yet implemented)

These are ideas for future extensions, kept here for reference:

### Declarative Cross-Service Overlays

The `configs.cross` section could evolve to support conditional cross-service config:

```yaml
configs:
  cross:
    ollama:
      api:
        environment:
          - OLLAMA_ENABLED=true
```

### System Variable Syntax

Currently using Harbor env conventions (`${HARBOR_CONTAINER_PREFIX}`). Future syntax could be cleaner:

```yaml
overrides:
  api:
    environment:
      - OPENAI_API_BASE=http://{{service:ollama}}:11434/v1
  web:
    ports:
      - {{port:3001}}:3000
```

### Lifecycle Hooks

```yaml
hooks:
  pre_up:
    - script: ./scripts/check-dependencies.sh
  post_up:
    - script: ./scripts/seed-database.sh
```

### Secrets Management

```yaml
secrets:
  provider: sops
  files:
    - .env.secrets.enc
```

---

Happy to discuss and iterate on this design!

