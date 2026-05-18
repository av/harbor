#!/usr/bin/env bash
# Suite: launch-smoke
#
# End-user smoke coverage for `harbor launch codex|claude|opencode` without
# requiring those tools, Docker, or a live model server on the host. The suite
# fakes Docker's "running services" view, fakes /v1/models responses from
# Harbor-compatible backends, and executes fake host tools to verify the
# arguments and environment variables a user would actually depend on.
set -euo pipefail

suite_log() { echo "[launch-smoke] $*"; }
fail() { echo "[launch-smoke] FAIL: $*" >&2; exit 1; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HARBOR_BIN="${HARBOR_BIN:-${HARBOR_TEST_REPO}/harbor.sh}"

tmp_dir="$(mktemp -d -t harbor-launch-smoke.XXXXXX)"
fake_bin="$tmp_dir/bin"
harbor_home="$tmp_dir/harbor-home"
tool_log="$tmp_dir/tool.log"
opencode_config="$tmp_dir/opencode-config.json"
step_out="$tmp_dir/step.out"
parallel_out="$tmp_dir/parallel.out"
mkdir -p "$fake_bin" "$harbor_home/profiles"
cp "$HARBOR_TEST_REPO/profiles/default.env" "$harbor_home/profiles/default.env"

cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

cat >"$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then
  printf '%s\n' ${HARBOR_FAKE_RUNNING_SERVICES:-}
  exit 0
fi

if [ "$1" = "port" ]; then
  case "$2" in
    harbor.ollama)
      echo "11434/tcp -> 0.0.0.0:11434"
      exit 0
      ;;
    harbor.llamacpp)
      echo "8080/tcp -> 0.0.0.0:33821"
      exit 0
      ;;
    harbor.vllm)
      echo "8000/tcp -> 0.0.0.0:33822"
      exit 0
      ;;
  esac
fi

if [ "$1" = "compose" ]; then
  exit 0
fi

exit 1
EOF

cat >"$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
case "${HARBOR_FAKE_MODELS_SCHEMA:-openai}" in
  openai-mixed)
    printf '%s\n' '{"object":"list","data":[{"object":"model"},{"id":"mixed-openai-model","object":"model","owned_by":"harbor"}]}'
    ;;
  ollama-native)
    printf '%s\n' '{"models":[{"name":"llama3.2:latest","modified_at":"2026-05-18T00:00:00Z"}]}'
    ;;
  root-array)
    printf '%s\n' '[{"id":"root-array-model","object":"model"}]'
    ;;
  *)
    printf '%s\n' '{"object":"list","data":[{"id":"default-model","object":"model"}]}'
    ;;
esac
EOF

cat >"$fake_bin/codex" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=codex"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/claude" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=claude"
  echo "ANTHROPIC_AUTH_TOKEN=${ANTHROPIC_AUTH_TOKEN:-}"
  echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY-__unset__}"
  echo "ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/opencode" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=opencode"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
printf '%s\n' "${OPENCODE_CONFIG_CONTENT:-}" >"$HARBOR_LAUNCH_OPENCODE_CONFIG"
EOF

chmod +x "$fake_bin/docker" "$fake_bin/curl" "$fake_bin/codex" "$fake_bin/claude" "$fake_bin/opencode"

run_launch() {
  local name="$1"
  local running_services="$2"
  local schema="$3"
  shift 3

  suite_log "$name"
  : >"$tool_log"
  : >"$opencode_config"
  if ! env \
    HARBOR_LEGACY_CLI=true \
    HARBOR_CAPABILITIES_AUTODETECT=false \
    HARBOR_HOME="$harbor_home" \
    HARBOR_FAKE_RUNNING_SERVICES="$running_services" \
    HARBOR_FAKE_MODELS_SCHEMA="$schema" \
    HARBOR_LAUNCH_TOOL_LOG="$tool_log" \
    HARBOR_LAUNCH_OPENCODE_CONFIG="$opencode_config" \
    PATH="$fake_bin:/usr/bin:/bin" \
    "$HARBOR_BIN" launch "$@" >"$step_out" 2>&1; then
    cat "$step_out" >&2
    fail "$name exited non-zero"
  fi
}

