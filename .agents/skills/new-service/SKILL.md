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

Create `services/${handle}/default.env` holding the service's `HARBOR_${HANDLE}_*`
defaults. Harbor loads it alongside `profiles/default.env` — same syntax, same
precedence — so new services keep their defaults next to their compose file
instead of appending to the shared profile. Only truly global keys
(`HARBOR_SERVICES_DEFAULT`, `HARBOR_LOG_LEVEL`, ...) belong in
`profiles/default.env`.

**Port allocation:** Read the end of `profiles/default.env` and the other
`services/*/default.env` files to find the last used port.
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

**Every env var referenced in the compose file must be defined in a default env
file** — `services/${handle}/default.env` for service-specific keys,
`profiles/default.env` for global ones.

After editing a default env file, propagate:
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
- Document ALL env vars from `services/${handle}/default.env`
- No behavior should surprise the user — if you add it, document it

### Screenshot

Every new service ships with one screenshot of its UI in the docs.

- File: `docs/harbor-${handle}.png` — the `harbor-` prefix is the convention for service screenshots; older shots without the prefix predate it.
- Embed near the top of the doc, right after the lead paragraph, with a descriptive alt text.
- Capture during Step 9 (Test) while the service is up. For web UIs, use `agent-browser` so the screenshot comes from the same browser workflow used for validation:
  ```bash
  agent-browser open http://localhost:${PORT}/
  agent-browser wait --load networkidle
  agent-browser screenshot docs/harbor-${handle}.png
  agent-browser close
  ```
- Pick a frame that represents the actual product (a populated dashboard if state is easy to seed; otherwise the first-screen the user sees). 1280×800 is standard. Avoid login screens devoid of branding.

## Step 7: Service Directory

Create `services/${handle}/.gitignore` for persistent data directories:

```
data/
cache/
logs/
```

Add any config files, entrypoints, or Dockerfiles the service needs into `services/${handle}/`.

### Sidecars that need CLI tools — never `apk add` at runtime

If you add an init/bootstrap sidecar that needs tools beyond what `alpine:3.20` ships
(`curl`, `jq`, `sqlite`, `ssh-keygen`, etc.), **do not** install them with `apk add` in
the entrypoint. Every container creation re-pays the install cost: empirically `apk add
--no-cache curl jq` takes ~24s on each `harbor up`, blocking everything that depends on
the sidecar via `service_completed_successfully` (e.g. webui waiting on
`unsloth-studio-bootstrap`).

The correct pattern is one of:

**(a) Inline Dockerfile in compose** — preferred for sidecars wholly owned by one service:

```yaml
services:
  ${handle}-bootstrap:
    build:
      context: ./services/${handle}
      dockerfile_inline: |
        FROM alpine:3.20
        RUN apk add --no-cache curl jq
    entrypoint: ["/bin/sh", "/usr/local/bin/bootstrap.sh"]
    volumes:
      - ./services/${handle}/bootstrap.sh:/usr/local/bin/bootstrap.sh:ro
```

**(b) Standalone Dockerfile** — `services/${handle}/Dockerfile.bootstrap` + `build: { context, dockerfile }` — use when the sidecar pulls in non-trivial setup (multi-stage, COPYed assets) or could be shared across services.

Either way the apk install runs **once at build time**, not on every up. The build
itself is cached by Docker, so subsequent ups skip it entirely.

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

The goal is to prove the service is useful from an end-user point of view. Avoid superficial checks that do not validate the important workflow. A container starting, a port returning HTML, or `/health` returning OK is necessary but not sufficient.

**Build/pull first:**
```bash
harbor pull ${handle}   # pre-built image
harbor build ${handle}  # source build
```

**Start the user-facing scenario:**
```bash
harbor up ${handle}
```

If the service's main value depends on Harbor integrations, start the integrated scenario too. For example, for an AI app that should use local models and search, test the real workflow with:

```bash
harbor up ${handle} ollama searxng
```

**Validate the most important workflow:**
- Pick the one workflow an end user would run immediately after `harbor up`.
- For web frontends, use `agent-browser` to interact with the UI: sign up or log in, complete onboarding, configure/select the Harbor backend if needed, submit a real prompt/task/upload, and verify the expected result appears.
- For APIs, make the real API call that exercises the service's core feature, not just `/health`.
- For CLI services, run the primary command a user would run and verify the output is meaningful.
- If the service depends on other Harbor services, verify the integrated feature works end-to-end (for example, an LLM-backed response actually uses Ollama/llama.cpp; a search feature actually uses SearXNG).

Useful web UI loop:
```bash
agent-browser open http://localhost:${PORT}/
agent-browser snapshot -i
# interact with refs from the snapshot
agent-browser click @e3
agent-browser snapshot -i
```

Also check logs for errors after the workflow, not only during startup:
```bash
harbor logs ${handle}
```

**Clean up after testing:**
```bash
harbor down ${handle}
```

## Validation Checklist

Before declaring the service complete, verify all of these:

- [ ] Handle is unique and valid
- [ ] Compose file follows all conventions (naming, env_file, network, no restart)
- [ ] `services/${handle}/default.env` exists and is tracked by git
- [ ] All env vars in compose are defined in a default env file
- [ ] `harbor config update` ran after editing the default env file
- [ ] Metadata entry in `serviceMetadata.ts` with correct category and doc link
- [ ] Documentation created with all required sections
- [ ] Screenshot captured at `docs/harbor-${handle}.png` and embedded in the doc
- [ ] `.gitignore` in service directory covers generated files
- [ ] Service starts successfully (`harbor up ${handle}`)
- [ ] The primary end-user workflow was tested and works; not only startup/health/port checks
- [ ] Web UI services were validated with `agent-browser` interactions when applicable
- [ ] Logs show healthy behavior after the end-user workflow (`harbor logs ${handle}`)
- [ ] Cross-files created and end-to-end tested for relevant integrations
- [ ] `harbor dev add-logos` ran to resolve the service logo (or added manually)

## Common Pitfalls

- **Forgetting `harbor config update`** after editing a default env file — your `.env`
  won't have the new variables and the service will fail with empty substitutions.
- **Wrong volume paths** — must use `./services/${handle}/...` (relative to repo root),
  not absolute paths.
- **Setting `restart: always`** — Harbor doesn't expect auto-restart; omit the policy.
- **Editing `.env` directly** — always use `harbor config set` or edit
  `services/${handle}/default.env` + `harbor config update`.
- **Mismatched service name** — the primary compose service name must equal the handle.
