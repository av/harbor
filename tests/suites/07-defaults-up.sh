#!/usr/bin/env bash
# Suite: defaults-up
#
# Fresh-install defaults path. On a pristine row, a bare `harbor up` must:
#   - bring up exactly the default services: webui + llamacpp (no ollama)
#   - print the first-boot notices (webui model download, llamacpp empty cache)
#   - hold `--wait` until webui is actually healthy (first boot downloads
#     the embedding model before the HTTP port serves)
#   - leave the llamacpp router answering /v1/models even with an empty HF cache
#   - land webui's merged config as flat per-key dot-path entries
#     (guards shared/json_config_merger.py --flatten and the *.enabled→*.enable alias)
#
# Heavy: pulls the webui + llamacpp images inside the nested dockerd, so it is
# registered in HEAVY_SUITE_DEFAULTS (tests/stage-repo.ts) — one distro, serial.
set -euo pipefail

suite_log() { echo "[defaults-up] $*"; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-/opt/harbor-test/repo}"
# shellcheck source=../lib/readiness.sh
source "${HARBOR_TEST_REPO}/tests/lib/readiness.sh"

WEBUI_PORT="${HARBOR_WEBUI_HOST_PORT:-33801}"
LLAMACPP_PORT="${HARBOR_LLAMACPP_HOST_PORT:-33831}"
UP_LOG="/opt/harbor-test/artifacts/defaults-up/up.log"
mkdir -p "$(dirname "$UP_LOG")"

cleanup() {
  local rc=$?
  suite_log "Tearing down (trap, exit=${rc})..."
  harbor down >/dev/null 2>&1 || true
  return $rc
}
trap cleanup EXIT

suite_log "harbor defaults ls"
defaults="$(harbor defaults ls)"
echo "$defaults"
echo "$defaults" | grep -qx "webui" || { suite_log "FAIL: webui not in defaults"; exit 1; }
echo "$defaults" | grep -qx "llamacpp" || { suite_log "FAIL: llamacpp not in defaults"; exit 1; }
if echo "$defaults" | grep -q "ollama"; then
  suite_log "FAIL: ollama must not be in defaults"
  exit 1
fi

suite_log "harbor up (defaults; first pull can take a while)..."
harbor up 2>&1 | tee "$UP_LOG"

suite_log "Checking first-boot notices in up output..."
grep -q "First Open WebUI start downloads embedding/audio models" "$UP_LOG" \
  || { suite_log "FAIL: missing webui first-boot notice"; exit 1; }
grep -q "llama.cpp has no local models yet" "$UP_LOG" \
  || { suite_log "FAIL: missing llamacpp empty-cache notice"; exit 1; }

suite_log "Checking running containers..."
harbor ps
if harbor ps | grep -q "ollama"; then
  suite_log "FAIL: ollama container running on defaults path"
  exit 1
fi

suite_log "Waiting for webui /health..."
wait_for_http "http://localhost:${WEBUI_PORT}/health" 900 5

suite_log "Checking webui container health status..."
health="$(docker inspect --format '{{.State.Health.Status}}' harbor.webui)"
[ "$health" = "healthy" ] || { suite_log "FAIL: webui health=${health}"; exit 1; }

suite_log "Checking llamacpp router /v1/models..."
models_json="$(curl -fsS "http://localhost:${LLAMACPP_PORT}/v1/models")"
echo "$models_json" | jq -e '.data | type == "array"' >/dev/null \
  || { suite_log "FAIL: llamacpp /v1/models did not return a model array"; exit 1; }

suite_log "Checking merged webui config is flat per-key..."
# Open WebUI consumes the legacy import file at startup and renames it to
# old_config.json once the rows are in the DB — read whichever exists.
merged="$(docker exec harbor.webui sh -c 'cat /app/backend/data/old_config.json 2>/dev/null || cat /app/backend/data/config.json')"
# The --flatten merger must emit dot-path keys, never nested legacy blobs.
echo "$merged" | jq -e '."openai.enable" == true' >/dev/null \
  || { suite_log "FAIL: openai.enable not true (enabled→enable alias broken?)"; exit 1; }
echo "$merged" | jq -e '."openai.api_base_urls" | type == "array"' >/dev/null \
  || { suite_log "FAIL: openai.api_base_urls not a flat array key"; exit 1; }
echo "$merged" | jq -e 'has("openai") or has("audio") or has("rag") | not' >/dev/null \
  || { suite_log "FAIL: nested legacy top-level blob present in merged config"; exit 1; }

suite_log "Checking webui DB config rows are per-key..."
docker exec harbor.webui python - <<'PY'
import sqlite3, sys
conn = sqlite3.connect("/app/backend/data/webui.db")
cols = [r[1] for r in conn.execute("PRAGMA table_info(config)")]
print("config table columns:", cols)
if "key" not in cols:
    sys.exit("FAIL: config table has no per-key schema (columns: %s)" % cols)
keys = sorted(r[0] for r in conn.execute("SELECT key FROM config"))
print("rows:", len(keys))
dotted = [k for k in keys if "." in k]
if "openai.enable" not in keys:
    sys.exit("FAIL: openai.enable row missing from config table")
if not dotted:
    sys.exit("FAIL: no dot-path config rows found")
for bad in ("openai", "audio"):
    if bad in keys:
        sys.exit("FAIL: nested legacy blob row '%s' present" % bad)
print("OK: %d dot-path rows, openai.enable present" % len(dotted))
PY

suite_log "harbor down"
harbor down
trap - EXIT

suite_log "OK"
