#!/usr/bin/env bash
# Harbor services integration runner — automates tests/services-integration.md.
#
# Usage:
#   ./tests/services-integration.sh                 # run all CPU-safe groups (A B C D F G H I K L M)
#   ./tests/services-integration.sh --groups B,G    # run selected groups
#   ./tests/services-integration.sh --list          # list groups and their checks
#
# Groups run SERIALLY (services share ports/GPU); every group ends with
# `harbor down` teardown, even on failure. Group E (comfyui) is excluded by
# default: the shipped image is CUDA-only — on a non-NVIDIA host the runner
# applies the `--cpu` workaround, but it is opt-in via `--groups E`. Group J
# (ROCm paths) is likewise opt-in via `--groups J` and self-skips on hosts
# without an AMD GPU (/dev/kfd + renderD* + amdgpu module).
#
# Never uses `harbor logs` (tails forever) — uses `docker logs` when needed.
# Prints one PASS/FAIL line per check plus a final summary; exits non-zero if
# any check failed. See tests/services-integration.md for the full spec and
# rationale behind each check (thinking-model token budgets, run-style vs
# up-style services, orphaned-slot cleanup, config overrides).
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
HARBOR=./harbor.sh

DEFAULT_GROUPS="A B C D F G H I K L M"
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

  log "Group I-d: chatui/librechat chat round trips, langflow flow execution"
  "$HARBOR" up llamacpp ollama chatui librechat langflow >/dev/null 2>&1
  wait_llamacpp_ready "I8 llamacpp ready" || { teardown; return; }
  resolve_model || { record FAIL "I8 model discovery"; teardown; return; }
  wait_ollama_ready "I9 ollama ready" || { teardown; return; }
  "$HARBOR" exec ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  # I8 chatui chat round trip. chat-ui >= 0.10 serves the models of the single
  # OPENAI_BASE_URL provider (bridged from Harbor's config by envify.js), i.e.
  # the llamacpp router. chatui sends no max_tokens, so a thinking model
  # (Qwen3.5) can ramble to context exhaustion — use the non-thinking
  # template-tolerant model instead. The anonymous-session cookie (hf-chat)
  # is minted on the first response; message POSTs are multipart and require
  # a matching Origin header.
  probe_200 "I8 chatui ready" "$(svc_url chatui)/" 300
  local cu cujar conv cu_cid cu_root cu_reply
  cu=$(svc_url chatui)
  cujar=$(mktemp -t harbor.cujar.XXXXXX)
  conv=$(curl -s -c "$cujar" -m 30 -X POST "$cu/conversation" \
    -H 'Content-Type: application/json' -d "{\"model\":\"$OPENCODE_MODEL\"}")
  cu_cid=$(echo "$conv" | jq -r '.conversationId // empty')
  cu_root=$(echo "$conv" | jq -r '.conversation | fromjson | .json.rootMessageId // empty' 2>/dev/null)
  cu_reply=""
  if [ -n "$cu_cid" ] && [ -n "$cu_root" ]; then
    curl -s -b "$cujar" -m 600 -H "Origin: $cu" -X POST "$cu/conversation/$cu_cid" \
      -F "data={\"inputs\":\"Reply with exactly: PONG\",\"id\":\"$cu_root\",\"is_retry\":false,\"is_continue\":false,\"web_search\":false,\"tools\":[]}" \
      >/dev/null 2>&1
    cu_reply=$(curl -s -b "$cujar" -m 30 "$cu/api/v2/conversations/$cu_cid" \
      | jq -r '[.json.messages[] | select(.from=="assistant") | .content] | join("")' 2>/dev/null)
  fi
  rm -f "$cujar"
  if [ -n "$cu_reply" ]; then
    record PASS "I8 chatui chat round trip" "$OPENCODE_MODEL"
  else
    record FAIL "I8 chatui chat round trip" "cid: ${cu_cid:-none}, assistant reply empty"
  fi

  # I9 librechat chat round trip. Registration is disabled by default, so the
  # test user is seeded via the bundled create-user script and removed from
  # mongo afterwards. Chat requires: a browser-like User-Agent (uaParser
  # middleware rejects others), a /api/models fetch to warm the endpoint model
  # cache, and endpoint "ollama" (lowercase — the custom endpoint named
  # "Ollama" is normalized) with endpointType "custom". The chat POST returns
  # a stream id immediately; the reply is polled from /api/messages.
  probe_200 "I9 librechat ready" "$(svc_url librechat)/" 300
  local lc lc_ua lc_email lc_tok lc_cid lc_out
  lc=$(svc_url librechat)
  lc_ua='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
  lc_email="services-it@harbor.test"
  docker exec harbor.librechat node /app/config/create-user.js \
    "$lc_email" services-it servicesit Services-IT-1234 --email-verified=true >/dev/null 2>&1
  lc_tok=$(curl -s -m 30 -X POST "$lc/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$lc_email\",\"password\":\"Services-IT-1234\"}" | jq -r '.token // empty')
  lc_out=""
  if [ -n "$lc_tok" ]; then
    curl -s -m 60 -A "$lc_ua" -H "Authorization: Bearer $lc_tok" "$lc/api/models" >/dev/null 2>&1
    lc_cid=$(curl -s -N -m 600 -A "$lc_ua" -X POST "$lc/api/agents/chat/ollama" \
      -H "Authorization: Bearer $lc_tok" -H 'Content-Type: application/json' \
      -d "{\"text\":\"Reply with exactly: PONG\",\"endpoint\":\"ollama\",\"endpointType\":\"custom\",\"model\":\"$OLLAMA_TINY_MODEL\",\"conversationId\":null,\"parentMessageId\":\"00000000-0000-0000-0000-000000000000\",\"isCreatedByUser\":true,\"error\":false,\"generation\":\"\"}" \
      | jq -r '.conversationId // empty' 2>/dev/null)
    waited=0
    while [ -n "$lc_cid" ] && [ "$waited" -le 300 ]; do
      lc_out=$(curl -s -m 30 -A "$lc_ua" -H "Authorization: Bearer $lc_tok" "$lc/api/messages/$lc_cid" \
        | jq -r '[.[] | select(.isCreatedByUser==false) | (.text // "") + ([.content[]? | select(.type=="text") | .text] | join(""))] | join("")' 2>/dev/null)
      [ -n "$lc_out" ] && break
      sleep 5; waited=$((waited + 5))
    done
  fi
  if [ -n "$lc_out" ]; then
    record PASS "I9 librechat chat round trip" "ollama/$OLLAMA_TINY_MODEL"
  else
    record FAIL "I9 librechat chat round trip" "token: ${lc_tok:+set}${lc_tok:-missing}, cid: ${lc_cid:-none}, reply empty"
  fi
  docker exec harbor.librechat-db mongosh LibreChat --quiet \
    --eval "db.users.deleteOne({email:'$lc_email'})" >/dev/null 2>&1

  # I10 langflow flow execution: import a minimal ChatInput -> ChatOutput
  # passthrough flow (built from the live component catalog), run it via the
  # run API (x-api-key minted via /api/v1/api_key), assert the output echoes
  # the input, delete the flow. Auth token comes from auto_login
  # (LANGFLOW_AUTO_LOGIN=true in Harbor's defaults).
  probe_200 "I10 langflow ready" "$(svc_url langflow)/health" 300
  local lf lf_tok lf_out
  lf=$(svc_url langflow)
  lf_tok=$(curl -s -m 30 "$lf/api/v1/auto_login" | jq -r '.access_token // empty')
  lf_out=$(python3 tests/lib/langflow-flow.py "$lf" "$lf_tok" 2>/dev/null)
  if [ "$lf_out" = "PONG-services-it" ]; then
    record PASS "I10 langflow flow execution" "passthrough echo"
  else
    record FAIL "I10 langflow flow execution" "got: ${lf_out:-nothing}"
  fi

  teardown
}

