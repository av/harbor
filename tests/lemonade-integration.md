# Lemonade Service Integration Tests

## Prerequisites

1. Ensure Harbor CLI is available: `./harbor.sh --version`
2. Ensure Docker is running: `docker info`
3. Pull the lemonade image: `./harbor.sh pull lemonade`
4. Ensure no conflicting services are running: `./harbor.sh down`
5. Propagate config: `./harbor.sh config update`

## Test 1: Service Lifecycle & Health

**Steps:**
1. Run `./harbor.sh up lemonade` and wait for services to become healthy.
2. Run `docker ps --filter name=harbor.lemonade --format '{{.Names}} {{.Status}}'`.
3. Run `curl -sf http://localhost:34860/live`.
4. Run `./harbor.sh down`.
5. Run `docker ps --filter name=harbor.lemonade -q`.

**Expectations:**
1. The `harbor up` command exits 0.
2. Container `harbor.lemonade` is listed and status contains "healthy".
3. The `/live` endpoint returns `{"status":"ok"}` with HTTP 200.
4. The `harbor down` command exits 0.
5. No container ID is returned (container removed).

## Test 2: Compose Configuration Validation

**Steps:**
1. Run `docker compose -f compose.yml -f services/compose.lemonade.yml config` and capture output.
2. Run `docker compose -f compose.yml -f services/compose.lemonade.yml -f services/compose.x.lemonade.rocm.yml config` and capture output.
3. Run `docker compose -f compose.yml -f services/compose.lemonade.yml -f services/compose.webui.yml -f services/compose.x.webui.lemonade.yml config` and capture output.

**Expectations:**
1. First config resolves without error. Output contains:
   - `container_name:` with value containing `harbor.lemonade`
   - `image:` with value containing `ghcr.io/lemonade-sdk/lemonade-server`
   - Port mapping `34860` to `13305`
   - Volume mount to `/root/.cache/huggingface`
   - Volume mount to `/opt/lemonade/llama`
   - Volume mount to `/root/.cache/lemonade`
   - Network `harbor-network`
   - Environment `LEMONADE_LLAMACPP=cpu`
   - Healthcheck with `curl -sf http://localhost:13305/live`
   - No `restart` policy
2. ROCm config resolves without error. Output contains:
   - Device `/dev/kfd`
   - Device `/dev/dri`
   - Environment `LEMONADE_LLAMACPP=rocm` (overrides cpu)
3. WebUI cross-file resolves without error. Output contains:
   - Volume mount of `config.lemonade.json` to `/app/configs/config.lemonade.json`

## Test 3: OpenAI-Compatible API

**Steps:**
1. Run `./harbor.sh up lemonade` and wait for healthy.
2. Run `curl -sf http://localhost:34860/v1/models`.
3. Extract the first model ID from the response using `jq '.data[0].id'`.
4. Run `curl -sf -X POST http://localhost:34860/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer sk-lemonade" -d '{"model":"<model_id>","messages":[{"role":"user","content":"Say hello in exactly one word."}],"max_tokens":10}'`.
5. Run `./harbor.sh down`.

**Expectations:**
1. Service starts and becomes healthy.
2. The `/v1/models` endpoint returns JSON with a non-empty `data` array.
3. A model ID string is extracted (non-empty).
4. The chat completions response contains a `choices` array with at least one entry that has a `message.content` field (non-empty string).
5. Clean shutdown.

## Test 4: Ollama-Compatible API

**Steps:**
1. Run `./harbor.sh up lemonade` and wait for healthy.
2. Run `curl -sf http://localhost:34860/api/tags`.
3. Run `curl -sf http://localhost:34860/api/version`.
4. Run `./harbor.sh down`.

**Expectations:**
1. Service starts and becomes healthy.
2. The `/api/tags` endpoint returns JSON with a `models` key (array).
3. The `/api/version` endpoint returns JSON with a `version` key (non-empty string).
4. Clean shutdown.

## Test 5: Environment Variable Propagation

**Steps:**
1. Run `grep 'HARBOR_LEMONADE_HOST_PORT' .env`.
2. Run `grep 'HARBOR_LEMONADE_IMAGE' .env`.
3. Run `grep 'HARBOR_LEMONADE_VERSION' .env`.
4. Run `grep 'HARBOR_LEMONADE_WORKSPACE' .env`.
5. Run `grep 'HARBOR_LEMONADE_LLAMACPP' .env`.
6. Run `./harbor.sh up lemonade` and wait for healthy.
7. Run `docker exec harbor.lemonade env | grep LEMONADE`.
8. Run `./harbor.sh down`.

