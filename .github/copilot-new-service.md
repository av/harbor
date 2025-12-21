# Adding new service

This file outlines a specific step-by-step workflow to follow in order to add a new service to this repository. This guide is designed to enable autonomous service addition by AI agents.

## This repository

This repository is a [very large modular Docker Compose project](../docs/6.-Harbor-Compose-Setup.md) controlled by a dedicated CLI (`harbor.sh`) that allows to dynamically match wanted files and configs based on the services user wants to run.

## What is a service?

In this repository, a service is a:
- piece of dedicated compose config, in a `compose.<service>.yml` file
  - It may include multiple docker compose services, representing a single software project
- a folder `<service>` that contains:
  - any configuration files needed for the service to run
  - any volume mounts needed for the service to run
  - a Dockerfile if the service needs one
  - an entrypoint if the service needs one
  - any scripts needed for the service to run
  - `override.env` file for the service
- piece of metadata in the `app/src/serviceMetadata.ts`
  - A service can be tagged with one or more categories, see `HST` in the same file
  - A service must have a short description for the in-app tooltip
- a documentation file in the `docs/<Doc Name>.md`
  - Docs for the services are split into `Backend`, `Frontend`, `Satellite` categories
  - Each category has its own numeration scheme:
    - `2.1.N-Frontend-<Service-Name>.md` for Frontend services
    - `2.2.N-Backend-<Service-Name>.md` for Backend services
    - `2.3.N-Satellite-<Service-Name>.md` for Satellite services
