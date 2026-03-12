#!/usr/bin/env bash
set -eo pipefail

HARBOR_ROOT="${HARBOR_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
log_art() { echo "[artifacts] $*"; }

ARTIFACTS_DIR="${HARBOR_INT_ARTIFACTS_DIR:-${1:-./integration/artifacts/unknown}}"
log_art "Collecting artifacts to: $ARTIFACTS_DIR"
mkdir -p "$ARTIFACTS_DIR"

# 1. Environment metadata (filter sensitive vars)
env | sort | grep -Ev '^[^=]*((SECRET|TOKEN|PASSWORD|API_KEY)[^=]*|_KEY)=' \
  > "$ARTIFACTS_DIR/env-metadata.txt" 2>&1 || true

# 2. docker ps (all Harbor containers: name starts with "harbor.")
docker ps -a --filter "name=harbor." \
  --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}" \
  > "$ARTIFACTS_DIR/docker-ps.txt" 2>&1 || true

# 3. mock-openai compose ps (explicit compose file to avoid override.env errors)
if [[ -f "${HARBOR_ROOT}/.env" ]]; then
  docker compose \
    -f "${HARBOR_ROOT}/services/compose.mock-openai.yml" \
    --env-file "${HARBOR_ROOT}/.env" \
    ps \
    > "$ARTIFACTS_DIR/docker-compose-mock-ps.txt" 2>&1 || true
fi

# 4. Container logs — only Harbor containers (filter by "harbor." prefix)
# Skip containers whose logs were already captured by _teardown (non-empty file).
mkdir -p "$ARTIFACTS_DIR/container-logs"
harbor_containers=$(docker ps -a --filter "name=harbor." --format "{{.Names}}" 2>/dev/null || true)
if [[ -n "$harbor_containers" ]]; then
  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    local_log="$ARTIFACTS_DIR/container-logs/${container}.txt"
    if [[ -s "$local_log" ]]; then
      log_art "  Skipping $container (logs already captured)"
      continue
    fi
    log_art "  Collecting logs for: $container"
    docker logs "$container" > "$local_log" 2>&1 || true
  done <<< "$harbor_containers"
else
  log_art "  No Harbor containers found"
fi

# 5. harbor ps (scoped to mock-openai to avoid override.env errors for unconfigured services)
bash "${HARBOR_ROOT}/harbor.sh" ps mock-openai > "$ARTIFACTS_DIR/harbor-ps.txt" 2>&1 || true

# 6. harbor ls
bash "${HARBOR_ROOT}/harbor.sh" ls > "$ARTIFACTS_DIR/harbor-ls.txt" 2>&1 || true

# 7. OS info
{ uname -a; echo "---"; cat /etc/os-release 2>/dev/null || true; } \
  > "$ARTIFACTS_DIR/os-info.txt" 2>&1 || true

# 8. Run summary
{
  echo "Run ID:    ${HARBOR_INT_RUN_ID:-unknown}"
  echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "Status:    ${HARBOR_INT_TEST_STATUS:-unknown}"
  echo "Artifacts: $ARTIFACTS_DIR"
} > "$ARTIFACTS_DIR/run-summary.txt"

log_art "Collection complete: $ARTIFACTS_DIR"
ls -lh "$ARTIFACTS_DIR"
