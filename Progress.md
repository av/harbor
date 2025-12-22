# Harbor Service Configuration (harbor.yaml) - Progress

## 2024-12-18

### Session 4: Documentation & Discussion Draft

**Completed**:
1. ✅ Pushed feature branch to origin: `origin/feature/upstream-compose-integration`
2. ✅ Created `DISCUSSION_DRAFT.md` for upstream GitHub discussion
3. ✅ Researched modern Docker Compose features (profiles, providers, include, watch)
4. ✅ Designed `overlays:` syntax for declarative cross-service integrations
5. ✅ Documented longer-term vision (hooks, secrets, backup, multi-env)
6. ✅ Updated AGENTS.md with implementation details

**Key Findings - Docker Compose Features**:
- **Profiles**: Static, can't replace Harbor's dynamic file-matching
- **Include**: No conditional logic (`include: if:` doesn't exist)
- **Providers**: New extension mechanism for non-container resources (interesting for future)
- **Lifecycle hooks**: `post_start`/`pre_stop` added in Compose v2.30

**Proposed Future `harbor.yaml` Sections**:
```yaml
overlays:        # Cross-service integrations (replaces compose.x.*.yml naming)
hooks:           # pre_up, post_up, pre_down lifecycle scripts
secrets:         # SOPS/age/Vault integration
backup:          # Scheduled volume backups
environments:    # dev/prod configurations
```

**Next**: Test transformation with `harbor up dify2`

### Session 4b: Bug Fixes & Testing

**Bugs Fixed**:
1. ✅ **Volume long syntax**: Volumes can be objects (not just strings) - added `VolumeEntry` type
2. ✅ **Network prefixing**: Service network references now prefixed (`ssrf_proxy_network` → `dify2-ssrf_proxy_network`)
3. ✅ **Default network**: Added implicit `{prefix}-default` network for services referencing `default`

**Test Results**:
```bash
# Transformation test - 33 services transformed correctly
~/.deno/bin/deno run --allow-read testUpstream.ts
# Services: dify2-init_permissions, dify2-api, dify2-worker, dify2-web, ...

# Merged compose validation
docker compose -f __harbor.yml config --services
# Shows: dify2-api, dify2-worker, dify2-web, dify2-redis, etc.

# Harbor up dry-run - pulls images successfully
harbor up dify2 --dry-run
```

**Files Modified**:
- `routines/upstream.ts` - Fixed volume and network transformation

**Deep Testing Results**:
```
✅ dify2-web          - Up, serving Next.js on port 3001
✅ dify2-redis        - Up, healthy
✅ dify2-init_perms   - Completed successfully
✅ ollama             - Up, healthy
⚠️  dify2-api         - Starts but needs storage config (OPENDAL_SCHEME)
⚠️  dify2-sandbox     - Needs conf/config.yaml (volume mount issue)
⚠️  dify2-ssrf_proxy  - Entrypoint script issue
⏸️  dify2-worker      - Waiting on API
⏸️  dify2-db_postgres - Not started (uses Docker Compose profiles)
```

**Known Issues for Dify Integration**:
1. **Profiles**: Stock Dify uses `profiles:` for optional services (databases). Need to handle profile passthrough or default selection.
2. **Config files**: Some services (sandbox, ssrf_proxy) expect config files that aren't in the stock compose volumes.
3. **Environment**: API needs storage configuration (`OPENDAL_SCHEME`, etc.) - should be in `override.env`.

**Conclusion**: The upstream transformation is working correctly. The issues are Dify-specific configuration requirements, not transformation bugs.

### Session 4c: Full Dify2 Integration

**Completed**:
1. ✅ Downloaded Dify's `.env.example` to `dify2/upstream/.env.example`
2. ✅ Updated transformation to inject upstream env file: `.env` → `upstream/.env.example` → `override.env`
3. ✅ Downloaded ssrf_proxy config files (`docker-entrypoint.sh`, `squid.conf.template`)
4. ✅ Created sandbox config directory with `config.yaml`
5. ✅ Added service hostname overrides to global `.env` (DB_HOST, REDIS_HOST, etc.)
6. ✅ Fixed port conflict (PLUGIN_DEBUGGING_PORT 5003→5013)

**All Dify2 Services Running**:
```
harbor.dify2-web                Up (port 3001)
harbor.dify2-api                Up (port 5001 internal)
harbor.dify2-worker             Up
harbor.dify2-worker_beat        Up
harbor.dify2-plugin_daemon      Up (port 5013)
harbor.dify2-redis              Up (healthy)
harbor.dify2-db_postgres        Up (requires --profile postgresql)
harbor.dify2-sandbox            Up (healthy)
harbor.dify2-ssrf_proxy         Up
harbor.dify2-init_permissions   Exited (0) - expected
```

**Key Learnings (Session 4c - now superseded by Session 5)**:
1. **Env file precedence**: Compose `environment:` with defaults like `${VAR:-default}` requires overrides in global `.env`, not just `env_file`
2. **Profiles**: Database services use `profiles: [postgresql]` - must pass `--profile postgresql` to start them
3. **Config files**: Some services (sandbox, ssrf_proxy) need config files downloaded from upstream

**Files Modified**:
- `routines/upstream.ts` - Added upstream `.env.example` to env_file injection
- `dify2/override.env` - Service hostname overrides
- `.env` - Global Dify2 config (DB_HOST, REDIS_HOST, ports)
- `dify2/upstream/.env.example` - Downloaded from Dify
- `dify2/upstream/ssrf_proxy/*` - Downloaded config files
- `dify2/upstream/volumes/sandbox/conf/config.yaml` - Sandbox config

### Session 5: Namespace Isolation via Internal Networks

**Date**: 2024-12-22

**Problem with Previous Approach (Session 4c)**:
The env rewrite approach required:
1. Injecting upstream `.env.example` into env_file chain
2. Rewriting service hostnames in `override.env` (DB_HOST, REDIS_HOST, etc.)
3. Adding Dify-specific overrides to Harbor's global `.env`
4. Complex handling of hardcoded values in compose `environment:` section

This was fragile and polluted the global `.env` with service-specific config.

**New Approach: Internal Network Isolation**

Use Docker Compose networks to prevent conflicts without rewriting env vars:

```yaml
# harbor.yaml schema
upstream:
  source: ./upstream/docker/docker-compose.yaml
  namespace: dify2
  services:
    include: [api, worker, web, redis, db]
    exclude: [nginx]
  expose: [api, web]  # Services visible on harbor-network
```

**How it works**:

| Network | Service reachable as | Used by |
|---------|---------------------|---------|
| `dify2-internal` | `api`, `db`, `redis` (original) | Dify services internally |
| `harbor-network` | `dify2-api`, `dify2-web` (aliased) | Other Harbor services |

**Benefits**:
1. **No env rewrites** - Internal services use original names
2. **No compose changes** - Upstream compose works as-is
3. **No conflicts** - External services see prefixed aliases
4. **Backward compatible** - Existing Harbor services unchanged
5. **Clean separation** - No Dify-specific vars in global `.env`

**Transformation rules (updated)**:

| Original | Transformed |
|----------|-------------|
| Service `api` | `api` (unchanged) |
| `container_name: X` | `${HARBOR_CONTAINER_PREFIX}.{namespace}-{original}` |
| `depends_on: [redis]` | `depends_on: [redis]` (unchanged) |
| `network_mode: service:X` | `network_mode: service:X` (unchanged) |
| Volume `mydata` | `{namespace}-mydata` |
| Networks | Add `{namespace}-internal` + `harbor-network` (with alias for exposed) |

**Cross-service integration**:
- Other Harbor services reference exposed aliases: `http://dify2-api:5001`
- User creates cross-service files: `compose.x.boost.dify2.yml`
- Internal Dify services (db, redis) not exposed - no conflicts possible

**Status**: Design finalized, implementation pending

---

## 2024-12-16

### Session 3: Rename to harbor.yaml

**Completed**:
1. ✅ Renamed `harbor.upstream.yaml` → `harbor.yaml`
2. ✅ Restructured schema with `upstream:` section for future extensibility
3. ✅ Updated `routines/upstream.ts`:
   - Added `HarborConfig` interface with `upstream`, `metadata`, `configs` sections
   - Added `loadHarborConfig()` function
   - `loadUpstreamConfig()` now reads from `harbor.yaml` → `upstream:` section
   - Added `hasHarborConfig()` and `findHarborConfigServices()` functions
4. ✅ Updated documentation (AGENTS.md)
5. ✅ Created feature branch: `feature/upstream-compose-integration`

**New Schema**:
```yaml
# harbor.yaml
upstream:
  source: ./upstream/docker-compose.yaml
  prefix: myservice
  exclude: [nginx]

metadata:  # Future
  tags: [backend, api]

configs:   # Future
  base: ./configs/config.yml
```

---

### Session 2: Implementation

**Completed**:
1. ✅ Created `routines/upstream.ts` - Core transformation module
   - `loadHarborConfig()` - Loads `harbor.yaml`
   - `loadUpstreamConfig()` - Extracts `upstream:` section
   - `transformUpstreamCompose()` - Transforms stock compose with prefix
   - `loadTransformedUpstream()` - Full pipeline for a service
   - Handles: service names, container_name, depends_on, network_mode, volumes, networks

2. ✅ Integrated into `routines/mergeComposeFiles.ts`
   - Added `loadUpstreamComposeForServices()` function
   - Upstream transforms are loaded before regular compose files
   - Merged using existing deepMerge logic

3. ✅ Created `dify2/` test service structure:
   - `dify2/harbor.yaml` - Config with `upstream:` section
   - `dify2/override.env` - Harbor-specific env vars
   - `dify2/upstream/docker/docker-compose.yaml` - Downloaded stock file
   - `compose.dify2.yml` - Harbor overlay for cross-service integration

4. ✅ Created `routines/testUpstream.ts` - Test script for transformation

**Files Created/Modified**:
- `routines/upstream.ts` (NEW) - ~390 lines
- `routines/mergeComposeFiles.ts` (MODIFIED) - Added upstream loading
- `routines/testUpstream.ts` (NEW) - Test script
- `dify2/harbor.yaml` (NEW)
- `dify2/override.env` (NEW)
- `dify2/upstream/docker/docker-compose.yaml` (NEW - downloaded)
- `compose.dify2.yml` (NEW)
- `AGENTS.md` (MODIFIED) - Added design docs
- `Progress.md` (NEW)

**Pending Testing**:
- Deno not available in current environment
- Need to test with `harbor up dify2` on a system with harbor installed
- Test commands:
  ```bash
  # Test transformation only
  cd routines && deno run --allow-read --allow-write testUpstream.ts
  
  # Test full integration
  harbor up dify2
  ```

**Known Issues to Address**:
1. Volume path transformation needs refinement for relative paths
2. Need to handle `profiles:` from stock compose (passthrough or filter)
3. YAML anchors (`x-shared-env`) - should work since resolved at parse time

---

### Session 1: Initial Design & Analysis

**Goal**: Enable Harbor to use stock Docker Compose files from upstream projects with minimal/zero modifications.

**Analysis Completed**:
- Examined Harbor's current compose layering system (`routines/docker.ts`, `routines/mergeComposeFiles.ts`)
- Analyzed stock compose files: Dify, Langflow, Open-WebUI, Flowise, Lobe-Chat
- Evaluated 4 options:
  - Option A: Init containers ✅ Selected for config templating
  - Option B: Sidecars ❌ Overkill for static configs
  - Option C: Docker Compose extends ❌ Doesn't work with YAML anchors
  - Option D: Wrapper compose files ❌ Service name conflicts

**Design Decisions**:
1. **CLI preprocessing** transforms stock compose files (service names, volumes, networks)
2. **Init containers** (Option A) handle config merging when needed
3. **`harbor.upstream.yaml`** metadata file declares transformation rules
4. **Zero changes** to stock compose files (can be git submodules)

**Key Transformation Rules**:
- Service names: `api` → `{prefix}-api`
- Container names: Add `${HARBOR_CONTAINER_PREFIX}.{prefix}-{name}`
- `depends_on` references: Update to prefixed names
- `network_mode: service:X`: Update X to prefixed name
- Named volumes: Prefix to avoid conflicts
- Networks: Add `harbor-network` to all services

---

## Backlog

- [ ] Test transformation with Deno runtime
- [ ] Test `harbor up dify2` end-to-end
- [ ] Support for Docker Compose profiles passthrough
- [ ] Init container generation from `harbor.upstream.yaml`
- [ ] Git submodule automation for upstream repos
- [ ] Migration guide for existing Harbor services
- [ ] Add more upstream services (langflow, flowise, etc.)