- Extra [cross-files](../docs/6.-Harbor-Compose-Setup.md#cross-service-file) when service needs to react to presence of the other services and/or [capabilities](../docs/3.-Harbor-CLI-Reference.md#capabilities-detection)
- A section in the `profiles/default.env` with environment variables for the service

## Autonomous Service Addition Workflow

Follow these steps in order to add a new service. Each step includes validation criteria.

### Step 0: Gather Information

**Requirements:**
- User provided a name or a link to a github repo
  - For a name - identify a specific repository associated with the name, if ambiguous, ask for clarification
  - For a link - ensure the link is valid and points to a GitHub repository
- In the repo - find documentation and/or code for Service's Docker config
  - Use `githubRepo` and `jina` tools for learning about the repository
  - If unsure - clarify with the user where it can be found
- Repo could have one of:
  - Links to prebuilt Docker images on Docker Hub or GitHub Container Registry or other registries
  - Dockerfile in the root or a `docker` subfolder
  - Docker Compose project in a root or a `docker` subfolder

### Step 1: Service Handle Selection

**Requirements:**
- Handle must be unique (check existing `compose.*.yml` files)
- Must contain only lowercase letters, numbers, and hyphens
- Should be short and representative of the service
- Must not conflict with existing handles in `serviceMetadata.ts`

**Validation:**
```bash
# Check if handle exists
ls compose.${handle}.yml 2>/dev/null && echo "Handle exists!" || echo "Handle available"
grep -q "^  ${handle}:" app/src/serviceMetadata.ts && echo "Handle in metadata!" || echo "Metadata available"
```

### Step 2: Use Scaffold Script

**Action:**
```bash
deno run -A ./.scripts/scaffold.ts ${handle}
```

**Generated files:**
- `compose.${handle}.yml` - Basic compose structure
- `${handle}/override.env` - Service-specific environment file

**Validation:**
- Both files should exist and have basic content

### Step 3: Complete Compose Configuration

**Required compose.yml structure:**
```yaml
services:
  ${handle}:
    container_name: ${HARBOR_CONTAINER_PREFIX}.${handle}
    image: ${HARBOR_${HANDLE}_IMAGE}:${HARBOR_${HANDLE}_VERSION}
    env_file:
      - ./.env
      - ./${handle}/override.env
    networks:
      - harbor-network
    # Add ports, volumes, healthcheck as needed
```

**Key requirements:**
- Container name must use `${HARBOR_CONTAINER_PREFIX}.${handle}` format
- Must include both `.env` and service override env file
- Must use harbor-network
- Environment variables must follow `HARBOR_${HANDLE}_*` pattern
- If service exposes ports, use `${HARBOR_${HANDLE}_HOST_PORT}:${internal_port}` format
- Main container in the compose file MUST match the service handle
- You must not set `restart` policy in the compose file, automatic restart is not expected and considered an error

### Step 4: Add Environment Variables to profiles/default.env

**Required pattern:**
```bash
# ${service_name}
HARBOR_${HANDLE}_HOST_PORT=33XXX  # Choose unique port 33000-34000 range
HARBOR_${HANDLE}_IMAGE="repo/image"
HARBOR_${HANDLE}_VERSION="latest"
# Add other service-specific variables as needed
```

**Port allocation:**
- Read the `default.env` file from the end to see the place to add new service variables and last used port
- Check existing ports in `profiles/default.env`
- Use next available port in 33000-34000 range
- Increment by 10s for services needing multiple ports

**Consistency**
- All environment variables referenced in the `compose.${handle}.yml` must be defined in the `profiles/default.env`
- All variables must use the `HARBOR_${HANDLE}_*` pattern in the profile, but not necessarily in the compose file

### Step 5: Add Service Metadata

**File:** `app/src/serviceMetadata.ts`

**Add entry:**
Add new entry at the end of the `serviceMetadata` object.
```typescript
${handle}: {
    name: '${Service Display Name}',
    tags: [HST.${category}], // backend, frontend, or satellite + additional tags
    wikiUrl: `${wikiUrl}/2.${category_num}.${next_num}-${Category}:-${Service-Name}`,
    tooltip: '${Brief description for UI tooltip}',
},
```

**Category mapping:**
- Backend services: HST.backend, category_num = 2
  - Backends are used for inference services for LLMs and other models (TTS/STT, etc.)
- Frontend services: HST.frontend, category_num = 1
  - Frontends are Web UIs for interacting with LLMs
- Satellite services: HST.satellite, category_num = 3
  - Satellites are CLI tools, utilities, Web UIs for doing specific tasks utilising LLMs or other services in Harbor

**Find next document number:**
```bash
# For backend services
ls docs/2.2.*.md | wc -l
# For frontend services
ls docs/2.1.*.md | wc -l
# For satellite services
ls docs/2.3.*.md | wc -l
```

### Step 6: Create Documentation

**File pattern:** `docs/2.${category_num}.${next_num}-${Category}-${Service-Name}.md`

**Required sections:**

```harbor-service-doc(markdown)
### [${Service Name}](LINK TO ORIGINAL REPO)

> Handle: `<service handle>`<br/>
> URL: [http://localhost:<DEFAULT HOST PORT>](http://localhost:<DEFAULT HOST PORT>)

Brief description of the service and its purpose.

## Starting

\`\`\`bash
# Pull if pre-built image
harbor pull <service handle>
# Build docs if needed
harbor build <service handle>

# Start the service
# --open for web UIs
# --tail for BEs
harbor up <service handle> --open
# For CLIs, implement an alias:
harbor <service handle> --help
\`\`\`

## Configuration

### Environment Variables

Following options can be set via [`harbor config`](./3.-Harbor-CLI-Reference.md#harbor-config):

\`\`\`bash
List all HARBOR_${HANDLE}_* variables with descriptions. Example:

# Main UI port
HARBOR_SERVICE_HOST_PORT          00000

# Workspace directory for persistent data
HARBOR_SERVICE_WORKSPACE          ./service
\`\`\`

### Volumes
Describe any persistent data or configuration mounts.
```

**Validation:**
- Documentation explains how to start the service, refers to troubleshooting guide
- Documentation refers to Harbor CLI commands, not Docker commands

### Step 8: Add to .gitignore (if needed)

**Add persistent data directories:**
- Create `.gitignore` in a service folder

```bash
# Add to .gitignore if service creates persistent data
echo "data/" >> .gitignore
echo "cache/" >> .gitignore
echo "logs/" >> .gitignore
```

### Step 10: Cross-Service Integration (Optional)

**If service needs integration with other services:**

Create cross-service files following pattern:
- `compose.x.${handle}.${other_service}.yml` - Integration with specific service
- `compose.x.${handle}.nvidia.yml` - GPU support
- `compose.x.traefik.${handle}.yml` - Reverse proxy integration

#### Ollama Integration Pattern

When integrating a service that supports Ollama, create a `compose.x.${handle}.ollama.yml` file to auto-configure Ollama connectivity:

```yaml
services:
  ${handle}:
    environment:
      - <SERVICE_OLLAMA_VAR>=${HARBOR_OLLAMA_INTERNAL_URL}
```

**Example for Open Notebook** (`compose.x.opennotebook.ollama.yml`):
```yaml
services:
  opennotebook:
    environment:
      - OLLAMA_API_BASE=${HARBOR_OLLAMA_INTERNAL_URL}
```

This pattern allows the service to automatically connect to Ollama when both are running in the Harbor network. The `HARBOR_OLLAMA_INTERNAL_URL` defaults to `http://ollama:11434`.

**Common Ollama environment variable names:**
- `OLLAMA_API_BASE` - Most common (Open WebUI, Open Notebook, etc.)
- `OLLAMA_URL` - Alternative naming (Parllama, etc.)
- `OLLAMA_BASE_URL` - Another variant
- `OLLAMA_HOST` - Less common

Check the service's documentation or environment variable configuration to identify the correct variable name.

### Validation Checklist

Before considering the service complete, verify:

- [ ] Unique handle selected and validated
- [ ] Scaffold script executed successfully
- [ ] Compose file follows required structure with proper naming
- [ ] Environment variables added to `profiles/default.env` with unique port
- [ ] Service metadata added to `serviceMetadata.ts` with correct category
- [ ] Documentation created following naming convention
- [ ] Service directory created with necessary files
- [ ] Persistent data paths added to `.gitignore` if needed
- [ ] Service starts successfully with `harbor up ${handle}`
- [ ] Service accessible via `harbor open ${handle}` (if applicable)
- [ ] Service logs show healthy startup via `harbor logs ${handle}`
- [ ] Cross-service integrations added if required

### Common Patterns by Service Type

**Backend Services (AI/LLM):**
- Usually need GPU support (`compose.x.${handle}.nvidia.yml`)
- Often integrate with frontends via cross-files
- Typically expose OpenAI-compatible APIs
- Need model download/cache volumes
- Port range: 33800-33999

**Frontend Services (Web UIs):**
- Often integrate with multiple backends via cross-files
- Usually need reverse proxy integration
- May need authentication/session persistence
- Port range: 33800-33899

**Satellite Services (CLI/Tools):**
- May not need exposed ports
- Often integrate with backends for API access
- May need special entrypoints or command handling
- Can be CLI-only (add HST.cli tag to block UI launch)

## Complete Reference

For detailed implementation guidance, see:
- [Adding a new service](../docs/7.-Adding-A-New-Service.md) - Complete workflow
- [Harbor Compose Setup](../docs/6.-Harbor-Compose-Setup.md) - Architecture details
- [Harbor CLI Reference](../docs/3.-Harbor-CLI-Reference.md) - CLI capabilities
- Existing services in the repository for implementation examples
