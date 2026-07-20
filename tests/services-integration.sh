#!/usr/bin/env bash
# Harbor services integration runner — automates tests/services-integration.md.
#
# Usage:
#   ./tests/services-integration.sh                 # run all CPU-safe groups (A B C D F G H I)
#   ./tests/services-integration.sh --groups B,G    # run selected groups
#   ./tests/services-integration.sh --list          # list groups and their checks
#
# Groups run SERIALLY (services share ports/GPU); every group ends with
# `harbor down` teardown, even on failure. Group E (comfyui) is excluded by
# default: the shipped image is CUDA-only — on a non-NVIDIA host the runner
# applies the `--cpu` workaround, but it is opt-in via `--groups E`.
#
# Never uses `harbor logs` (tails forever) — uses `docker logs` when needed.
# Prints one PASS/FAIL line per check plus a final summary; exits non-zero if
# any check failed. See tests/services-integration.md for the full spec and
# rationale behind each check (thinking-model token budgets, run-style vs
# up-style services, orphaned-slot cleanup, config overrides).
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
HARBOR=./harbor.sh

DEFAULT_GROUPS="A B C D F G H I"
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FAILED_CHECKS=""
MODEL=""

# Thinking models (Qwen3.5) burn small budgets entirely on reasoning_content.
MAX_TOKENS=2000
OPENCODE_MODEL="LiquidAI/LFM2.5-8B-A1B-GGUF:Q8_0"
OLLAMA_TINY_MODEL="qwen3:0.6b"

log() { echo "[services-it] $*"; }

record() {
  # record PASS|FAIL|SKIP <check-id> [detail]
  local result="$1" id="$2" detail="${3:-}"
  case "$result" in
    PASS) PASS_COUNT=$((PASS_COUNT + 1)) ;;
    SKIP) SKIP_COUNT=$((SKIP_COUNT + 1)) ;;
    *)
      FAIL_COUNT=$((FAIL_COUNT + 1))
      FAILED_CHECKS="$FAILED_CHECKS $id"
      ;;
  esac
  if [ -n "$detail" ]; then
    echo "$result: $id — $detail"
  else
    echo "$result: $id"
  fi
}

# Poll a URL until it returns HTTP 200. probe_200 <check-id> <url> <timeout_s>
probe_200() {
  local id="$1" url="$2" timeout_s="$3" waited=0 code=""
  while [ "$waited" -le "$timeout_s" ]; do
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url" 2>/dev/null)
    if [ "$code" = "200" ]; then
      record PASS "$id" "200 after ${waited}s"
      return 0
    fi
    sleep 5
    waited=$((waited + 5))
  done
  record FAIL "$id" "no 200 within ${timeout_s}s (last: ${code:-none}) at $url"
  return 1
}

svc_url() { "$HARBOR" url "$1" 2>/dev/null; }

# Save a harbor config value and set a new one; restore_config undoes all.
SAVED_KEYS=""
save_and_set_config() {
  local key="$1" value="$2" current
  current=$("$HARBOR" config get "$key" 2>/dev/null)
  SAVED_KEYS="$SAVED_KEYS $key=$current"
  "$HARBOR" config set "$key" "$value" >/dev/null
}

restore_config() {
  local pair key value
  for pair in $SAVED_KEYS; do
    key="${pair%%=*}"
    value="${pair#*=}"
    "$HARBOR" config set "$key" "$value" >/dev/null
    log "restored $key=$value"
  done
  SAVED_KEYS=""
}

# Remove stray run-style containers (harbor-<svc>-run-*) left by timeouts.
cleanup_run_containers() {
  local strays
  strays=$(docker ps -aq --filter 'name=harbor-.*-run-' 2>/dev/null)
  if [ -n "$strays" ]; then
    log "removing stray run containers"
    # shellcheck disable=SC2086
    docker rm -f $strays >/dev/null 2>&1
  fi
}

