#!/usr/bin/env bash
# Suite: speaches-webui
#
# Regression guard for the speaches ↔ Open WebUI STT/TTS integration.
# On a fresh row, `harbor up --no-defaults webui speaches` must:
#   - print the speaches first-boot notice and hold `--wait` while
#     speaches-init pulls the STT/TTS models (compose healthcheck + init
#     depends_on service_healthy)
#   - land webui's audio config as flat per-key rows pointing BOTH
#     STT and TTS at http://speaches:8000/v1 with engine=openai
#     (guards config.speaches.json through the --flatten merger)
#   - serve a webui-proxied TTS request: /api/v1/audio/speech → real audio
#   - round-trip STT: transcribe that audio via /api/v1/audio/transcriptions
#
# Heavy: pulls webui + speaches images and the Kokoro/whisper models inside
# the nested dockerd — registered in HEAVY_SUITE_DEFAULTS (ubuntu-2404, serial).
set -euo pipefail

suite_log() { echo "[speaches-webui] $*"; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-/opt/harbor-test/repo}"
# shellcheck source=../lib/readiness.sh
source "${HARBOR_TEST_REPO}/tests/lib/readiness.sh"

WEBUI_PORT="${HARBOR_WEBUI_HOST_PORT:-33801}"
ART_DIR="/opt/harbor-test/artifacts/speaches-webui"
UP_LOG="${ART_DIR}/up.log"
mkdir -p "$ART_DIR"

cleanup() {
  local rc=$?
  suite_log "Tearing down (trap, exit=${rc})..."
  harbor down >/dev/null 2>&1 || true
  return $rc
}
trap cleanup EXIT

suite_log "harbor up --no-defaults webui speaches (first pull can take a while)..."
harbor up --no-defaults webui speaches 2>&1 | tee "$UP_LOG"

suite_log "Checking speaches first-boot notice in up output..."
grep -q "First speaches start downloads STT/TTS models" "$UP_LOG" \
  || { suite_log "FAIL: missing speaches first-boot notice"; exit 1; }

suite_log "Checking speaches-init pulled the models successfully..."
init_exit="$(docker inspect --format '{{.State.ExitCode}}' harbor.speaches-init)"
[ "$init_exit" = "0" ] || {
  suite_log "FAIL: speaches-init exit=${init_exit}"
  docker logs harbor.speaches-init >&2 || true
  # The init container only sees HTTP status codes — the real failure
  # (e.g. an HF download error behind a 500) is in the speaches server log.
  suite_log "speaches server log (last 100 lines):"
  docker logs --tail 100 harbor.speaches >&2 || true
  exit 1
}

suite_log "Waiting for webui /health..."
wait_for_http "http://localhost:${WEBUI_PORT}/health" 900 5

suite_log "Checking merged webui config points STT/TTS at speaches..."
# Open WebUI renames data/config.json → old_config.json after import.
merged="$(docker exec harbor.webui sh -c 'cat /app/backend/data/old_config.json 2>/dev/null || cat /app/backend/data/config.json')"
echo "$merged" | jq -e '."audio.tts.openai.api_base_url" == "http://speaches:8000/v1"' >/dev/null \
  || { suite_log "FAIL: audio.tts.openai.api_base_url not pointed at speaches"; exit 1; }
echo "$merged" | jq -e '."audio.stt.openai.api_base_url" == "http://speaches:8000/v1"' >/dev/null \
  || { suite_log "FAIL: audio.stt.openai.api_base_url not pointed at speaches"; exit 1; }
echo "$merged" | jq -e '."audio.tts.engine" == "openai" and ."audio.stt.engine" == "openai"' >/dev/null \
  || { suite_log "FAIL: audio engines not set to openai"; exit 1; }
echo "$merged" | jq -e '."audio.tts.model" | length > 0' >/dev/null \
  || { suite_log "FAIL: audio.tts.model empty"; exit 1; }
echo "$merged" | jq -e 'has("audio") | not' >/dev/null \
  || { suite_log "FAIL: nested legacy 'audio' blob present in merged config"; exit 1; }

suite_log "Checking webui DB config rows point at speaches..."
docker exec harbor.webui python - <<'PY'
import sqlite3, sys
conn = sqlite3.connect("/app/backend/data/webui.db")
cols = [r[1] for r in conn.execute("PRAGMA table_info(config)")]
val_col = "value" if "value" in cols else "data"
if "key" not in cols or val_col not in cols:
    sys.exit("FAIL: unexpected config table schema: %s" % cols)
rows = {k: str(v) for k, v in conn.execute("SELECT key, %s FROM config" % val_col)}
for key in ("audio.tts.openai.api_base_url", "audio.stt.openai.api_base_url"):
    val = rows.get(key)
    if val is None:
        sys.exit("FAIL: config row missing: %s" % key)
    if "speaches:8000" not in val:
        sys.exit("FAIL: %s = %r does not point at speaches" % (key, val))
if "audio" in rows:
    sys.exit("FAIL: nested legacy 'audio' blob row present")
print("OK: STT/TTS DB rows point at speaches")
PY

suite_log "Creating admin account for API access..."
token="$(curl -fsS -X POST "http://localhost:${WEBUI_PORT}/api/v1/auths/signup" \
  -H 'Content-Type: application/json' \
  -d '{"name":"harbor-test","email":"test@harbor.local","password":"harbor-test-pass"}' | jq -r '.token')"
[ -n "$token" ] && [ "$token" != "null" ] || { suite_log "FAIL: signup did not return a token"; exit 1; }

suite_log "TTS via webui proxy: /api/v1/audio/speech..."
tts_out="${ART_DIR}/tts-output.audio"
curl -fsS -X POST "http://localhost:${WEBUI_PORT}/api/v1/audio/speech" \
  -H "Authorization: Bearer ${token}" \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello from harbor."}' \
  -o "$tts_out" \
  || { suite_log "FAIL: TTS request failed"; exit 1; }
tts_size="$(stat -c '%s' "$tts_out" 2>/dev/null || stat -f '%z' "$tts_out")" # harbor-lint disable=HARBOR010
suite_log "TTS returned ${tts_size} bytes"
[ "$tts_size" -gt 1000 ] || { suite_log "FAIL: TTS output too small (${tts_size} bytes)"; exit 1; }
if dd if="$tts_out" bs=1 count=512 2>/dev/null | grep -qi '"detail"\|<html'; then
  dd if="$tts_out" bs=1 count=512 2>/dev/null >&2
  suite_log "FAIL: TTS returned an error payload, not audio"
  exit 1
fi

suite_log "STT round-trip via webui proxy: /api/v1/audio/transcriptions..."
stt_json="$(curl -fsS -X POST "http://localhost:${WEBUI_PORT}/api/v1/audio/transcriptions" \
  -H "Authorization: Bearer ${token}" \
  -F "file=@${tts_out};type=audio/mpeg;filename=tts.mp3")" \
  || { suite_log "FAIL: STT request failed"; exit 1; }
echo "$stt_json"
transcript="$(echo "$stt_json" | jq -r '.text // empty' | tr 'A-Z' 'a-z')"
case "$transcript" in
  *hello*harbor*) suite_log "STT transcript OK: ${transcript}" ;;
  *)
    suite_log "FAIL: STT transcript did not round-trip (got: '${transcript}')"
    exit 1
    ;;
esac

suite_log "harbor down"
harbor down
trap - EXIT

suite_log "OK"