**Expectations:**
1. `HARBOR_LEMONADE_HOST_PORT=34860` is present in `.env`.
2. `HARBOR_LEMONADE_IMAGE="ghcr.io/lemonade-sdk/lemonade-server"` is present.
3. `HARBOR_LEMONADE_VERSION="latest"` is present.
4. `HARBOR_LEMONADE_WORKSPACE="./lemonade"` is present.
5. `HARBOR_LEMONADE_LLAMACPP="cpu"` is present.
6. Service starts successfully.
7. Container environment includes `LEMONADE_LLAMACPP=cpu`, `LEMONADE_HOST=0.0.0.0`, `LEMONADE_PORT=13305`.
8. Clean shutdown.

## Test 6: Open WebUI Integration

**Steps:**
1. Verify config file exists: `cat services/webui/configs/config.lemonade.json`.
2. Run `./harbor.sh up lemonade webui` and wait for healthy.
3. From the webui container, test DNS resolution: `docker exec harbor.webui curl -sf http://lemonade:13305/live`.
4. From the webui container, verify config was mounted: `docker exec harbor.webui cat /app/configs/config.lemonade.json`.
5. From the webui container, test the OpenAI endpoint: `docker exec harbor.webui curl -sf http://lemonade:13305/v1/models`.
6. Run `./harbor.sh down`.

**Expectations:**
1. Config file exists and contains `"api_base_urls": ["http://lemonade:13305/v1"]`.
2. Both services start and become healthy.
3. Lemonade health endpoint is reachable from webui container, returns `{"status":"ok"}`.
4. Config file is mounted at the expected path, content matches source.
5. Models endpoint is reachable from webui container, returns JSON with `data` array.
6. Clean shutdown.

## Test 7: Service Metadata & Documentation

**Steps:**
1. Run `grep -A 8 'lemonade:' app/src/serviceMetadata.ts`.
2. Check documentation exists: `test -f docs/2.2.19-Backend-Lemonade.md && echo EXISTS`.
3. Check screenshot exists: `test -f docs/harbor-lemonade.png && echo EXISTS`.
4. Verify doc references correct port: `grep '34860' docs/2.2.19-Backend-Lemonade.md`.

**Expectations:**
1. Metadata entry exists with `name: 'Lemonade'`, tags include `HST.backend`, `HST.api`, `HST.audio`, `HST.image`, has a `projectUrl`, `wikiUrl` contains `2.2.19`, and has a `logo` field.
2. Documentation file exists (prints "EXISTS").
3. Screenshot file exists (prints "EXISTS").
4. Port 34860 is referenced in the documentation.

## Test 8: Volume Persistence

**Steps:**
1. Run `./harbor.sh up lemonade` and wait for healthy.
2. Check that workspace directories are created: `ls -la lemonade/`.
3. Check lemonade cache directory has content: `ls lemonade/cache/`.
4. Run `./harbor.sh down`.
5. Verify workspace directories still exist after down: `ls -la lemonade/`.

**Expectations:**
1. Service starts and becomes healthy.
2. `lemonade/` directory exists with `llama/` and `cache/` subdirectories.
3. Cache directory has content (at minimum a `config.json` or similar).
4. Clean shutdown.
5. Workspace directories persist after container removal.

## Test 9: Web UI Accessibility

**Steps:**
1. Run `./harbor.sh up lemonade` and wait for healthy.
2. Run `curl -sf -o /dev/null -w '%{http_code}' http://localhost:34860/`.
3. Run `curl -sf http://localhost:34860/ | head -c 500`.
4. Run `./harbor.sh down`.

**Expectations:**
1. Service starts and becomes healthy.
2. Root URL returns HTTP 200.
3. Response body contains HTML (includes `<html` or `<!DOCTYPE` or `<head`).
4. Clean shutdown.

## Test 10: .gitignore Coverage

**Steps:**
1. Run `cat services/lemonade/.gitignore`.

**Expectations:**
1. File contains `llama/` and `cache/` entries to ignore persistent data directories.