teardown() {
  log "teardown: harbor down"
  "$HARBOR" down >/dev/null 2>&1
  cleanup_run_containers
  restore_config
}

resolve_model() {
  local url
  url=$(svc_url llamacpp)
  MODEL=$(curl -s -m 10 "$url/v1/models" | jq -r '.data[].id' 2>/dev/null \
    | grep -i 'Qwen3.5-0.8B' | head -1)
  if [ -z "$MODEL" ]; then
    MODEL=$(curl -s -m 10 "$url/v1/models" | jq -r '.data[0].id' 2>/dev/null)
  fi
  log "MODEL=$MODEL"
  [ -n "$MODEL" ]
}

wait_llamacpp_ready() {
  local id="$1"
  probe_200 "$id" "$(svc_url llamacpp)/health" 300
}

llamacpp_chat() {
  # llamacpp_chat <model> — prints content, exit 0 on non-empty
  local url
  url=$(svc_url llamacpp)
  curl -s -m 300 "$url/v1/chat/completions" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -er '.choices[0].message.content | select(length > 0)'
}

group_A() {
  log "Group A: llamacpp webui boost litellm (+aichat via run)"
  "$HARBOR" up llamacpp webui boost litellm >/dev/null 2>&1

  wait_llamacpp_ready "A1 llamacpp ready" || { teardown; return; }
  resolve_model || { record FAIL "A1 model discovery" "no models in router"; teardown; return; }

  # Chat completion — thinking model is flaky-once; allow one retry.
  if llamacpp_chat "$MODEL" >/dev/null 2>&1 || llamacpp_chat "$MODEL" >/dev/null 2>&1; then
    record PASS "A1 llamacpp chat completion"
  else
    record FAIL "A1 llamacpp chat completion" "empty content twice"
  fi

  local waited=0 health=""
  while [ "$waited" -le 300 ]; do
    health=$(docker inspect -f '{{.State.Health.Status}}' harbor.webui 2>/dev/null)
    [ "$health" = "healthy" ] && break
    sleep 5; waited=$((waited + 5))
  done
  if [ "$health" = "healthy" ]; then
    record PASS "A2 webui healthy"
  else
    record FAIL "A2 webui healthy" "status: ${health:-missing}"
  fi
  local webui_version
  webui_version=$(curl -s -m 10 "$(svc_url webui)/api/version" | jq -er '.version' 2>/dev/null)
  if [ -n "$webui_version" ]; then
    record PASS "A2 webui version" "$webui_version"
  else
    record FAIL "A2 webui version"
  fi

  probe_200 "A3 boost ready" "$(svc_url boost)/health" 120
  local boost_url boosted
  boost_url=$(svc_url boost)
  if curl -s -m 10 -H 'Authorization: Bearer sk-boost' "$boost_url/v1/models" \
    | jq -er '.data | length > 0' >/dev/null 2>&1; then
    record PASS "A3 boost model list"
  else
    record FAIL "A3 boost model list"
  fi
  boosted=$(curl -s -m 10 -H 'Authorization: Bearer sk-boost' "$boost_url/v1/models" \
    | jq -r '.data[].id' | grep -iF "$MODEL" | head -1)
  if [ -n "$boosted" ] && curl -s -m 300 "$boost_url/v1/chat/completions" \
    -H 'Authorization: Bearer sk-boost' -H 'Content-Type: application/json' \
    -d "{\"model\":\"$boosted\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -er '.choices[0].message.content | length > 0' >/dev/null 2>&1; then
    record PASS "A3 boost completion" "$boosted"
  else
    record FAIL "A3 boost completion" "boosted id: ${boosted:-none}"
  fi
  local code
  code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$boost_url/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$boosted\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}")
  if [ "$code" = "401" ]; then
    record PASS "A3 boost 401 without auth"
  else
    record FAIL "A3 boost 401 without auth" "got $code"
  fi

  probe_200 "A4 litellm ready" "$(svc_url litellm)/health/liveliness" 120
  local litellm_key
  litellm_key=$("$HARBOR" config get litellm.master.key 2>/dev/null)
  if curl -s -m 10 -H "Authorization: Bearer ${litellm_key:-sk-litellm}" \
    "$(svc_url litellm)/v1/models" | jq -er '.data' >/dev/null 2>&1; then
    record PASS "A4 litellm models" "empty list is expected (no llamacpp overlay)"
  else
    record FAIL "A4 litellm models"
  fi

  # A5 aichat: run-style container; must use a llamacpp router model id.
  save_and_set_config aichat.model "$MODEL"
  local out rc attempt
  for attempt in 1 2; do
    out=$(timeout 600 "$HARBOR" run aichat --no-stream 'Reply with exactly: PONG' </dev/null 2>&1)
    rc=$?
    [ "$rc" -eq 0 ] && [ -n "$out" ] && break
    # Timed-out runs leave llamacpp slots decoding the orphaned request;
    # removing the client container alone does not stop them.
    log "aichat attempt $attempt failed (rc=$rc), cleaning up + restarting llamacpp"
    cleanup_run_containers
    docker restart harbor.llamacpp >/dev/null 2>&1
    wait_llamacpp_ready "A5 llamacpp re-ready (retry $attempt)"
  done
  if [ "$rc" -eq 0 ] && [ -n "$out" ]; then
    record PASS "A5 aichat one-shot"
  else
    record FAIL "A5 aichat one-shot" "rc=$rc"
  fi

  teardown
}

