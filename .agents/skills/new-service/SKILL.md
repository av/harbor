---
name: new-service
description: >
  Add a new service to Harbor — scaffold the compose config, environment variables,
  metadata, documentation, and cross-service integrations. Use this skill whenever
  the user wants to add a new service to Harbor, integrate a new tool/app/model server,
  create a compose configuration for a new project, or onboard any software into the
  Harbor ecosystem. Triggers on phrases like "add X to Harbor", "new service", "integrate Y",
  "onboard Z", "create a service for", or when the user provides a GitHub repo link and
  expects it to become a Harbor service. Even if the user just says a project name and
  implies they want it in Harbor, this skill applies.
---

# Adding a New Service to Harbor

> **Subagent instruction:** Before doing any work, read this skill file in full using the `read_file` tool at path `/home/everlier/code/harbor/.agents/skills/new-service/SKILL.md`. Do not proceed until the file has been read.

Harbor is a modular Docker Compose project. Each service is a self-contained unit:
a compose file, a service directory, environment variables, app metadata, and documentation.
The detailed technical reference lives in `.github/copilot-new-service.md` — consult it
for edge cases or patterns not covered here.

## Workflow Overview

```
Gather Info → Scaffold → Compose Config → Env Vars → Metadata → Documentation → Integrations → Test
```

Every step has validation criteria. Do not advance until the current step passes.

## Step 0: Gather Information

Before writing any files, understand what you're building.

**Required inputs:**
- Service name or GitHub repo URL (from user)
- Docker deployment method: pre-built image, Dockerfile, or docker-compose in repo
- Service category: backend (inference), frontend (web UI), or satellite (tool/utility)
- Ports the service exposes internally
- Persistent data directories (volumes)
- Environment variables the service accepts

**Research the repo.** Look for:
- `docker-compose.yml`, `Dockerfile`, or `docker/` directory
- README sections on Docker deployment, environment variables, configuration
- The service's default ports and data paths

If the repo has its own docker-compose, study the service definitions — you'll adapt them
to Harbor's conventions, not copy them verbatim.

**If ambiguous, ask the user.** Don't guess the category or deployment method.

## Step 1: Select a Handle

The handle is the service's identifier everywhere in Harbor.

**Rules:**
- Lowercase letters, numbers, hyphens only
- Short, memorable, representative
- Must be unique

**Validate:**
```bash
ls services/compose.${handle}.yml 2>/dev/null && echo "TAKEN" || echo "OK"
grep -q "\"${handle}\"\\|'${handle}'\\|${handle}:" app/src/serviceMetadata.ts && echo "TAKEN" || echo "OK"
```

## Step 2: Scaffold

```bash
harbor dev scaffold ${handle}
```

This creates:
- `services/compose.${handle}.yml` — starter compose config
- `services/${handle}/override.env` — service-specific env overrides

## Step 3: Complete the Compose File

Edit `services/compose.${handle}.yml`. The scaffold gives you a skeleton — fill it in.

**Mandatory conventions:**
- Container name: `${HARBOR_CONTAINER_PREFIX}.${handle}`
- Main service name in compose MUST match the handle
- `env_file` includes both `./.env` and `./services/${handle}/override.env`
- Network: `harbor-network`
- All env vars follow `HARBOR_${HANDLE}_*` pattern (HANDLE = uppercase handle)
- Port mapping: `${HARBOR_${HANDLE}_HOST_PORT}:${internal_port}`
- Volume paths: `./services/${handle}/...` for config, `${HARBOR_${HANDLE}_WORKSPACE}/...` for data
- No `restart` policy — automatic restart is not expected in Harbor
- Image reference: `${HARBOR_${HANDLE}_IMAGE}:${HARBOR_${HANDLE}_VERSION}`

**If building from source** (no pre-built image), use `build` instead of `image`:
```yaml
build:
  context: ${HARBOR_${HANDLE}_GIT_REF}
  dockerfile: Dockerfile
```

**If the service needs multiple containers** (e.g., app + database), define them all in the
same compose file. The primary container must use the handle as its service name.
Auxiliary containers use `${handle}-<role>` naming (e.g., `windmill-db`, `windmill-worker`).

**Example** — a typical web service:
```yaml
services:
  myservice:
    container_name: ${HARBOR_CONTAINER_PREFIX}.myservice
    image: ${HARBOR_MYSERVICE_IMAGE}:${HARBOR_MYSERVICE_VERSION}
    env_file:
      - ./.env
      - ./services/myservice/override.env
    ports:
      - ${HARBOR_MYSERVICE_HOST_PORT}:8080
    volumes:
      - ${HARBOR_MYSERVICE_WORKSPACE}/data:/app/data
    networks:
      - harbor-network
```

## Step 4: Environment Variables

Add a section to `profiles/default.env` for the service.

**Port allocation:** Read the end of `default.env` to find the last used port.
Pick the next available port in the 33000–34999 range. Increment by 10 for services
needing multiple ports.

**Required variables:**
```bash
# Service Name
HARBOR_${HANDLE}_HOST_PORT=34XXX
HARBOR_${HANDLE}_IMAGE="repo/image"
HARBOR_${HANDLE}_VERSION="latest"
```

**Common additional variables:**
```bash
HARBOR_${HANDLE}_WORKSPACE=./${handle}        # persistent data dir
HARBOR_${HANDLE}_MODEL=some-default-model      # if service uses AI models
HARBOR_${HANDLE}_GIT_REF=https://github.com/...#branch  # if building from source
```

**Every env var referenced in the compose file must be defined in `default.env`.**

After editing `default.env`, propagate:
```bash
harbor config update
```

