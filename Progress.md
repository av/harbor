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