group_B() {
  log "Group B: searxng langflow"
  "$HARBOR" up searxng langflow >/dev/null 2>&1

  probe_200 "B1 searxng ready" "$(svc_url searxng)/" 120
  if curl -s -m 30 "$(svc_url searxng)/search?q=harbor&format=json" \
    | jq -er '.results | type == "array"' >/dev/null 2>&1; then
    record PASS "B1 searxng JSON search"
  else
    record FAIL "B1 searxng JSON search"
  fi

  probe_200 "B2 langflow ready" "$(svc_url langflow)/health" 300
  local lf_version
  lf_version=$(curl -s -m 10 "$(svc_url langflow)/api/v1/version" | jq -er '.version' 2>/dev/null)
  if [ -n "$lf_version" ]; then
    record PASS "B2 langflow version" "$lf_version"
  else
    record FAIL "B2 langflow version"
  fi

  teardown
}

group_C() {
  log "Group C: hermes opencode (host CLIs via harbor launch + llamacpp)"
  if ! command -v hermes >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/hermes" ]; then
    record SKIP "C1 hermes" "hermes not installed on host"
  fi
  "$HARBOR" up llamacpp >/dev/null 2>&1
  wait_llamacpp_ready "C0 llamacpp ready" || { teardown; return; }
  resolve_model || { record FAIL "C0 model discovery"; teardown; return; }

  local out rc
  if command -v hermes >/dev/null 2>&1 || [ -x "$HOME/.local/bin/hermes" ]; then
    out=$(timeout 300 "$HARBOR" launch --backend llamacpp --model "$MODEL" \
      hermes -z "Reply with exactly: PONG and nothing else" </dev/null 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ] && [ -n "$out" ]; then
      record PASS "C1 hermes one-shot"
    else
      record FAIL "C1 hermes one-shot" "rc=$rc"
    fi
  fi

  # opencode needs a template-tolerant model (Qwen3.5 400s on non-first
  # system message); `opencode run` exits 0 even on API errors — assert output.
  if command -v opencode >/dev/null 2>&1 || [ -x "$HOME/.opencode/bin/opencode" ]; then
    out=$(timeout 600 "$HARBOR" launch --backend llamacpp --model "$OPENCODE_MODEL" \
      opencode run "Reply with exactly: PONG and nothing else" </dev/null 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ] && echo "$out" | grep -qi 'PONG'; then
      record PASS "C2 opencode run"
    else
      record FAIL "C2 opencode run" "rc=$rc, PONG not in output"
    fi
  else
    record SKIP "C2 opencode" "opencode not installed on host"
  fi

  teardown
}