## Step 5: Service Metadata

Add an entry at the end of the `serviceMetadata` object in `app/src/serviceMetadata.ts`.

```typescript
${handle}: {
    name: 'Display Name',
    tags: [HST.${category}],  // + additional tags: HST.cli, HST.api, HST.rag, etc.
    projectUrl: 'https://github.com/...',
    wikiUrl: `${wikiUrl}/2.${cat_num}.${next_num}-${Category}-${Name}`,
    tooltip: 'Brief description for the UI.',
},
```

**Logo resolution:** After adding the metadata entry, resolve the service logo:
```bash
harbor dev add-logos --dry-run   # preview
harbor dev add-logos             # write to serviceMetadata.ts
```
This populates the `logo` field automatically from the project URL.

**Category → cat_num mapping:**
- Frontend → `2.1`
- Backend → `2.2`
- Satellite → `2.3`

**Find the next doc number:**
```bash
ls docs/2.${cat_num}.*.md | sort -t. -k3 -n | tail -1
```

**Available tags** (from `HST` enum): `backend`, `frontend`, `satellite`, `api`, `cli`,
`partial`, `builtIn`, `eval`, `audio`, `rag`, `image`, `workflows`, `tools`, `infra`.

Add `HST.cli` for CLI-only services (blocks "Open" button in the app).

## Step 6: Documentation

Create `docs/2.${cat_num}.${next_num}-${Category}-${ServiceName}.md`.

Follow the format from `docs/2.3.52-Satellite-Windmill.md` — it's the reference example.

**Required sections:**

```markdown
### [Service Name](https://github.com/repo-link)

> Handle: `${handle}`<br/>
> URL: [http://localhost:PORT](http://localhost:PORT)

Brief description of what the service does.

## Starting

\`\`\`bash
harbor pull ${handle}   # or harbor build ${handle}
harbor up ${handle} --open
\`\`\`

First-launch notes (default credentials, setup steps, etc.)

## Configuration

### Environment Variables

Following options can be set via [`harbor config`](./3.-Harbor-CLI-Reference.md#harbor-config):

\`\`\`bash
# Document every HARBOR_${HANDLE}_* variable with descriptions
\`\`\`

### Volumes

Describe persistent data and configuration mounts.

## Troubleshooting

\`\`\`bash
harbor logs ${handle}
\`\`\`

Common issues and solutions.

## Links

- [Official Documentation](...)
- [GitHub Repository](...)
```

**Rules:**
- Reference Harbor CLI commands, not raw Docker commands
- Document ALL env vars from `default.env`
- No behavior should surprise the user — if you add it, document it

## Step 7: Service Directory

Create `services/${handle}/.gitignore` for persistent data directories:

```
data/
cache/
logs/
```

Add any config files, entrypoints, or Dockerfiles the service needs into `services/${handle}/`.

## Step 8: Cross-Service Integration (If Needed)

Cross-files are applied when multiple services run together. They live in `services/` with
the naming pattern `compose.x.${handle}.${other}.yml`.

**When to create cross-files:**

| Integration | File | Purpose |
|---|---|---|
| Ollama | `compose.x.${handle}.ollama.yml` | Set Ollama URL env vars, add `depends_on` |
| GPU | `compose.x.${handle}.nvidia.yml` | GPU passthrough via deploy.resources |
| Traefik | `compose.x.traefik.${handle}.yml` | Reverse proxy labels |

**Ollama integration pattern:**
```yaml
services:
  ${handle}:
    depends_on:
      - ollama
    environment:
      - OLLAMA_API_BASE=${HARBOR_OLLAMA_INTERNAL_URL}
```

Check the service's docs for the correct Ollama env var name. Common variants:
`OLLAMA_API_BASE`, `OLLAMA_URL`, `OLLAMA_BASE_URL`, `OLLAMA_HOST`.

## Step 9: Test

**Build/pull first:**
```bash
harbor pull ${handle}   # pre-built image
harbor build ${handle}  # source build
```

**Start and verify:**
```bash
harbor up ${handle}
harbor logs ${handle}
```

**Check for:**
- Service starts without errors in logs
- Port is accessible: `curl -s http://localhost:${PORT}` or `harbor open ${handle}`
- If it has an API, make a test request
- If it depends on other services, test with them running

**Clean up after testing:**
```bash
harbor down ${handle}
```

## Validation Checklist

Before declaring the service complete, verify all of these:

- [ ] Handle is unique and valid
- [ ] Compose file follows all conventions (naming, env_file, network, no restart)
- [ ] All env vars in compose are defined in `default.env`
- [ ] `harbor config update` ran after editing `default.env`
- [ ] Metadata entry in `serviceMetadata.ts` with correct category and doc link
- [ ] Documentation created with all required sections
- [ ] `.gitignore` in service directory covers generated files
- [ ] Service starts successfully (`harbor up ${handle}`)
- [ ] Logs show healthy startup (`harbor logs ${handle}`)
- [ ] Cross-files created for relevant integrations
- [ ] `harbor dev add-logos` ran to resolve the service logo (or added manually)

## Common Pitfalls

- **Forgetting `harbor config update`** after editing `default.env` — your `.env` won't
  have the new variables and the service will fail with empty substitutions.
- **Wrong volume paths** — must use `./services/${handle}/...` (relative to repo root),
  not absolute paths.
- **Setting `restart: always`** — Harbor doesn't expect auto-restart; omit the policy.
- **Editing `.env` directly** — always use `harbor config set` or edit `default.env` +
  `harbor config update`.
- **Mismatched service name** — the primary compose service name must equal the handle.