run_parallel_history_smoke() {
  suite_log "parallel launch history writes do not share temp files"
  : >"$parallel_out"

  if ! env \
    HARBOR_LEGACY_CLI=true \
    HARBOR_CAPABILITIES_AUTODETECT=false \
    HARBOR_HOME="$harbor_home" \
    PATH="$fake_bin:/usr/bin:/bin" \
    "$HARBOR_BIN" config set history.size 1 >>"$parallel_out" 2>&1; then
    cat "$parallel_out" >&2
    fail "could not lower temporary history size"
  fi

  local pids=()
  local failed=0
  local i

  for ((i = 1; i <= 40; i++)); do
    env \
      HARBOR_LEGACY_CLI=true \
      HARBOR_CAPABILITIES_AUTODETECT=false \
      HARBOR_HOME="$harbor_home" \
      HARBOR_FAKE_RUNNING_SERVICES="ollama" \
      HARBOR_FAKE_MODELS_SCHEMA="openai-mixed" \
      PATH="$fake_bin:/usr/bin:/bin" \
      "$HARBOR_BIN" launch codex --backend ollama --model "race-$i" --config >>"$parallel_out" 2>&1 &
    pids+=("$!")
  done

  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      failed=1
    fi
  done

  if [ "$failed" -ne 0 ]; then
    cat "$parallel_out" >&2
    fail "parallel launch history smoke exited non-zero"
  fi

  if grep -Eq -- '\.history\.tmp|cannot stat .*history|No such file or directory.*history' "$parallel_out"; then
    cat "$parallel_out" >&2
    fail "parallel launch history smoke exposed a shared temp-file race"
  fi

  if find "$harbor_home" -maxdepth 1 -name 'harbor-history.*' | grep -q .; then
    find "$harbor_home" -maxdepth 1 -name 'harbor-history.*' -print >&2
    fail "parallel launch history smoke left history temp files behind"
  fi
}

assert_log() {
  local pattern="$1"
  if ! grep -Eq -- "$pattern" "$tool_log"; then
    echo "--- tool log ---" >&2
    cat "$tool_log" >&2
    echo "--- command output ---" >&2
    cat "$step_out" >&2
    fail "tool log did not match /$pattern/"
  fi
}

assert_json() {
  local filter="$1"
  if ! jq -e "$filter" "$opencode_config" >/dev/null; then
    echo "--- opencode config ---" >&2
    cat "$opencode_config" >&2
    fail "opencode config did not satisfy jq filter: $filter"
  fi
}

run_launch "codex uses OpenAI data[] model id and passes Codex provider config" \
  "ollama" "openai-mixed" \
  codex --backend ollama -- --sandbox workspace-write
assert_log '^tool=codex$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^arg=model_providers\.harbor_launch\.base_url="http://localhost:11434/v1"$'
assert_log '^arg=-m$'
assert_log '^arg=mixed-openai-model$'
assert_log '^arg=--sandbox$'
assert_log '^arg=workspace-write$'

run_launch "claude accepts Ollama-native models[] name schema and uses Anthropic env" \
  "ollama" "ollama-native" \
  claude --backend ollama -- -p "hello"
assert_log '^tool=claude$'
assert_log '^ANTHROPIC_AUTH_TOKEN=ollama$'
assert_log '^ANTHROPIC_API_KEY=$'
assert_log '^ANTHROPIC_BASE_URL=http://localhost:11434$'
assert_log '^arg=--model$'
assert_log '^arg=llama3\.2:latest$'
assert_log '^arg=-p$'
assert_log '^arg=hello$'

run_launch "opencode accepts root-array model schema and writes inline provider config" \
  "llamacpp" "root-array" \
  opencode --backend llamacpp run
assert_log '^tool=opencode$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^arg=-m$'
assert_log '^arg=harbor-llamacpp/root-array-model$'
assert_log '^arg=run$'
assert_json '.provider["harbor-llamacpp"].options.baseURL == "http://localhost:33821/v1"'
assert_json '.provider["harbor-llamacpp"].models["root-array-model"].tool_call == true'

run_parallel_history_smoke

suite_log "OK"