wait_ollama_ready() {
  local id="$1" waited=0
  while [ "$waited" -le 120 ]; do
    if curl -s -m 10 "$(svc_url ollama)/api/version" | jq -er '.version' >/dev/null 2>&1; then
      record PASS "$id" "after ${waited}s"
      return 0
    fi
    sleep 5; waited=$((waited + 5))
  done
  record FAIL "$id" "no version within 120s"
  return 1
}

group_D() {
  log "Group D: ollama gptme"
  "$HARBOR" up ollama >/dev/null 2>&1
  wait_ollama_ready "D1 ollama ready" || { teardown; return; }

  if "$HARBOR" exec ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1 \
    && curl -s -m 300 "$(svc_url ollama)/api/generate" \
      -d "{\"model\":\"$OLLAMA_TINY_MODEL\",\"prompt\":\"Reply with exactly: PONG\",\"stream\":false}" \
      | jq -er '.response | length > 0' >/dev/null 2>&1; then
    record PASS "D1 ollama pull + generate"
  else
    record FAIL "D1 ollama pull + generate"
  fi

  # gptme: run-style; only the `harbor gptme` subcommand injects -m local/<model>.
  save_and_set_config gptme.model "$OLLAMA_TINY_MODEL"
  local out rc
  out=$(timeout 300 "$HARBOR" gptme -n --no-stream 'Reply with exactly: PONG' </dev/null 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && [ -n "$out" ]; then
    record PASS "D2 gptme one-shot"
  else
    record FAIL "D2 gptme one-shot" "rc=$rc"
  fi

  teardown
}

group_E() {
  log "Group E: comfyui (GPU-optional; CPU fallback applied)"
  # Default image is CUDA-only; on non-NVIDIA hosts force --cpu. Env is read
  # at create time, so recreate rather than restart.
  save_and_set_config comfyui.args "--cpu"
  docker rm -f harbor.comfyui >/dev/null 2>&1
  "$HARBOR" up comfyui >/dev/null 2>&1

  probe_200 "E1 comfyui ready" "$(svc_url comfyui)/" 300
  if curl -s -m 30 "$(svc_url comfyui)/system_stats" | jq -er '.system' >/dev/null 2>&1; then
    record PASS "E1 comfyui system_stats"
  else
    record FAIL "E1 comfyui system_stats"
  fi

  teardown
}

group_F() {
  log "Group F: jupyter chatui librechat promptfoo (+ollama for overlays)"
  "$HARBOR" up ollama jupyter chatui librechat promptfoo >/dev/null 2>&1

  probe_200 "F1 jupyter ready" "$(svc_url jupyter)/api" 600
  if curl -s -m 10 "$(svc_url jupyter)/api" | jq -er '.version' >/dev/null 2>&1; then
    record PASS "F1 jupyter version"
  else
    record FAIL "F1 jupyter version"
  fi

  probe_200 "F2 chatui ready" "$(svc_url chatui)/" 300
  if curl -s -m 10 "$(svc_url chatui)/" | grep -qi '<html'; then
    record PASS "F2 chatui front page"
  else
    record FAIL "F2 chatui front page"
  fi

  probe_200 "F3 librechat ready" "$(svc_url librechat)/" 300
  if curl -s -m 10 "$(svc_url librechat)/api/config" | jq -er '.appTitle' >/dev/null 2>&1; then
    record PASS "F3 librechat config API"
  else
    record FAIL "F3 librechat config API"
  fi

  probe_200 "F4 promptfoo ready" "$(svc_url promptfoo)/" 120
  if curl -s -m 10 "$(svc_url promptfoo)/health" | jq -er '.status' >/dev/null 2>&1; then
    record PASS "F4 promptfoo health"
  else
    record FAIL "F4 promptfoo health"
  fi

  teardown
}

group_G() {
  log "Group G: fabric cmdh (run-style CLIs via ollama)"
  "$HARBOR" up ollama >/dev/null 2>&1
  wait_ollama_ready "G0 ollama ready" || { teardown; return; }
  "$HARBOR" exec ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  save_and_set_config fabric.model "$OLLAMA_TINY_MODEL"
  local out rc
  out=$(echo 'Reply with exactly: PONG' | timeout 300 "$HARBOR" fabric 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && [ -n "$out" ]; then
    record PASS "G1 fabric one-shot"
  else
    record FAIL "G1 fabric one-shot" "rc=$rc"
  fi

  save_and_set_config cmdh.model "$OLLAMA_TINY_MODEL"
  out=$(timeout 300 "$HARBOR" cmdh 'print the current directory' </dev/null 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ] && echo "$out" | grep -qi 'command'; then
    record PASS "G2 cmdh one-shot"
  else
    record FAIL "G2 cmdh one-shot" "rc=$rc"
  fi

  teardown
}

group_H() {
  log "Group H-a: kobold speaches"
  "$HARBOR" up kobold speaches >/dev/null 2>&1

  # kobold downloads its default model on first start (~670 MB): allow 10 min.
  local waited=0 model_name=""
  while [ "$waited" -le 600 ]; do
    model_name=$(curl -s -m 10 "$(svc_url kobold)/api/v1/model" | jq -er '.result' 2>/dev/null)
    [ -n "$model_name" ] && break
    sleep 10; waited=$((waited + 10))
  done
  if [ -n "$model_name" ]; then
    record PASS "H1 kobold model loaded" "$model_name"
  else
    record FAIL "H1 kobold model loaded" "no model within 600s"
  fi
  if curl -s -m 300 "$(svc_url kobold)/api/v1/generate" \
    -d '{"prompt":"Reply with exactly: PONG\n","max_length":16}' \
    | jq -er '.results[0].text | length > 0' >/dev/null 2>&1; then
    record PASS "H1 kobold generate"
  else
    record FAIL "H1 kobold generate"
  fi

  # speaches-init registers/downloads STT+TTS models; wait for it to exit 0.
  waited=0
  local init_state=""
  while [ "$waited" -le 600 ]; do
    init_state=$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' harbor.speaches-init 2>/dev/null)
    [ "$init_state" = "exited 0" ] && break
    sleep 10; waited=$((waited + 10))
  done
  probe_200 "H2 speaches health" "$(svc_url speaches)/health" 120
  if curl -s -m 10 "$(svc_url speaches)/v1/models" | grep -qi 'whisper'; then
    record PASS "H2 speaches STT model registered"
  else
    record FAIL "H2 speaches STT model registered"
  fi
  local wav=/tmp/services-it-tts.wav tts_model stt_model
  tts_model=$(curl -s -m 10 "$(svc_url speaches)/v1/models" | jq -r '.data[].id' | grep -i kokoro | head -1)
  stt_model=$(curl -s -m 10 "$(svc_url speaches)/v1/models" | jq -r '.data[].id' | grep -i whisper | head -1)
  if [ -n "$tts_model" ] && [ -n "$stt_model" ] \
    && curl -s -m 120 "$(svc_url speaches)/v1/audio/speech" \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"$tts_model\",\"voice\":\"af_bella\",\"input\":\"hello world\",\"response_format\":\"wav\"}" \
      -o "$wav" && [ -s "$wav" ] \
    && curl -s -m 120 "$(svc_url speaches)/v1/audio/transcriptions" \
      -F "file=@$wav" -F "model=$stt_model" | jq -er '.text' | grep -qi hello; then
    record PASS "H2 speaches TTS-STT round trip"
  else
    record FAIL "H2 speaches TTS-STT round trip"
  fi
  rm -f "$wav"

  teardown

  log "Group H-b: txtairag plandex webtop"
  # plandex CLI container is run-style and exits at its auth prompt — a
  # nonzero `up` on that container alone is expected; assert on probes.
  "$HARBOR" up txtairag plandex webtop >/dev/null 2>&1

  probe_200 "H3 txtairag ready" "$(svc_url txtairag)/" 300
  # The run-style `plandex` CLI container exits, so `harbor url plandex`
  # fails; probe the long-running server container instead. First boot does
  # fresh postgres init + LiteLLM proxy bootstrap + migrations before the
  # listener opens — allow the same 300s budget as the other web probes.
  probe_200 "H4 plandex server health" "$(svc_url plandex-server)/health" 300
  probe_200 "H5 webtop ready" "$(svc_url webtop)/" 300

  teardown
}

BOOST_IT_MODULES="klmbr rcn g1 mcts eli5 concept ponder"

group_I() {
  log "Group I-a: depth checks — webui chat, searxng categories, litellm proxy, boost modules"
  # Boost only serves configured modules; select the ones under test.
  save_and_set_config boost.modules "klmbr;rcn;g1;mcts;eli5;concept;ponder"
  "$HARBOR" up llamacpp webui boost litellm searxng >/dev/null 2>&1

  wait_llamacpp_ready "I0 llamacpp ready" || { teardown; return; }
  resolve_model || { record FAIL "I0 model discovery"; teardown; return; }

  # I1 webui chat round trip via its OpenAI-compat API. The instance may have
  # existing users, so a fresh signup lands as "pending" — promote it to admin
  # directly in webui.db (test user is removed afterwards).
  local waited=0 health=""
  while [ "$waited" -le 300 ]; do
    health=$(docker inspect -f '{{.State.Health.Status}}' harbor.webui 2>/dev/null)
    [ "$health" = "healthy" ] && break
    sleep 5; waited=$((waited + 5))
  done
  local wu it_email it_token
  wu=$(svc_url webui)
  it_email="services-it-$$@harbor.test"
  it_token=$(curl -s -m 30 "$wu/api/v1/auths/signup" -H 'Content-Type: application/json' \
    -d "{\"name\":\"services-it\",\"email\":\"$it_email\",\"password\":\"services-it-pass\"}" \
    | jq -r '.token // empty')
  docker exec harbor.webui python -c "import sqlite3; c = sqlite3.connect('/app/backend/data/webui.db'); c.execute(\"update user set role='admin' where email='$it_email'\"); c.commit()" >/dev/null 2>&1
  local webui_reply
  webui_reply=$(curl -s -m 600 "$wu/api/chat/completions" \
    -H "Authorization: Bearer $it_token" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -r '.choices[0].message.content // empty')
  if [ -n "$it_token" ] && [ -n "$webui_reply" ]; then
    record PASS "I1 webui chat round trip"
  else
    record FAIL "I1 webui chat round trip" "token: ${it_token:+set}${it_token:-missing}, reply empty"
  fi
  docker exec harbor.webui python -c "import sqlite3; c = sqlite3.connect('/app/backend/data/webui.db'); c.execute(\"delete from user where email='$it_email'\"); c.execute(\"delete from auth where email='$it_email'\"); c.commit()" >/dev/null 2>&1

  # I2 searxng category queries (beyond the single general JSON query of B1).
  local sx cat
  sx=$(svc_url searxng)
  for cat in images it; do
    if curl -s -m 60 "$sx/search?q=github&categories=$cat&format=json" \
      | jq -er '.results | type == "array"' >/dev/null 2>&1; then
      record PASS "I2 searxng category: $cat"
    else
      record FAIL "I2 searxng category: $cat"
    fi
  done

  # I3 litellm actually proxying to llamacpp via the llamacpp wildcard fragment.
  probe_200 "I3 litellm ready" "$(svc_url litellm)/health/liveliness" 120
  local litellm_key lu
  litellm_key=$("$HARBOR" config get litellm.master.key 2>/dev/null)
  lu=$(svc_url litellm)
  if curl -s -m 10 -H "Authorization: Bearer ${litellm_key:-sk-litellm}" "$lu/v1/models" \
    | jq -er '.data | length > 0' >/dev/null 2>&1; then
    record PASS "I3 litellm models non-empty"
  else
    record FAIL "I3 litellm models non-empty"
  fi
  if curl -s -m 600 -H "Authorization: Bearer ${litellm_key:-sk-litellm}" \
    -H 'Content-Type: application/json' "$lu/v1/chat/completions" \
    -d "{\"model\":\"llamacpp/$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -er '.choices[0].message.content | length > 0' >/dev/null 2>&1; then
    record PASS "I3 litellm proxied completion" "llamacpp/$MODEL"
  else
    record FAIL "I3 litellm proxied completion" "llamacpp/$MODEL"
  fi

  # I4 boost modules — one boosted completion per module under test.
  probe_200 "I4 boost ready" "$(svc_url boost)/health" 120
  local boost_url models mod mid
  boost_url=$(svc_url boost)
  models=$(curl -s -m 10 -H 'Authorization: Bearer sk-boost' "$boost_url/v1/models" | jq -r '.data[].id')
  local base attempt ok
  for mod in $BOOST_IT_MODULES; do
    # Multi-turn self-reflection modules (rcn, g1) capture the *content* of
    # intermediate completions; thinking models (Qwen3.5) emit only
    # reasoning_content there, breaking the chain — use the non-thinking,
    # template-tolerant model for those.
    case "$mod" in
      rcn|g1) base="$OPENCODE_MODEL" ;;
      *) base="$MODEL" ;;
    esac
    mid=$(echo "$models" | grep -i "^${mod}-" | grep -iF "$base" | head -1)
    if [ -z "$mid" ]; then
      record FAIL "I4 boost module $mod" "no ${mod}-* model served"
      continue
    fi
    ok=""
    for attempt in 1 2; do
      if curl -s -m 900 "$boost_url/v1/chat/completions" \
        -H 'Authorization: Bearer sk-boost' -H 'Content-Type: application/json' \
        -d "{\"model\":\"$mid\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 6 times 7? Reply briefly.\"}],\"max_tokens\":$MAX_TOKENS}" \
        | jq -er '.choices[0].message.content | length > 0' >/dev/null 2>&1; then
        ok=1
        break
      fi
      log "I4 $mod attempt $attempt failed, retrying"
    done
    if [ -n "$ok" ]; then
      record PASS "I4 boost module $mod" "$mid"
    else
      record FAIL "I4 boost module $mod" "$mid"
    fi
  done

  teardown

  log "Group I-b: jupyter kernel exec, promptfoo eval (via ollama)"
  "$HARBOR" up ollama jupyter promptfoo >/dev/null 2>&1
  wait_ollama_ready "I5 ollama ready" || { teardown; return; }
  "$HARBOR" exec ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  probe_200 "I5 jupyter ready" "$(svc_url jupyter)/api" 600
  local kernel_out
  kernel_out=$(docker exec harbor.jupyter python -c '
from jupyter_client.manager import start_new_kernel
km, kc = start_new_kernel(kernel_name="python3")
kc.execute("print(6*7)")
while True:
    msg = kc.get_iopub_msg(timeout=120)
    if msg["msg_type"] == "stream":
        print(msg["content"]["text"].strip())
        break
km.shutdown_kernel()
' 2>/dev/null)
  if [ "$kernel_out" = "42" ]; then
    record PASS "I5 jupyter kernel execute" "print(6*7) -> 42"
  else
    record FAIL "I5 jupyter kernel execute" "got: ${kernel_out:-nothing}"
  fi

  probe_200 "I6 promptfoo ready" "$(svc_url promptfoo)/health" 120
  local pf_rc
  docker exec -e OLLAMA_BASE_URL=http://ollama:11434 harbor.promptfoo sh -c '
    cd /tmp || exit 1
    printf "prompts:\n  - \"Reply with exactly: PONG\"\nproviders:\n  - id: ollama:chat:%s\ntests:\n  - assert:\n      - type: javascript\n        value: output.length > 0\n" "'"$OLLAMA_TINY_MODEL"'" > pf.yaml
    if command -v promptfoo >/dev/null 2>&1; then
      promptfoo eval -c pf.yaml --no-progress-bar
    else
      node /app/dist/src/main.js eval -c pf.yaml --no-progress-bar
    fi
  ' >/dev/null 2>&1
  pf_rc=$?
  if [ "$pf_rc" -eq 0 ]; then
    record PASS "I6 promptfoo eval run"
  else
    record FAIL "I6 promptfoo eval run" "rc=$pf_rc"
  fi

  teardown

  log "Group I-c: comfyui workflow submission (CPU mode)"
  save_and_set_config comfyui.args "--cpu"
  docker rm -f harbor.comfyui >/dev/null 2>&1
  "$HARBOR" up comfyui >/dev/null 2>&1

  probe_200 "I7 comfyui ready" "$(svc_url comfyui)/" 300
  # Model-free graph: EmptyImage -> SaveImage exercises the full queue,
  # execution, and history pipeline without needing checkpoints.
  local cu prompt_id
  cu=$(svc_url comfyui)
  prompt_id=$(curl -s -m 30 "$cu/prompt" -H 'Content-Type: application/json' \
    -d '{"prompt":{"1":{"class_type":"EmptyImage","inputs":{"width":64,"height":64,"batch_size":1,"color":0}},"2":{"class_type":"SaveImage","inputs":{"images":["1",0],"filename_prefix":"services-it"}}}}' \
    | jq -r '.prompt_id // empty')
  local outputs=""
  waited=0
  if [ -n "$prompt_id" ]; then
    while [ "$waited" -le 120 ]; do
      outputs=$(curl -s -m 10 "$cu/history/$prompt_id" \
        | jq -er ".\"$prompt_id\".outputs | length > 0" 2>/dev/null)
      [ "$outputs" = "true" ] && break
      sleep 5; waited=$((waited + 5))
    done
  fi
  if [ "$outputs" = "true" ]; then
    record PASS "I7 comfyui workflow executed" "prompt_id $prompt_id"
  else
    record FAIL "I7 comfyui workflow executed" "prompt_id: ${prompt_id:-none}"
  fi

  teardown
}

list_groups() {
  cat <<'EOF'
A  llamacpp webui boost litellm aichat   (llamacpp backend + OpenAI satellites)
B  searxng langflow                      (standalone web services, no LLM)
C  hermes opencode                       (host CLIs via harbor launch + llamacpp)
D  ollama gptme                          (ollama backend + container CLI)
E  comfyui                               (GPU-optional; excluded by default, CPU fallback)
F  jupyter chatui librechat promptfoo    (web services batch 2)
G  fabric cmdh                           (run-style CLIs via ollama)
H  kobold speaches txtairag plandex webtop (batch 3, two sub-batches)
I  webui searxng litellm boost jupyter promptfoo comfyui (depth: chat/eval/kernel/workflow)
EOF
}

main() {
  local groups="$DEFAULT_GROUPS"
  while [ $# -gt 0 ]; do
    case "$1" in
      --list) list_groups; exit 0 ;;
      --groups)
        groups=$(echo "$2" | tr ',a-z' ' A-Z')
        shift
        ;;
      -h|--help)
        sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
      *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
  done

  local g
  for g in $groups; do
    case "$g" in
      A|B|C|D|E|F|G|H|I) ;;
      *) echo "Unknown group: $g (valid: A-I)" >&2; exit 2 ;;
    esac
  done

  log "groups: $groups"
  log "starting from a clean stack"
  "$HARBOR" down >/dev/null 2>&1
  cleanup_run_containers

  for g in $groups; do
    "group_$g"
  done

  echo
  echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed, $SKIP_COUNT skipped"
  if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "Failed checks:$FAILED_CHECKS"
    exit 1
  fi
}

main "$@"