has_rocm_host() {
  # Same predicate as harbor.sh has_rocm(): kfd + render nodes + amdgpu module.
  [ -e /dev/kfd ] || return 1
  ls /dev/dri/renderD* >/dev/null 2>&1 || return 1
  lsmod 2>/dev/null | grep -q '^amdgpu ' || return 1
}

# Assert the container got /dev/kfd via the rocm capability overlay.
# rocm_devices <check-id> <container>
rocm_devices() {
  local id="$1" ctr="$2" devs
  devs=$(docker inspect "$ctr" --format '{{range .HostConfig.Devices}}{{.PathOnHost}} {{end}}' 2>/dev/null)
  if echo "$devs" | grep -q '/dev/kfd'; then
    record PASS "$id" "devices: $devs"
  else
    record FAIL "$id" "no /dev/kfd in devices: ${devs:-none}"
  fi
}

group_J() {
  log "Group J: ROCm paths — llamacpp ollama lemonade localai voicebox (vllm gated)"
  if ! has_rocm_host; then
    local c
    for c in "J1 llamacpp.rocm" "J2 ollama.rocm" "J3 lemonade rocm" \
             "J4 localai.rocm" "J5 voicebox rocm devices" "J6 vllm.rocm"; do
      record SKIP "$c" "not a ROCm host (/dev/kfd, renderD*, amdgpu required)"
    done
    return
  fi

  # J1 llamacpp.rocm — capability overlay auto-applies HARBOR_LLAMACPP_IMAGE_ROCM.
  "$HARBOR" up llamacpp >/dev/null 2>&1
  rocm_devices "J1 llamacpp rocm devices" harbor.llamacpp
  wait_llamacpp_ready "J1 llamacpp ready"
  local out
  # This check proves GPU inference, not prompt adherence: heavily-quantized
  # thinking models (Q4_K_M) reliably burn the whole budget on
  # reasoning_content, so accept content OR reasoning_content.
  resolve_model
  out=$(curl -s -m 300 "$(svc_url llamacpp)/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -r '.choices[0].message | (.content // "") + (.reasoning_content // "")' 2>/dev/null)
  if [ -n "$out" ]; then
    record PASS "J1 llamacpp GPU inference" "${out:0:40}"
  else
    record FAIL "J1 llamacpp GPU inference" "no content/reasoning_content"
  fi
  # The ROCm0 device line is only emitted when a model loads — grep after
  # the inference above, not at startup.
  # Note: no `grep -q` on docker-logs pipelines — under pipefail, -q's
  # early exit SIGPIPEs docker logs (141) and fails the pipeline on a match.
  if docker logs harbor.llamacpp 2>&1 | grep 'ROCm0' >/dev/null; then
    record PASS "J1 llamacpp ROCm device init" \
      "$(docker logs harbor.llamacpp 2>&1 | grep -m1 -o 'ROCm0.*' | cut -c1-80)"
  else
    record FAIL "J1 llamacpp ROCm device init" "no ROCm0 line in logs after inference"
  fi
  "$HARBOR" down >/dev/null 2>&1

  # J2 ollama.rocm — image switches to ollama/ollama:rocm via overlay.
  "$HARBOR" up ollama >/dev/null 2>&1
  rocm_devices "J2 ollama rocm devices" harbor.ollama
  local oll
  oll=$(svc_url ollama)
  probe_200 "J2 ollama ready" "$oll/" 120
  if docker logs harbor.ollama 2>&1 | grep 'inference compute' | grep 'library=ROCm' >/dev/null; then
    record PASS "J2 ollama ROCm compute" \
      "$(docker logs harbor.ollama 2>&1 | grep -m1 -o 'library=ROCm compute=[^ ]*')"
  else
    record FAIL "J2 ollama ROCm compute" "no library=ROCm in inference compute line"
  fi
  docker exec harbor.ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1
  out=$(curl -s -m 300 "$oll/api/generate" \
    -d "{\"model\":\"$OLLAMA_TINY_MODEL\",\"prompt\":\"Say PONG\",\"stream\":false,\"think\":false}" \
    | jq -r '.response // empty')
  if [ -n "$out" ] && docker exec harbor.ollama ollama ps 2>/dev/null | grep -q 'GPU'; then
    record PASS "J2 ollama GPU generate" "${out:0:40}"
  else
    record FAIL "J2 ollama GPU generate" "response empty or model not on GPU"
  fi
  "$HARBOR" down >/dev/null 2>&1

  # J3 lemonade — overlay sets LEMONADE_LLAMACPP=rocm; rocm backend ships installed.
  "$HARBOR" up lemonade >/dev/null 2>&1
  local lem
  lem=$(svc_url lemonade)
  rocm_devices "J3 lemonade rocm devices" harbor.lemonade
  probe_200 "J3 lemonade live" "$lem/live" 300
  if docker inspect harbor.lemonade --format '{{range .Config.Env}}{{.}} {{end}}' \
      | grep -q 'LEMONADE_LLAMACPP=rocm'; then
    record PASS "J3 lemonade rocm env"
  else
    record FAIL "J3 lemonade rocm env" "LEMONADE_LLAMACPP=rocm not set (overlay not applied)"
  fi
  # Register the already-cached GGUF (HF cache is mounted) — no download.
  # Right after boot the model manager may not accept registrations yet:
  # retry the pull until the model shows up in /api/v1/models.
  local lem_waited=0
  while [ "$lem_waited" -lt 120 ]; do
    curl -s -m 120 -X POST "$lem/api/v1/pull" -H 'Content-Type: application/json' \
      -d '{"model_name":"user.services-it-tiny","checkpoint":"unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M","recipe":"llamacpp"}' \
      >/dev/null 2>&1
    curl -s -m 30 "$lem/api/v1/models" \
      | jq -e '.data[] | select(.id=="user.services-it-tiny")' >/dev/null 2>&1 && break
    sleep 10; lem_waited=$((lem_waited + 10))
  done
  # Thinking model: accept content or reasoning_content. One retry, first
  # call also loads the model.
  out=""
  for _ in 1 2; do
    out=$(curl -s -m 300 "$lem/api/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model":"user.services-it-tiny","messages":[{"role":"user","content":"Say PONG"}],"max_tokens":4000}' \
      | jq -r '.choices[0].message | (.content // "") + (.reasoning_content // "")' 2>/dev/null)
    [ -n "$out" ] && break
  done
  if [ -z "$out" ]; then
    record FAIL "J3 lemonade GPU inference" "no output (registration or chat failed)"
  elif ! docker logs harbor.lemonade 2>&1 | grep 'ROCm0' >/dev/null; then
    record FAIL "J3 lemonade GPU inference" "output ok but no ROCm0 in logs (CPU/vulkan path?)"
  else
    record PASS "J3 lemonade GPU inference" "ROCm0 buffers + output: ${out:0:30}"
  fi
  # Deliberately NO /api/v1/delete cleanup: lemonade's delete removes the
  # checkpoint files from the SHARED HF cache (it deleted Qwen3.5-0.8B
  # Q4_K_M that other groups' model discovery relies on). The registration
  # is idempotent and points at cached files — leaving it is harmless.
  "$HARBOR" down >/dev/null 2>&1

  # J4 localai.rocm — hipblas image; first run pulls ~4.3GB image + ~3.1GB
  # rocm backend + model, hence the generous timeouts.
  "$HARBOR" up localai >/dev/null 2>&1
  local la waited
  la=$(svc_url localai)
  rocm_devices "J4 localai rocm devices" harbor.localai
  probe_200 "J4 localai ready" "$la/readyz" 600
  if ! curl -s -m 30 "$la/v1/models" | jq -e '.data[] | select(.id=="qwen3-0.6b")' >/dev/null 2>&1; then
    curl -s -m 60 -X POST "$la/models/apply" -H 'Content-Type: application/json' \
      -d '{"id":"qwen3-0.6b"}' >/dev/null 2>&1
    waited=0
    while [ "$waited" -lt 600 ]; do
      curl -s -m 30 "$la/v1/models" | jq -e '.data[] | select(.id=="qwen3-0.6b")' >/dev/null 2>&1 && break
      sleep 10; waited=$((waited + 10))
    done
  fi
  out=$(curl -s -m 900 "$la/v1/chat/completions" -H 'Content-Type: application/json' \
    -d "{\"model\":\"qwen3-0.6b\",\"messages\":[{\"role\":\"user\",\"content\":\"Say PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -r '.choices[0].message.content // empty')
  if [ -n "$out" ]; then
    record PASS "J4 localai rocm inference" "${out:0:40}"
  else
    record FAIL "J4 localai rocm inference" "empty content (backend/model download may have failed)"
  fi
  "$HARBOR" down >/dev/null 2>&1

  # J5 voicebox — startup + device passthrough only: upstream image ships
  # CPU-only torch, so GPU cannot be used yet (documented limitation).
  "$HARBOR" up voicebox >/dev/null 2>&1
  rocm_devices "J5 voicebox rocm devices" harbor.voicebox
  probe_200 "J5 voicebox health" "$(svc_url voicebox)/health" 600
  "$HARBOR" down >/dev/null 2>&1

  # J6 vllm — default image is a CUDA build; only run when the user has
  # configured a ROCm vllm image (see spec for the verified procedure).
  local vllm_image
  vllm_image=$("$HARBOR" config get vllm.image 2>/dev/null)
  if [ "$vllm_image" = "vllm/vllm-openai" ]; then
    record SKIP "J6 vllm.rocm" "default CUDA image configured; see spec J6 for the ROCm procedure"
  else
    "$HARBOR" up vllm >/dev/null 2>&1
    rocm_devices "J6 vllm rocm devices" harbor.vllm
    local vurl vmodel
    vurl=$(svc_url vllm)
    probe_200 "J6 vllm health" "$vurl/health" 900
    vmodel=$("$HARBOR" config get vllm.model 2>/dev/null)
    out=$(curl -s -m 300 "$vurl/v1/chat/completions" -H 'Content-Type: application/json' \
      -d "{\"model\":\"$vmodel\",\"messages\":[{\"role\":\"user\",\"content\":\"Say PONG\"}],\"max_tokens\":1000}" \
      | jq -r '.choices[0].message.content // empty')
    if [ -n "$out" ]; then
      record PASS "J6 vllm rocm inference" "${out:0:40}"
    else
      record FAIL "J6 vllm rocm inference" "empty content"
    fi
    "$HARBOR" down >/dev/null 2>&1
  fi

  teardown
}

group_K() {
  log "Group K: landing hollama mikupad mock-openai qdrant libretranslate netdata dbhub (lightweight standalone CPU web services)"

  # LibreTranslate downloads every language pair by default (~10 GB); pin to
  # en<->es for the round trip. Restored (unset) in the teardown below.
  "$HARBOR" env libretranslate LT_LOAD_ONLY "en,es" >/dev/null

  "$HARBOR" up landing hollama mikupad mock-openai qdrant libretranslate netdata dbhub >/dev/null 2>&1

  # K1 landing — nginx serving the landing page + /docs mount
  if probe_200 "K1 landing ready" "$(svc_url landing)/" 120; then
    if curl -s -m 10 "$(svc_url landing)/" | grep -i 'harbor' >/dev/null; then
      record PASS "K1 landing index content"
    else
      record FAIL "K1 landing index content" "no 'harbor' in index.html"
    fi
    if curl -s -m 10 "$(svc_url landing)/docs/" | grep -i 'href' >/dev/null; then
      record PASS "K1 landing /docs listing"
    else
      record FAIL "K1 landing /docs listing"
    fi
  fi

  # K2 hollama — SPA index served
  if probe_200 "K2 hollama ready" "$(svc_url hollama)/" 120; then
    if curl -s -m 10 "$(svc_url hollama)/" | grep -i 'hollama' >/dev/null; then
      record PASS "K2 hollama index content"
    else
      record FAIL "K2 hollama index content"
    fi
  fi

  # K3 mikupad — single-file app served by http-server (image builds from git)
  if probe_200 "K3 mikupad ready" "$(svc_url mikupad)/" 300; then
    if curl -s -m 10 "$(svc_url mikupad)/" | grep -i 'mikupad' >/dev/null; then
      record PASS "K3 mikupad index content"
    else
      record FAIL "K3 mikupad index content"
    fi
  fi

  # K4 mock-openai — OpenAI-shaped fixture: models list + chat completion
  local mock_url
  mock_url=$(svc_url mock-openai)
  if probe_200 "K4 mock-openai ready" "$mock_url/v1/models" 120; then
    if curl -s -m 10 "$mock_url/v1/models" | jq -er '.data[0].id == "mock-model"' >/dev/null 2>&1; then
      record PASS "K4 mock-openai models"
    else
      record FAIL "K4 mock-openai models"
    fi
    local mock_reply
    mock_reply=$(curl -s -m 10 "$mock_url/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model":"mock-model","messages":[{"role":"user","content":"ping"}]}' \
      | jq -er '.choices[0].message.content' 2>/dev/null)
    if [ -n "$mock_reply" ]; then
      record PASS "K4 mock-openai chat completion" "$mock_reply"
    else
      record FAIL "K4 mock-openai chat completion"
    fi
  fi

  # K5 qdrant — collection CRUD + vector search (api-key auth)
  local qdrant_url qdrant_key
  qdrant_url=$(svc_url qdrant)
  qdrant_key=$("$HARBOR" config get qdrant.api_key 2>/dev/null)
  if probe_200 "K5 qdrant ready" "$qdrant_url/healthz" 120; then
    local coll="harbor_it_k5"
    curl -s -m 10 -X DELETE "$qdrant_url/collections/$coll" -H "api-key: $qdrant_key" >/dev/null 2>&1
    if curl -s -m 10 -X PUT "$qdrant_url/collections/$coll" -H "api-key: $qdrant_key" \
      -H 'Content-Type: application/json' \
      -d '{"vectors":{"size":4,"distance":"Dot"}}' | jq -er '.result == true' >/dev/null 2>&1; then
      record PASS "K5 qdrant create collection"
    else
      record FAIL "K5 qdrant create collection"
    fi
    curl -s -m 10 -X PUT "$qdrant_url/collections/$coll/points?wait=true" -H "api-key: $qdrant_key" \
      -H 'Content-Type: application/json' \
      -d '{"points":[{"id":1,"vector":[0.1,0.2,0.3,0.4]},{"id":2,"vector":[0.9,0.1,0.1,0.1]}]}' >/dev/null 2>&1
    local top_id
    top_id=$(curl -s -m 10 -X POST "$qdrant_url/collections/$coll/points/search" -H "api-key: $qdrant_key" \
      -H 'Content-Type: application/json' \
      -d '{"vector":[0.9,0.1,0.1,0.1],"limit":1}' | jq -er '.result[0].id' 2>/dev/null)
    if [ "$top_id" = "2" ]; then
      record PASS "K5 qdrant upsert + search" "top hit id=2"
    else
      record FAIL "K5 qdrant upsert + search" "expected id 2, got '${top_id:-none}'"
    fi
    curl -s -m 10 -X DELETE "$qdrant_url/collections/$coll" -H "api-key: $qdrant_key" >/dev/null 2>&1
  fi

  # K6 libretranslate — en->es translation round trip (models download on
  # first boot even with LT_LOAD_ONLY; allow a long ready window)
  local lt_url
  lt_url=$(svc_url libretranslate)
  if probe_200 "K6 libretranslate ready" "$lt_url/languages" 600; then
    local lt_text
    lt_text=$(curl -s -m 60 "$lt_url/translate" -H 'Content-Type: application/json' \
      -d '{"q":"hello world","source":"en","target":"es"}' \
      | jq -er '.translatedText' 2>/dev/null)
    if [ -n "$lt_text" ] && [ "$lt_text" != "hello world" ]; then
      record PASS "K6 libretranslate en->es" "$lt_text"
    else
      record FAIL "K6 libretranslate en->es" "got '${lt_text:-none}'"
    fi
  fi

  # K7 netdata — real metrics API
  local nd_url nd_version
  nd_url=$(svc_url netdata)
  if probe_200 "K7 netdata ready" "$nd_url/api/v1/info" 180; then
    nd_version=$(curl -s -m 10 "$nd_url/api/v1/info" | jq -er '.version' 2>/dev/null)
    if [ -n "$nd_version" ]; then
      record PASS "K7 netdata info" "$nd_version"
    else
      record FAIL "K7 netdata info"
    fi
  fi

  # K8 dbhub — MCP server (streamable HTTP, stateless) at /mcp over the
  # bundled demo SQLite: initialize returns serverInfo, and a tools/call
  # of execute_sql actually runs SQL.
  local dbhub_url dbhub_server
  dbhub_url=$(svc_url dbhub)
  local waited=0 rc=1
  while [ "$waited" -le 120 ]; do
    dbhub_server=$(curl -s -m 10 "$dbhub_url/mcp" -X POST \
      -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"harbor-it","version":"1.0"}}}' \
      | jq -er '.result.serverInfo.name' 2>/dev/null) && rc=0 && break
    sleep 5
    waited=$((waited + 5))
  done
  if [ "$rc" = "0" ] && [ -n "$dbhub_server" ]; then
    record PASS "K8 dbhub MCP initialize" "$dbhub_server after ${waited}s"
  else
    record FAIL "K8 dbhub MCP initialize" "no serverInfo within 120s"
  fi
  local dbhub_answer
  dbhub_answer=$(curl -s -m 10 "$dbhub_url/mcp" -X POST \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"execute_sql","arguments":{"sql":"SELECT 6*7 AS answer"}}}' \
    | jq -er '.result.content[0].text | fromjson | .data.rows[0].answer' 2>/dev/null)
  if [ "$dbhub_answer" = "42" ]; then
    record PASS "K8 dbhub execute_sql" "6*7=42"
  else
    record FAIL "K8 dbhub execute_sql" "expected 42, got '${dbhub_answer:-none}'"
  fi

  "$HARBOR" env libretranslate unset LT_LOAD_ONLY >/dev/null 2>&1
  teardown

  # --- K-b: drawio sillytavern lobechat traefik (need ollama + a routed target)
  log "Group K-b: drawio sillytavern lobechat traefik (+ollama +landing)"

  # Default drawio model (qwen3:30b) is not pulled; use the tiny one.
  save_and_set_config drawio.ai_model "$OLLAMA_TINY_MODEL"
  "$HARBOR" up ollama drawio sillytavern lobechat traefik landing >/dev/null 2>&1
  docker exec harbor.ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  # K9 drawio — GET / is a 307 to /en/; AI chat round trip via ollama
  local drawio_url waited code
  drawio_url=$(svc_url drawio)
  waited=0 code=""
  while [ "$waited" -le 180 ]; do
    code=$(curl -sL -o /dev/null -m 10 -w '%{http_code}' "$drawio_url/" 2>/dev/null)
    [ "$code" = "200" ] && break
    sleep 5
    waited=$((waited + 5))
  done
  if [ "$code" = "200" ]; then
    record PASS "K9 drawio ready" "200 after ${waited}s"
    local drawio_chat
    drawio_chat=$(curl -s -m 300 "$drawio_url/api/chat" -H 'Content-Type: application/json' \
      -d '{"messages":[{"id":"m1","role":"user","parts":[{"type":"text","text":"Reply with a short greeting"}]}],"xml":""}')
    if echo "$drawio_chat" | grep '"type":"finish"' >/dev/null \
      && echo "$drawio_chat" | grep '"text-delta"' >/dev/null; then
      record PASS "K9 drawio AI chat" "streamed text-delta + finish"
    else
      record FAIL "K9 drawio AI chat" "$(echo "$drawio_chat" | tail -c 200)"
    fi
  else
    record FAIL "K9 drawio ready" "no 200 within 180s (last: ${code:-none})"
  fi

  # K10 sillytavern — version API + index content + ollama wiring
  local st_url st_version
  st_url=$(svc_url sillytavern)
  if probe_200 "K10 sillytavern ready" "$st_url/version" 180; then
    st_version=$(curl -s -m 10 "$st_url/version" | jq -er '.pkgVersion' 2>/dev/null)
    if [ -n "$st_version" ] && curl -s -m 10 "$st_url/" | grep -i 'sillytavern' >/dev/null; then
      record PASS "K10 sillytavern version + content" "$st_version"
    else
      record FAIL "K10 sillytavern version + content"
    fi
    if docker exec harbor.sillytavern env 2>/dev/null | grep '^SILLYTAVERN_OLLAMA_URL=http://ollama:11434' >/dev/null; then
      record PASS "K10 sillytavern ollama wiring"
    else
      record FAIL "K10 sillytavern ollama wiring" "SILLYTAVERN_OLLAMA_URL not set"
    fi
  fi

  # K11 lobechat — GET / is a 307 to /chat; chat round trip needs the client
  # XOR token (base64(XOR(json, 'LobeHub · LobeHub'))), built with node.
  local lobe_url
  lobe_url=$(svc_url lobechat)
  waited=0 code=""
  while [ "$waited" -le 300 ]; do
    code=$(curl -sL -o /dev/null -m 10 -w '%{http_code}' "$lobe_url/" 2>/dev/null)
    [ "$code" = "200" ] && break
    sleep 5
    waited=$((waited + 5))
  done
  if [ "$code" = "200" ]; then
    record PASS "K11 lobechat ready" "200 after ${waited}s"
    if command -v node >/dev/null 2>&1; then
      local lobe_tok lobe_out
      lobe_tok=$(node -e '
        const key = Buffer.from("LobeHub · LobeHub", "utf8");
        const p = Buffer.from(JSON.stringify({ accessCode: "", apiKey: "", baseURL: "", userId: "harbor-it" }), "utf8");
        const out = Buffer.alloc(p.length);
        for (let i = 0; i < p.length; i++) out[i] = p[i] ^ key[i % key.length];
        console.log(out.toString("base64"));')
      lobe_out=$(curl -s -m 300 "$lobe_url/webapi/chat/ollama" \
        -H "X-lobe-chat-auth: $lobe_tok" -H 'Content-Type: application/json' \
        -d '{"model":"'"$OLLAMA_TINY_MODEL"'","messages":[{"role":"user","content":"Reply with exactly: PONG"}],"stream":false}')
      if echo "$lobe_out" | grep -E 'event: (text|reasoning)' >/dev/null; then
        record PASS "K11 lobechat chat round trip" "streamed model output via ollama"
      else
        record FAIL "K11 lobechat chat round trip" "$(echo "$lobe_out" | tail -c 200)"
      fi
    else
      record SKIP "K11 lobechat chat round trip" "node not available for the auth token"
    fi
  else
    record FAIL "K11 lobechat ready" "no 200 within 300s (last: ${code:-none})"
  fi

  # K12 traefik — routed target check against landing via the docker provider.
  # Traefik binds host 80/443; if the container is not up (ports taken), SKIP.
  local traefik_dash="http://localhost:34373"
  if ! docker ps --format '{{.Names}}' | grep -x 'harbor.traefik' >/dev/null; then
    record SKIP "K12 traefik" "container not running (host ports 80/443 likely taken)"
  elif probe_200 "K12 traefik dashboard ready" "$traefik_dash/api/http/routers" 120; then
    if curl -s -m 10 "$traefik_dash/api/http/routers" | jq -er '[.[].name] | index("landing@docker") != null' >/dev/null 2>&1; then
      record PASS "K12 traefik landing router registered"
    else
      record FAIL "K12 traefik landing router registered"
    fi
    if curl -sk -m 10 'https://localhost:443/' -H 'Host: landing.lan' | grep -i 'harbor' >/dev/null; then
      record PASS "K12 traefik https routing to landing"
    else
      record FAIL "K12 traefik https routing to landing"
    fi
    local redir
    redir=$(curl -s -o /dev/null -m 10 -w '%{http_code}' 'http://localhost:80/' -H 'Host: landing.lan')
    if [ "$redir" = "301" ] || [ "$redir" = "308" ]; then
      record PASS "K12 traefik http->https redirect" "$redir"
    else
      record FAIL "K12 traefik http->https redirect" "got $redir"
    fi
  fi

  teardown
}

group_L() {
  log "Group L: anythingllm sqlchat (chat round trips)"

  "$HARBOR" up ollama anythingllm sqlchat >/dev/null 2>&1
  docker exec harbor.ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1
  resolve_model

  # L1 anythingllm — workspace chat round trip. Both the .llamacpp and
  # .ollama overlays apply (both backends up); which LLM_PROVIDER wins the
  # env merge is invocation-dependent, so pick the chat model to match the
  # active provider. Default chatMode 'automatic' routes into the agent
  # websocket flow, so it is forced to 'chat'.
  local allm_url allm_slug allm_final allm_provider allm_model
  allm_url=$(svc_url anythingllm)
  allm_provider=$(docker exec harbor.anythingllm sh -c 'echo "$LLM_PROVIDER"' 2>/dev/null)
  if [ "$allm_provider" = "ollama" ]; then
    allm_model="$OLLAMA_TINY_MODEL"
  else
    allm_model="$MODEL"
  fi
  if probe_200 "L1 anythingllm ready" "$allm_url/api/ping" 300; then
    allm_slug=$(curl -s -m 10 -X POST "$allm_url/api/workspace/new" \
      -H 'Content-Type: application/json' -d '{"name":"harbor-it"}' \
      | jq -er '.workspace.slug' 2>/dev/null)
    if [ -n "$allm_slug" ]; then
      record PASS "L1 anythingllm workspace create" "$allm_slug"
      curl -s -m 10 -X POST "$allm_url/api/workspace/$allm_slug/update" \
        -H 'Content-Type: application/json' \
        -d '{"chatMode":"chat","chatModel":"'"$allm_model"'"}' >/dev/null 2>&1
      allm_final=$(curl -s -m 300 -X POST "$allm_url/api/workspace/$allm_slug/stream-chat" \
        -H 'Content-Type: application/json' \
        -d '{"message":"Reply with exactly: PONG","attachments":[]}' \
        | grep 'finalizeResponseStream' | tail -1)
      if echo "$allm_final" | grep -o '"completion_tokens":[0-9]*' \
        | grep -v '"completion_tokens":0$' >/dev/null; then
        record PASS "L1 anythingllm chat round trip" "$(echo "$allm_final" | grep -o '"completion_tokens":[0-9]*' | head -1)"
      else
        record FAIL "L1 anythingllm chat round trip" "no finalizeResponseStream with tokens"
      fi
      curl -s -m 10 -X DELETE "$allm_url/api/workspace/$allm_slug" >/dev/null 2>&1
    else
      record FAIL "L1 anythingllm workspace create"
    fi
  fi

  # L2 sqlchat — /api/chat only forwards built-in gpt-* model names
  # (upstream limitation): alias the tiny model in ollama and point the
  # request at ollama via the honored x-openai-endpoint header.
  local sql_url sql_out
  sql_url=$(svc_url sqlchat)
  if probe_200 "L2 sqlchat ready" "$sql_url/" 300; then
    docker exec harbor.ollama ollama cp "$OLLAMA_TINY_MODEL" gpt-3.5-turbo >/dev/null 2>&1
    local attempt
    for attempt in 1 2; do
      sql_out=$(curl -s -m 300 "$sql_url/api/chat" -H 'Content-Type: application/json' \
        -H 'x-openai-endpoint: http://ollama:11434/v1' \
        -d '{"messages":[{"role":"user","content":"Reply with exactly: PONG"}]}')
      echo "$sql_out" | grep 'PONG' >/dev/null && break
      log "L2 retry ($attempt)"
    done
    if echo "$sql_out" | grep 'PONG' >/dev/null; then
      record PASS "L2 sqlchat chat round trip" "PONG via ollama alias"
    else
      record FAIL "L2 sqlchat chat round trip" "$(echo "$sql_out" | tail -c 200)"
    fi
    docker exec harbor.ollama ollama rm gpt-3.5-turbo >/dev/null 2>&1
  fi

  teardown

  # ---- Sub-batch L-b: khoj + perplexica + ldr (each x ollama x searxng) + presenton
  log "Group L-b: khoj perplexica ldr presenton (searxng-paired frontends)"
  save_and_set_config khoj.default.model "$OLLAMA_TINY_MODEL"
  save_and_set_config presenton.ollama.model "$OLLAMA_TINY_MODEL"
  "$HARBOR" up ollama searxng khoj perplexica ldr presenton >/dev/null 2>&1
  docker exec harbor.ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  # L3 khoj — anonymous mode; chat via ollama, then /online via searxng.
  local khoj_url
  khoj_url=$(svc_url khoj)
  if probe_200 "L3 khoj ready" "$khoj_url/api/health" 600; then
    # /api/health 200s before khoj's async first-boot init (migrations +
    # chat-model creation) finishes — the first chat can die inside
    # get_default_chat_model. Retry a few times.
    local khoj_out khoj_try
    for khoj_try in 1 2 3; do
      khoj_out=$(curl -s -m 300 -N -X POST "$khoj_url/api/chat" \
        -H 'Content-Type: application/json' \
        -d '{"q":"Reply with exactly: PONG","stream":true}')
      echo "$khoj_out" | grep -a 'end_llm_response' >/dev/null && break
      log "L3 khoj chat retry ($khoj_try)"
      sleep 15
    done
    if echo "$khoj_out" | grep -a 'end_llm_response' >/dev/null \
      && echo "$khoj_out" | grep -a 'ONG' >/dev/null; then
      record PASS "L3 khoj chat round trip" "PONG via ollama"
    else
      record FAIL "L3 khoj chat round trip" "$(echo "$khoj_out" | tail -c 200)"
    fi
    khoj_out=$(curl -s -m 300 -N -X POST "$khoj_url/api/chat" \
      -H 'Content-Type: application/json' \
      -d '{"q":"/online latest Docker Compose version","stream":true}')
    if echo "$khoj_out" | grep -a '"organic"' >/dev/null; then
      record PASS "L3 khoj online search via searxng" "onlineContext has organic results"
    else
      record FAIL "L3 khoj online search via searxng" "no organic results in onlineContext"
    fi
  fi

  # L4 perplexica — backend lists ollama providers; WS webSearch round trip
  # (old andypenno fork is WebSocket-only; node >= 22 has a native client).
  local ppx_be ppx_port
  ppx_port=$("$HARBOR" config get perplexica.backend.host.port 2>/dev/null)
  ppx_be="http://localhost:${ppx_port:-34042}"
  if probe_200 "L4 perplexica backend ready" "$ppx_be/api/models" 300; then
    if curl -s -m 10 "$ppx_be/api/models" \
      | jq -er ".chatModelProviders.ollama | has(\"$OLLAMA_TINY_MODEL\")" >/dev/null 2>&1; then
      record PASS "L4 perplexica ollama models listed"
    else
      record FAIL "L4 perplexica ollama models listed" "tiny model missing from /api/models"
    fi
    if command -v node >/dev/null 2>&1; then
      local ppx_out
      if ppx_out=$(node tests/lib/perplexica-search.mjs "ws://localhost:${ppx_be##*:}" \
        "$OLLAMA_TINY_MODEL" "nomic-embed-text:latest" \
        "What is Docker Compose? Answer briefly." 2>&1); then
        record PASS "L4 perplexica webSearch round trip" "$(echo "$ppx_out" | cut -c1-120)"
      else
        record FAIL "L4 perplexica webSearch round trip" "$(echo "$ppx_out" | tail -c 200)"
      fi
    else
      record SKIP "L4 perplexica webSearch round trip" "node not installed"
    fi
  fi

  # L5 ldr — register/login (CSRF form + session), then a quick research via
  # searxng + ollama and assert the report has content.
  local ldr_url ldr_jar csrf rid st=""

  ldr_url=$(svc_url ldr)
  ldr_jar=$(mktemp /tmp/harbor-it-ldr-XXXXXX.jar)
  if probe_200 "L5 ldr ready" "$ldr_url/api/v1/health" 300; then
    csrf=$(curl -s -c "$ldr_jar" "$ldr_url/auth/register" \
      | grep -o 'csrf_token" value="[^"]*' | sed 's/.*value="//')
    curl -s -b "$ldr_jar" -c "$ldr_jar" -X POST "$ldr_url/auth/register" \
      --data-urlencode "csrf_token=$csrf" \
      -d 'username=harborit&password=harbor-it-pass1&confirm_password=harbor-it-pass1&acknowledge=true' \
      -o /dev/null 2>/dev/null # acknowledge must be the literal "true"; 400 if the user exists — ignored
    csrf=$(curl -s -b "$ldr_jar" -c "$ldr_jar" "$ldr_url/auth/login" \
      | grep -o 'csrf_token" value="[^"]*' | sed 's/.*value="//')
    local login_code
    login_code=$(curl -s -b "$ldr_jar" -c "$ldr_jar" -X POST "$ldr_url/auth/login" \
      --data-urlencode "csrf_token=$csrf" \
      -d 'username=harborit&password=harbor-it-pass1' -o /dev/null -w '%{http_code}')
    if [ "$login_code" = "302" ]; then
      record PASS "L5 ldr register+login" "302 to /"
      csrf=$(curl -s -b "$ldr_jar" -c "$ldr_jar" "$ldr_url/" \
        | grep -o 'csrf-token" content="[^"]*' | head -1 | sed 's/.*content="//')
      rid=$(curl -s -b "$ldr_jar" -c "$ldr_jar" -X POST "$ldr_url/api/start_research" \
        -H 'Content-Type: application/json' -H "X-CSRFToken: $csrf" \
        -d "{\"query\":\"What is Docker Compose? One short paragraph.\",\"mode\":\"quick\",\"model_provider\":\"OLLAMA\",\"model\":\"$OLLAMA_TINY_MODEL\",\"search_engine\":\"searxng\",\"iterations\":1,\"questions_per_iteration\":1,\"strategy\":\"source-based\"}" \
        | jq -er '.research_id' 2>/dev/null)
      if [ -n "$rid" ]; then
        for _ in $(seq 1 90); do
          st=$(curl -s -m 10 -b "$ldr_jar" "$ldr_url/api/research/$rid/status" \
            | jq -r '.status' 2>/dev/null)
          case "$st" in completed|failed|error|suspended|cancelled) break ;; esac
          sleep 10
        done
        if [ "$st" = "completed" ] && curl -s -b "$ldr_jar" "$ldr_url/api/report/$rid" \
          | jq -er '.content | select(length > 100)' >/dev/null 2>&1 \
          && ! curl -s -b "$ldr_jar" "$ldr_url/api/report/$rid" \
          | jq -r '.content' | grep -q 'No sources were found'; then
          record PASS "L5 ldr quick research via searxng+ollama" "completed with sourced report"
        else
          record FAIL "L5 ldr quick research via searxng+ollama" "status=$st"
        fi
      else
        record FAIL "L5 ldr research start" "no research_id"
      fi
    else
      record FAIL "L5 ldr register+login" "login code $login_code"
    fi
  fi
  rm -f "$ldr_jar"

  # L6 presenton — auth disabled by Harbor default; generate a tiny deck.
  local pres_url pres_out
  pres_url=$(svc_url presenton)
  if probe_200 "L6 presenton ready" "$pres_url/" 300; then
    pres_out=$(curl -s -m 580 -X POST "$pres_url/api/v1/ppt/presentation/generate" \
      -H 'Content-Type: application/json' \
      -d '{"content":"Docker Compose basics","n_slides":2,"language":"English","export_as":"pptx"}')
    if echo "$pres_out" | jq -er '.path | select(length > 0)' >/dev/null 2>&1; then
      record PASS "L6 presenton 2-slide pptx generate" "$(echo "$pres_out" | jq -r '.path' | tail -c 80)"
    else
      record FAIL "L6 presenton 2-slide pptx generate" "$(echo "$pres_out" | tail -c 200)"
    fi
  fi

  teardown

  # ---- Sub-batch L-c: run-style / TUI CLIs via ollama (aider, opint, oterm, parllama)
  log "Group L-c: aider opint oterm parllama (run-style CLIs via ollama)"
  save_and_set_config aider.model "$OLLAMA_TINY_MODEL"
  "$HARBOR" up ollama >/dev/null 2>&1
  docker exec harbor.ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  # L7 aider — interactive-only entrypoint (compose run -it): needs a pty.
  # /ask mode avoids file edits; run from a scratch dir so the mounted
  # workdir is never the repo.
  local aider_dir aider_out repo_root
  repo_root="$PWD"
  aider_dir=$(mktemp -d /tmp/harbor-it-aider-XXXXXX)
  aider_out=$(cd "$aider_dir" && python3 -c "
import pty, sys
rc = pty.spawn(['timeout','300','$repo_root/harbor.sh','aider','--message','/ask Reply with exactly: PONG','--no-git','--yes-always','--no-stream','--no-show-model-warnings'])
sys.exit(rc)
" </dev/null 2>&1)
  if echo "$aider_out" | grep -aE 'PONG|Tokens: .* sent' >/dev/null; then
    record PASS "L7 aider /ask round trip via ollama"
  else
    record FAIL "L7 aider /ask round trip via ollama" "$(echo "$aider_out" | tr -d '\r' | tail -c 200)"
  fi
  rm -rf "$aider_dir"

  # L8 opint — pin the backend (both .ollama and .llamacpp overlays override
  # the entrypoint; the winner is invocation-dependent). Piped stdin is read
  # as the chat message, EOF exits cleanly.
  save_and_set_config opint.backend ollama
  "$HARBOR" opint model "openai/$OLLAMA_TINY_MODEL" >/dev/null 2>&1
  local opint_out
  opint_out=$(echo 'Reply with exactly: PONG' | timeout 300 "$HARBOR" opint -y 2>&1)
  if echo "$opint_out" | grep -a 'PONG' >/dev/null; then
    record PASS "L8 opint chat round trip via ollama"
  else
    record FAIL "L8 opint chat round trip via ollama" "$(echo "$opint_out" | tail -c 200)"
  fi
  "$HARBOR" opint model qwen3.5:4b >/dev/null 2>&1 # shipped default

  # L9/L10 oterm + parllama — textual TUIs: assert the harbor-built images
  # run, report a version, and are wired to ollama (env + reachability).
  local tui_out
  tui_out=$($("$HARBOR" cmd ollama oterm 2>/dev/null) run --rm --entrypoint sh oterm -c \
    'echo "OLLAMA_URL=$OLLAMA_URL"; oterm --version; python3 -c "import urllib.request,os; urllib.request.urlopen(os.environ[\"OLLAMA_URL\"]+\"/api/version\", timeout=10)" && echo OLLAMA_REACHABLE' 2>&1)
  if echo "$tui_out" | grep -a 'oterm v' >/dev/null \
    && echo "$tui_out" | grep -a 'OLLAMA_URL=http://ollama:11434' >/dev/null \
    && echo "$tui_out" | grep -a 'OLLAMA_REACHABLE' >/dev/null; then
    record PASS "L9 oterm version + ollama wiring" "$(echo "$tui_out" | grep -a 'oterm v' | head -1)"
  else
    record FAIL "L9 oterm version + ollama wiring" "$(echo "$tui_out" | tail -c 200)"
  fi
  tui_out=$($("$HARBOR" cmd ollama parllama 2>/dev/null) run --rm --entrypoint sh parllama -c \
    'echo "OLLAMA_URL=$OLLAMA_URL"; uvx parllama --version' 2>&1)
  if echo "$tui_out" | grep -a 'parllama [0-9]' >/dev/null \
    && echo "$tui_out" | grep -a 'OLLAMA_URL=http://ollama:11434' >/dev/null; then
    record PASS "L10 parllama version + ollama wiring" "$(echo "$tui_out" | grep -a 'parllama [0-9]' | head -1)"
  else
    record FAIL "L10 parllama version + ollama wiring" "$(echo "$tui_out" | tail -c 200)"
  fi

  teardown
}

group_M() {
  log "=== Group M: proxies/gateways/MCP (bifrost, optillm, mcpo, metamcp, supergateway)"

  # --- M-a: OpenAI gateway proxies via ollama + llamacpp ---
  log "M-a: harbor up ollama optillm bifrost (optillm builds from git on first up)"
  "$HARBOR" up ollama optillm bifrost >/dev/null 2>&1

  local bifrost_url optillm_url
  bifrost_url=$(svc_url bifrost)
  optillm_url=$(svc_url optillm)
  docker exec harbor.ollama ollama pull "$OLLAMA_TINY_MODEL" >/dev/null 2>&1

  probe_200 "M1 bifrost health" "$bifrost_url/health" 180

  # Bootstrap sidecars must exit 0 and leave the provider key registered.
  # With a persisted services/bifrost/config.db this is the idempotency
  # regression check (keys live at /api/providers/<p>/keys, not on the
  # provider object).
  local rc_o rc_l keys_json
  rc_o=$(docker inspect -f '{{.State.ExitCode}}' harbor.bifrost-ollama-bootstrap 2>/dev/null)
  rc_l=$(docker inspect -f '{{.State.ExitCode}}' harbor.bifrost-llamacpp-bootstrap 2>/dev/null)
  keys_json=$(curl -s -m 10 "$bifrost_url/api/providers/ollama/keys")
  if [ "$rc_o" = "0" ] && [ "$rc_l" = "0" ] \
    && echo "$keys_json" | grep 'harbor-ollama' >/dev/null; then
    record PASS "M2 bifrost bootstraps idempotent" "both exit 0, harbor-ollama key present"
  else
    record FAIL "M2 bifrost bootstraps idempotent" "ollama rc=$rc_o llamacpp rc=$rc_l keys=$(echo "$keys_json" | cut -c1-120 | head -1)"
  fi

  # Proxy-through via ollama. qwen3 may spend part of the budget on
  # reasoning; accept non-empty content or reasoning.
  local reply
  reply=$(curl -s -m 240 "$bifrost_url/v1/chat/completions" \
    -H 'Content-Type: application/json' -H 'Authorization: Bearer sk-bifrost' \
    -d "{\"model\":\"ollama/$OLLAMA_TINY_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
    | jq -r '(.choices[0].message.content // "") + (.choices[0].message.reasoning // "")')
  if [ -n "$reply" ]; then
    record PASS "M3 bifrost proxies to ollama" "$(echo "$reply" | cut -c1-60 | head -1)"
  else
    record FAIL "M3 bifrost proxies to ollama" "empty reply"
  fi

  # Proxy-through via the llamacpp provider. Resolve the model id from the
  # llamacpp router itself — bifrost's persisted config.db can hold stale
  # ids from earlier bootstraps, and it forwards any llamacpp/<id> anyway.
  local bmodel
  resolve_model
  bmodel="llamacpp/$MODEL"
  # Retry: the llamacpp router closes the first connection while cold-
  # loading a model, which bifrost surfaces as "server closed connection".
  local m4_attempt
  reply=""
  for m4_attempt in 1 2 3; do
    reply=$(curl -s -m 240 "$bifrost_url/v1/chat/completions" \
      -H 'Content-Type: application/json' -H 'Authorization: Bearer sk-bifrost' \
      -d "{\"model\":\"$bmodel\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
      | jq -r '(.choices[0].message.content // "") + (.choices[0].message.reasoning // "")' 2>/dev/null)
    [ -n "$reply" ] && break
    sleep 10
  done
  if [ -n "$bmodel" ] && [ -n "$reply" ]; then
    record PASS "M4 bifrost proxies to llamacpp" "$bmodel attempt=$m4_attempt"
  else
    record FAIL "M4 bifrost proxies to llamacpp" "model=$bmodel reply-empty"
  fi

  probe_200 "M5 optillm models" "$optillm_url/v1/models" 120

  # Which backend won the overlay merge is invocation-dependent — read it
  # from the container and pick a non-thinking model accordingly. The
  # none-<model> prefix overrides the shipped OPTILLM_APPROACH=z3.
  local obase omodel attempt
  obase=$(docker exec harbor.optillm printenv OPTILLM_BASE_URL 2>/dev/null)
  if echo "$obase" | grep 'ollama' >/dev/null; then
    omodel="$OLLAMA_TINY_MODEL"
  else
    omodel="$OPENCODE_MODEL"
  fi
  for attempt in 1 2; do
    reply=$(curl -s -m 240 "$optillm_url/v1/chat/completions" \
      -H 'Content-Type: application/json' -H 'Authorization: Bearer sk-optillm' \
      -d "{\"model\":\"none-$omodel\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":$MAX_TOKENS}" \
      | jq -r '.choices[0].message.content // ""')
    if echo "$reply" | grep -i 'PONG' >/dev/null; then
      record PASS "M6 optillm proxies completion" "backend=$obase attempt=$attempt"
      break
    fi
    if [ "$attempt" = "2" ]; then
      record FAIL "M6 optillm proxies completion" "backend=$obase reply=$(echo "$reply" | cut -c1-80 | head -1)"
    fi
  done

  teardown

  # --- M-b: MCP over HTTP (metamcp + mcpo + mcp-server-time selector) ---
  log "M-b: harbor up metamcp mcpo mcp-server-time (metamcp builds from git on first up)"
  "$HARBOR" up metamcp mcpo mcp-server-time >/dev/null 2>&1

  local metamcp_url mcpo_url
  metamcp_url=$(svc_url metamcp)
  mcpo_url=$(svc_url mcpo)

  probe_200 "M7 metamcp UI" "$metamcp_url/mcp-servers" 300

  # Healthy SSE sidecar proves the headless project/profile/API-key seeding.
  local sse_health waited
  waited=0
  while [ "$waited" -le 120 ]; do
    sse_health=$(docker inspect -f '{{.State.Health.Status}}' harbor.metamcp-sse 2>/dev/null)
    [ "$sse_health" = "healthy" ] && break
    sleep 5
    waited=$((waited + 5))
  done
  if [ "$sse_health" = "healthy" ]; then
    record PASS "M8 metamcp-sse healthy" "after ${waited}s"
  else
    record FAIL "M8 metamcp-sse healthy" "status=$sse_health"
  fi

  # Real MCP tool exposed over OpenAPI HTTP (uvx installs on first start).
  probe_200 "M9a mcpo time docs" "$mcpo_url/time/docs" 180
  local tool_out
  tool_out=$(curl -s -m 30 -X POST "$mcpo_url/time/get_current_time" \
    -H 'Content-Type: application/json' -d '{"timezone":"UTC"}')
  if echo "$tool_out" | grep '"datetime"' >/dev/null; then
    record PASS "M9 mcpo MCP tool call" "$(echo "$tool_out" | cut -c1-60 | head -1)"
  else
    record FAIL "M9 mcpo MCP tool call" "$(echo "$tool_out" | cut -c1-120 | head -1)"
  fi

  # Aggregation round trip: seed a time server into metamcp, restart mcpo
  # (its metamcp session snapshots the tool list at connect), call the tool
  # through the mcpo -> supergateway -> metamcp-sse -> metamcp chain.
  docker exec harbor.metamcp-postgres sh -c \
    'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "INSERT INTO mcp_servers (name, description, command, args, profile_uuid) SELECT '\''time'\'', '\''it-seed'\'', '\''uvx'\'', ARRAY['\''mcp-server-time'\''], uuid FROM profiles LIMIT 1"' >/dev/null 2>&1
  docker restart harbor.mcpo >/dev/null 2>&1
  waited=0
  while [ "$waited" -le 240 ]; do
    if curl -s -m 10 "$mcpo_url/metamcp/openapi.json" 2>/dev/null \
      | grep 'mcp-time__get_current_time' >/dev/null; then
      break
    fi
    sleep 5
    waited=$((waited + 5))
  done
  tool_out=$(curl -s -m 60 -X POST "$mcpo_url/metamcp/mcp-time__get_current_time" \
    -H 'Content-Type: application/json' -d '{"timezone":"UTC"}')
  if echo "$tool_out" | grep '"datetime"' >/dev/null; then
    record PASS "M10 metamcp aggregation round trip" "after ${waited}s"
  else
    record FAIL "M10 metamcp aggregation round trip" "$(echo "$tool_out" | cut -c1-120 | head -1)"
  fi
  docker exec harbor.metamcp-postgres sh -c \
    'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "DELETE FROM mcp_servers WHERE description = '\''it-seed'\''"' >/dev/null 2>&1

  # --- M-c: supergateway stdio->SSE bridge (run-style, no ports) ---
  local sg_cid sg_out
  sg_cid=$($("$HARBOR" cmd supergateway) run -d supergateway \
    --stdio "uvx mcp-server-time" --port 8000 2>/dev/null | tail -1)
  sg_out=""
  waited=0
  while [ "$waited" -le 120 ]; do
    sg_out=$(docker exec "$sg_cid" sh -c 'curl -s -m 3 http://localhost:8000/sse' 2>/dev/null | head -2)
    [ -n "$sg_out" ] && break
    sleep 5
    waited=$((waited + 5))
  done
  if echo "$sg_out" | grep 'event: endpoint' >/dev/null \
    && echo "$sg_out" | grep 'sessionId' >/dev/null; then
    record PASS "M11 supergateway stdio->SSE bridge" "after ${waited}s"
  else
    record FAIL "M11 supergateway stdio->SSE bridge" "$(echo "$sg_out" | cut -c1-120 | head -1)"
  fi
  [ -n "$sg_cid" ] && docker rm -f "$sg_cid" >/dev/null 2>&1

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
I  webui searxng litellm boost jupyter promptfoo comfyui chatui librechat langflow (depth: chat/eval/kernel/workflow/flow)
J  llamacpp ollama lemonade localai voicebox vllm (ROCm paths; skipped on non-ROCm hosts, excluded by default)
K  landing hollama mikupad mock-openai qdrant libretranslate netdata dbhub drawio sillytavern lobechat traefik (standalone web services + routed traefik)
L  anythingllm sqlchat khoj perplexica ldr presenton aider opint oterm parllama (LLM frontends + CLIs)
M  bifrost optillm metamcp mcpo supergateway (proxies/gateways/MCP; git builds on first up)
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
      A|B|C|D|E|F|G|H|I|J|K|L|M) ;;
      *) echo "Unknown group: $g (valid: A-M)" >&2; exit 2 ;;
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
