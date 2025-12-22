# GitHub Discussion Draft for av/harbor

**Category:** Ideas / Feature Request

---

## Title: RFC: Stock Docker Compose Integration via `harbor.yaml`

---

### Summary

I'd like to propose a feature that enables Harbor to use **stock Docker Compose files** from upstream projects with zero modifications. This would significantly reduce maintenance burden when integrating complex services like Dify, Langflow, or Lobe-Chat that have their own multi-service compose files.

### Problem

Currently, when adding a new service to Harbor, we need to manually rewrite the upstream's Docker Compose file to:
- Rename services to avoid conflicts (e.g., `api` → `dify-api`)
- Update `container_name` with Harbor's prefix convention
- Fix all `depends_on` and `network_mode: service:X` references
- Rename volumes to avoid conflicts
- Add `harbor-network` to all services
- Inject Harbor's env files

This is error-prone, time-consuming, and creates a maintenance burden whenever upstream updates their compose file.

### Proposed Solution

Introduce a `harbor.yaml` configuration file per service that declares transformation rules:

```yaml
# {service}/harbor.yaml
upstream:
  # Path to stock compose file (can be a git submodule)
  source: ./upstream/docker/docker-compose.yaml
  
  # Prefix for all service names (api -> dify2-api)
  prefix: dify2
  
  # Services to exclude (e.g., nginx when Harbor handles reverse proxy)
  exclude:
    - nginx
    - certbot

# Future sections for extensibility
metadata:
  tags: [backend, api]
  wikiUrl: https://github.com/av/harbor/wiki/dify

configs:
  base: ./configs/config.yml
  cross:
    ollama: ./configs/config.ollama.yml
```

The CLI would automatically transform the stock compose at runtime using **namespace isolation via internal networks**:

```yaml
# harbor.yaml
upstream:
  source: ./upstream/docker/docker-compose.yaml
  namespace: dify2
  services:
    include: [api, worker, web, redis, db]
    exclude: [nginx]
  expose: [api, web]  # Services visible on harbor-network
```

**Key insight**: Use Docker Compose networks for conflict prevention instead of rewriting service names:

| Network | Service reachable as | Used by |
|---------|---------------------|---------|
| `{namespace}-internal` | `api`, `db`, `redis` (original names) | Internal services |
| `harbor-network` | `{namespace}-api`, `{namespace}-web` (aliased) | Other Harbor services |

**Transformation rules**:

| Original | Transformed |
|----------|-------------|
| Service `api` | `api` (unchanged) |
| `container_name: X` | `${HARBOR_CONTAINER_PREFIX}.{namespace}-{original}` |
| `depends_on: [redis]` | `depends_on: [redis]` (unchanged - internal network) |
| `network_mode: service:X` | `network_mode: service:X` (unchanged - internal network) |
| Volume `mydata` | `{namespace}-mydata` |
| Networks | Add `{namespace}-internal` + `harbor-network` (with alias for exposed) |
| `env_file` | Inject `.env` and `override.env` |

This approach means:
- **No env rewrites needed** - Internal services reference each other by original names
- **No compose modifications** - Upstream compose works as-is  
- **No conflicts** - External services see prefixed aliases
- **Backward compatible** - Existing Harbor services unchanged

### Benefits

1. **Zero maintenance** - Stock compose files can be git submodules, updated with `git pull`
2. **Backward compatible** - Services without `harbor.yaml` work exactly as before
3. **Extensible** - The `harbor.yaml` schema can grow to include service metadata for the Harbor App, config merging declarations, etc.
4. **Reduced errors** - Automated transformation eliminates manual rewrite mistakes

### Implementation Status

I have a working proof-of-concept implementation:
- **Branch:** `feature/upstream-compose-integration` ([kundeng/harbor](https://github.com/kundeng/harbor/tree/feature/upstream-compose-integration))
- **Core module:** `routines/upstream.ts` (~390 lines)
- **Test service:** `dify2/` with stock Dify compose file

The implementation integrates into the existing `mergeComposeFiles.ts` flow - upstream transforms are loaded before regular compose files and merged using the existing deepMerge logic.

### Questions for Discussion

1. Does this align with Harbor's design philosophy?
2. Should the `harbor.yaml` file live in the service directory (proposed) or somewhere else?
3. Any concerns about the transformation rules? Are there edge cases I'm missing?
4. Interest in the future `metadata:` and `configs:` sections for Harbor App integration?

### Future Direction: Declarative Cross-Service Overlays

Currently, Harbor uses file-naming conventions for cross-service integration:
- `compose.x.aider.ollama.yml` - applied when both `aider` AND `ollama` are running
- `compose.litellm.langfuse.postgres.yml` - applied when ANY of those services run

This works well but has limitations:
- Discovery requires scanning filenames
- Logic is implicit in naming conventions
- Hard to see all integrations for a service at a glance

The `harbor.yaml` approach could evolve to make this **declarative**:

```yaml
# aider/harbor.yaml
upstream:
  source: ./upstream/docker-compose.yaml
  prefix: aider

# Cross-service overlays - applied conditionally based on active services
overlays:
  # When ollama is also running
  ollama:
    volumes:
      - ./configs/aider.ollama.yml:/root/.aider/ollama.yml
  
  # When litellm is also running  
  litellm:
    volumes:
      - ./configs/aider.litellm.yml:/root/.aider/litellm.yml
    environment:
      - OPENAI_API_BASE=http://litellm:4000
  
  # Platform capabilities (nvidia toolkit detected)
  nvidia:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

# Multi-service conditions (AND logic)
overlays:
  # Applied only when BOTH litellm AND langfuse are running
  [litellm, langfuse]:
    environment:
      - LANGFUSE_HOST=http://langfuse:3000
```

This would:
1. **Consolidate** all cross-service logic for a service in one place
2. **Make dependencies explicit** and discoverable
3. **Support complex conditions** (AND/OR logic) declaratively
4. **Maintain backward compatibility** - file-based overlays continue to work

The file-naming convention could eventually become syntactic sugar that generates `harbor.yaml` entries, or both systems could coexist.

### Why Not Native Docker Compose Features?

Docker Compose has `profiles` and `include`, but neither can replace Harbor's dynamic composition:

- **Profiles** are static - you assign services to named profiles at authoring time. Harbor's file-matching is dynamic based on runtime service selection.
- **Include** lacks conditional logic - there's no `include: if: condition` syntax.

Harbor's file-matcher implements a **rule engine** that neither feature can replicate. The `harbor.yaml` approach formalizes this as a declarative configuration layer.

### Longer-Term Vision: Service Manifest for Full Lifecycle

This is admittedly ambitious, but if the `harbor.yaml` pattern proves useful, it could evolve into a **service manifest** that handles the full operational lifecycle - not just *what* to run, but *how* to operate it:

```yaml
# Future harbor.yaml - full service manifest
upstream:
  source: ./upstream/docker-compose.yaml
  prefix: myservice

overlays:
  ollama: { ... }
  nvidia: { ... }

# Lifecycle hooks (beyond Docker's native post_start/pre_stop)
hooks:
  pre_up:
    - script: ./scripts/check-dependencies.sh
  post_up:
    - script: ./scripts/seed-database.sh
  pre_down:
    - script: ./scripts/backup-data.sh

# Secrets management (SOPS/age, Vault, etc.)
secrets:
  provider: sops
  files:
    - .env.secrets.enc  # decrypted at runtime

# Backup & persistence
backup:
  schedule: "0 2 * * *"
  volumes: [postgres-data, ollama-models]
  destination: s3://harbor-backups/{{date}}

# Multi-environment support
environments:
  dev:
    overlays: [nvidia]
    env_file: .env.dev
  prod:
    overlays: [nvidia, monitoring]
    secrets:
      provider: vault
```

This would position Harbor as a **compose-based orchestration platform** - something I've been searching for across many alternatives:

- **Dokploy** - Clean UI, good Compose support, but limited cross-service orchestration
- **Coolify** - Feature-rich PaaS, but focused on app deployment not service composition
- **CapRover** - Solid and customizable, but Compose support is secondary
- **Portainer** - Great container GUI, but not an orchestration layer
- **Dockge** - Simple compose management, lacks advanced composition logic

Harbor is the closest I've found to treating Docker Compose as a **first-class orchestration primitive** rather than just a deployment artifact. The dynamic file-matching, cross-service config merging, and service-aware CLI are exactly the patterns needed for complex multi-service stacks (especially AI services that need to wire together backends, frontends, and satellites).

The `harbor.yaml` proposal formalizes these patterns. If proven with AI services, it could become a foundation for an **API-first, compose-based orchestration system** that surpasses the alternatives for complex scenarios.

*(This vision may be too ambitious for Harbor's current scope as an LLM toolkit - happy to keep it focused on the immediate `upstream:` feature if preferred.)*

### Next Steps (if accepted)

- [ ] Test with more upstream services (Langflow, Flowise, Lobe-Chat)
- [ ] Handle Docker Compose `profiles:` passthrough
- [ ] Optional init container generation for config preparation
- [ ] Prototype `overlays:` syntax for cross-service declarations
- [ ] Documentation and migration guide

---

Happy to discuss and iterate on this design. Would love to hear thoughts from the community!

