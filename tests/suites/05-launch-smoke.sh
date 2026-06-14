#!/usr/bin/env bash
# Suite: launch-smoke
#
# End-user smoke coverage for `harbor launch` host tool adapters without
# requiring those tools, Docker, or a live model server on the host. The suite
# fakes Docker's "running services" view, fakes /v1/models responses from
# Harbor-compatible backends, and executes fake host tools to verify the
# arguments and environment variables a user would actually depend on.
set -euo pipefail

suite_log() { echo "[launch-smoke] $*"; }
fail() { echo "[launch-smoke] FAIL: $*" >&2; exit 1; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
launch_repo_slug="$(printf '%s' "$HARBOR_TEST_REPO" | sed 's#[^A-Za-z0-9._-]#-#g; s#--*#-#g; s#^-##; s#-$##')"

tmp_dir="$(mktemp -d -t harbor-launch-smoke.XXXXXX)"
fake_bin="$tmp_dir/bin"
harbor_home="$tmp_dir/harbor-home"
tool_log="$tmp_dir/tool.log"
docker_log="$tmp_dir/docker.log"
docker_state="$tmp_dir/docker-state"
opencode_config="$tmp_dir/opencode-config.json"
droid_config="$tmp_dir/factory/config.json"
openclaw_config="$tmp_dir/openclaw/openclaw.json"
pi_models_config="$tmp_dir/pi/models.json"
pi_settings_config="$tmp_dir/pi/settings.json"
step_out="$tmp_dir/step.out"
parallel_out="$tmp_dir/parallel.out"
launch_workspace="$tmp_dir/launch-tests"
mkdir -p "$fake_bin" "$harbor_home/profiles" "$harbor_home/services" "$launch_workspace"
cp "$HARBOR_TEST_REPO/profiles/default.env" "$harbor_home/profiles/default.env"
cp "$HARBOR_TEST_REPO/compose.yml" "$harbor_home/compose.yml"
# Symlink individual service compose files (not the directory itself) so that
# find without -L can traverse the services/ directory. A directory symlink
# would be opaque to find(1) without -L.
ln -st "$harbor_home/services" "$HARBOR_TEST_REPO"/services/compose.*.yml
# Symlink service subdirectories (config templates, etc.)
for _d in "$HARBOR_TEST_REPO"/services/*/; do
  [ -d "$_d" ] && ln -s "$_d" "$harbor_home/services/$(basename "$_d")" 2>/dev/null || true
done

cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

cat >"$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
if [ -n "${HARBOR_FAKE_DOCKER_LOG:-}" ]; then
  printf '%s\n' "$*" >>"$HARBOR_FAKE_DOCKER_LOG"
fi

running_services() {
  printf '%s\n' ${HARBOR_FAKE_RUNNING_SERVICES:-}
  if [ -n "${HARBOR_FAKE_DOCKER_STATE:-}" ] && [ -f "$HARBOR_FAKE_DOCKER_STATE" ]; then
    cat "$HARBOR_FAKE_DOCKER_STATE"
  fi
}

# _check_docker calls "docker version" to verify the daemon is running
if [ "$1" = "version" ]; then
  echo "Docker version 99.0.0 (fake)"
  exit 0
fi

if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then
  running_services
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
    harbor.boost)
      echo "8000/tcp -> 0.0.0.0:8004"
      exit 0
      ;;
    harbor.dmr)
      echo "8080/tcp -> 0.0.0.0:34920"
      exit 0
      ;;
    harbor.mlx)
      echo "8080/tcp -> 0.0.0.0:34930"
      exit 0
      ;;
    harbor.omlx)
      echo "8080/tcp -> 0.0.0.0:34940"
      exit 0
      ;;
  esac
fi

if [ "$1" = "compose" ]; then
  if [ -n "${HARBOR_FAKE_DOCKER_STATE:-}" ] && [[ " $* " == *" up -d --wait "* ]]; then
    # Extract service names from args after --wait
    seen_wait=false
    for arg in "$@"; do
      if $seen_wait; then
        case "$arg" in
          -*)
            ;;
          *)
            printf '%s\n' "$arg" >>"$HARBOR_FAKE_DOCKER_STATE"
            ;;
        esac
      fi
      if [ "$arg" = "--wait" ]; then
        seen_wait=true
      fi
    done
    # Also extract service names from -f compose.<service>.yml flags
    for arg in "$@"; do
      case "$arg" in
        */compose.*.yml)
          local_name="${arg##*/}"
          local_name="${local_name#compose.}"
          local_name="${local_name%.yml}"
          case "$local_name" in
            x.*) ;; # skip cross-service integration files
            *)   printf '%s\n' "$local_name" >>"$HARBOR_FAKE_DOCKER_STATE" ;;
          esac
          ;;
      esac
    done
  fi
  exit 0
fi

exit 0
EOF

cat >"$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
case "${HARBOR_FAKE_MODELS_SCHEMA:-openai}" in
  openai-mixed)
    printf '%s\n' '{"object":"list","data":[{"object":"model"},{"id":"mxbai-embed-large","object":"model","owned_by":"harbor"},{"id":"qwen-chat-model","object":"model","owned_by":"harbor"},{"id":"mixed-openai-model","object":"model","owned_by":"harbor"}]}'
    ;;
  ollama-native)
    printf '%s\n' '{"models":[{"name":"llama3.2:latest","modified_at":"2026-05-18T00:00:00Z"},{"name":"qwen3.5:4b","modified_at":"2026-05-18T00:00:00Z"}]}'
    ;;
  root-array)
    printf '%s\n' '[{"id":"root-array-model","object":"model"},{"id":"root-second-model","object":"model"}]'
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
  echo "cwd=$PWD"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/copilot" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=copilot"
  echo "cwd=$PWD"
  echo "COPILOT_PROVIDER_BASE_URL=${COPILOT_PROVIDER_BASE_URL:-}"
  echo "COPILOT_PROVIDER_API_KEY=${COPILOT_PROVIDER_API_KEY:-}"
  echo "COPILOT_PROVIDER_WIRE_API=${COPILOT_PROVIDER_WIRE_API:-}"
  echo "COPILOT_MODEL=${COPILOT_MODEL:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/claude" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=claude"
  echo "cwd=$PWD"
  echo "ANTHROPIC_AUTH_TOKEN=${ANTHROPIC_AUTH_TOKEN:-}"
  echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY-__unset__}"
  echo "ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/droid" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=droid"
  echo "cwd=$PWD"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/hermes" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=hermes"
  echo "cwd=$PWD"
  echo "OPENAI_BASE_URL=${OPENAI_BASE_URL:-}"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
  echo "HERMES_MODEL=${HERMES_MODEL:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/mi" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=mi"
  echo "cwd=$PWD"
  echo "OPENAI_BASE_URL=${OPENAI_BASE_URL:-}"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
  echo "MODEL=${MODEL:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/openclaw" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=openclaw"
  echo "cwd=$PWD"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/opencode" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=opencode"
  echo "cwd=$PWD"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
printf '%s\n' "${OPENCODE_CONFIG_CONTENT:-}" >"$HARBOR_LAUNCH_OPENCODE_CONFIG"
EOF

cat >"$fake_bin/pi" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=pi"
  echo "cwd=$PWD"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/pool" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=pool"
  echo "cwd=$PWD"
  echo "POOLSIDE_STANDALONE_BASE_URL=${POOLSIDE_STANDALONE_BASE_URL:-}"
  echo "POOLSIDE_API_KEY=${POOLSIDE_API_KEY:-}"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

cat >"$fake_bin/code" <<'EOF'
#!/usr/bin/env bash
{
  echo "tool=code"
  echo "cwd=$PWD"
  for arg in "$@"; do
    echo "arg=$arg"
  done
} >>"$HARBOR_LAUNCH_TOOL_LOG"
EOF

chmod +x "$fake_bin/docker" "$fake_bin/curl" "$fake_bin/codex" "$fake_bin/copilot" "$fake_bin/claude" "$fake_bin/droid" "$fake_bin/hermes" "$fake_bin/mi" "$fake_bin/openclaw" "$fake_bin/opencode" "$fake_bin/pi" "$fake_bin/pool" "$fake_bin/code"

run_launch() {
  local name="$1"
  local running_services="$2"
  local schema="$3"
  shift 3

  suite_log "$name"
  : >"$tool_log"
  : >"$docker_log"
  : >"$docker_state"
  : >"$opencode_config"
  rm -f "$droid_config" "$openclaw_config" "$pi_models_config" "$pi_settings_config"
  if ! env \
    HARBOR_LEGACY_CLI=true \
    HARBOR_CAPABILITIES_AUTODETECT=false \
    HARBOR_HOME="$harbor_home" \
    HARBOR_FAKE_RUNNING_SERVICES="$running_services" \
    HARBOR_FAKE_DOCKER_LOG="$docker_log" \
    HARBOR_FAKE_DOCKER_STATE="$docker_state" \
    HARBOR_FAKE_MODELS_SCHEMA="$schema" \
    HARBOR_LAUNCH_TOOL_LOG="$tool_log" \
    HARBOR_LAUNCH_OPENCODE_CONFIG="$opencode_config" \
    HARBOR_LAUNCH_DROID_CONFIG="$droid_config" \
    HARBOR_LAUNCH_OPENCLAW_CONFIG="$openclaw_config" \
    HARBOR_LAUNCH_PI_MODELS_CONFIG="$pi_models_config" \
    HARBOR_LAUNCH_PI_SETTINGS_CONFIG="$pi_settings_config" \
    PATH="$fake_bin:$PATH" \
    harbor launch "$@" >"$step_out" 2>&1; then
    cat "$step_out" >&2
    fail "$name exited non-zero"
  fi
}

assert_docker_log() {
  local pattern="$1"
  if ! grep -Eq -- "$pattern" "$docker_log"; then
    echo "--- docker log ---" >&2
    cat "$docker_log" >&2
    echo "--- command output ---" >&2
    cat "$step_out" >&2
    fail "docker log did not match /$pattern/"
  fi
}

run_parallel_history_smoke() {
  suite_log "parallel launch history writes do not share temp files"
  : >"$parallel_out"

  if ! env \
    HARBOR_LEGACY_CLI=true \
    HARBOR_CAPABILITIES_AUTODETECT=false \
    HARBOR_HOME="$harbor_home" \
    PATH="$fake_bin:$PATH" \
    harbor config set history.size 1 >>"$parallel_out" 2>&1; then
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
      PATH="$fake_bin:$PATH" \
      harbor launch --backend ollama --model "race-$i" --config codex >>"$parallel_out" 2>&1 &
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

assert_output() {
  local pattern="$1"
  if ! grep -Eq -- "$pattern" "$step_out"; then
    echo "--- command output ---" >&2
    cat "$step_out" >&2
    fail "command output did not match /$pattern/"
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

assert_file_json() {
  local path="$1"
  local filter="$2"
  if ! jq -e "$filter" "$path" >/dev/null; then
    echo "--- $path ---" >&2
    cat "$path" >&2
    fail "$path did not satisfy jq filter: $filter"
  fi
}

cd "$HARBOR_TEST_REPO"

run_launch "codex uses OpenAI data[] model id and passes Codex provider config" \
  "ollama" "openai-mixed" \
  --backend ollama codex --sandbox workspace-write
assert_log '^tool=codex$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^arg=model_providers\.harbor_launch\.base_url="http://localhost:11434/v1"$'
assert_log '^arg=-m$'
assert_log '^arg=qwen-chat-model$'
assert_log '^arg=--sandbox$'
assert_log '^arg=workspace-write$'

run_launch "tool arguments after the host tool name are passed through unchanged" \
  "ollama" "openai-mixed" \
  --backend ollama codex --model tool-model --backend tool-backend --config
assert_log '^tool=codex$'
assert_log '^arg=--model$'
assert_log '^arg=tool-model$'
assert_log '^arg=--backend$'
assert_log '^arg=tool-backend$'
assert_log '^arg=--config$'

run_launch "explicit backend is started when missing" \
  "" "root-array" \
  --backend llamacpp --model root-array-model opencode run
assert_log '^tool=opencode$'
assert_log '^arg=harbor-llamacpp/root-array-model$'
assert_output "Backend 'llamacpp' is not running; starting it"
assert_docker_log 'compose.llamacpp.yml.*up -d --wait'

run_launch "starts llamacpp when no backend is running" \
  "" "root-array" \
  --model root-array-model opencode run
assert_log '^tool=opencode$'
assert_log '^arg=harbor-llamacpp/root-array-model$'
assert_output 'No running Harbor OpenAI-compatible backend found; starting llamacpp'
assert_docker_log 'compose.llamacpp.yml.*up -d --wait'

run_launch "web launch starts SearXNG and routes through boost-web workflow model" \
  "ollama boost" "openai-mixed" \
  --web --backend ollama codex --sandbox workspace-write
assert_log '^tool=codex$'
assert_log '^arg=model_providers\.harbor_launch\.base_url="http://localhost:8004/v1"$'
assert_log '^arg=-m$'
assert_log '^arg=boost-web-qwen-chat-model$'
assert_docker_log 'up -d --wait boost searxng$'
assert_output "Starting Boost workflow 'boost-web' for backend 'ollama'"

run_launch "already-prefixed boost workflow model is not prefixed again" \
  "ollama boost" "openai-mixed" \
  --web --backend ollama --model boost-web-qwen-chat-model codex
assert_log '^tool=codex$'
assert_log '^arg=-m$'
assert_log '^arg=boost-web-qwen-chat-model$'

run_launch "launch --web config prints boosted model and Boost API settings" \
  "ollama boost" "openai-mixed" \
  --web --backend ollama --config codex
assert_output '^backend=boost$'
assert_output '^model=boost-web-qwen-chat-model$'
assert_output '^OPENAI_API_KEY=sk-boost$'
assert_output 'base_url="http://localhost:8004/v1"'

run_launch "launch codex warns about llama.cpp Responses API tool compatibility" \
  "llamacpp" "root-array" \
  --backend llamacpp --model root-array-model codex --sandbox read-only
assert_log '^tool=codex$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^arg=root-array-model$'
assert_log '^arg=read-only$'
assert_output 'Codex CLI uses the Responses API tool schema'
assert_output "400 'type' of tool must be 'function'"

run_launch "claude accepts Ollama-native models[] name schema and uses Anthropic env" \
  "ollama" "ollama-native" \
  --backend ollama claude -p "hello"
assert_log '^tool=claude$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^ANTHROPIC_AUTH_TOKEN=ollama$'
assert_log '^ANTHROPIC_API_KEY=$'
assert_log '^ANTHROPIC_BASE_URL=http://localhost:11434$'
assert_log '^arg=--model$'
assert_log '^arg=llama3\.2:latest$'
assert_log '^arg=-p$'
assert_log '^arg=hello$'

run_launch "claude explicit non-Boost backend ignores running Boost" \
  "boost vllm" "root-array" \
  --backend vllm --model root-array-model claude -p "hello"
assert_log '^tool=claude$'
assert_log '^ANTHROPIC_AUTH_TOKEN=$'
assert_log '^ANTHROPIC_API_KEY=sk-harbor$'
assert_log '^ANTHROPIC_BASE_URL=http://localhost:33822$'
assert_log '^arg=--model$'
assert_log '^arg=root-array-model$'
assert_log '^arg=-p$'
assert_log '^arg=hello$'

run_launch "opencode accepts root-array model schema and writes inline provider config" \
  "llamacpp" "root-array" \
  --backend llamacpp opencode run
assert_log '^tool=opencode$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^arg=-m$'
assert_log '^arg=harbor-llamacpp/root-array-model$'
assert_log '^arg=run$'
assert_json '.provider["harbor-llamacpp"].options.baseURL == "http://localhost:33821/v1"'
assert_json '.provider["harbor-llamacpp"].models["root-array-model"].tool_call == true'
assert_json '.provider["harbor-llamacpp"].models["root-second-model"].tool_call == true'

run_launch "mi uses host CLI with OpenAI base URL without v1 suffix" \
  "ollama" "openai-mixed" \
  --backend ollama mi -p hello
assert_log '^tool=mi$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_BASE_URL=http://localhost:11434$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^MODEL=qwen-chat-model$'
assert_log '^arg=-p$'
assert_log '^arg=hello$'

run_launch "mi --web routes through Boost without v1 suffix" \
  "ollama boost" "openai-mixed" \
  --web --backend ollama mi -p hello
assert_log '^tool=mi$'
assert_log '^OPENAI_BASE_URL=http://localhost:8004$'
assert_log '^OPENAI_API_KEY=sk-boost$'
assert_log '^MODEL=boost-web-qwen-chat-model$'
assert_docker_log 'up -d --wait boost searxng$'

run_launch "copilot uses Ollama-compatible Responses API environment" \
  "ollama" "openai-mixed" \
  --backend ollama copilot -p "hello"
assert_log '^tool=copilot$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^COPILOT_PROVIDER_BASE_URL=http://localhost:11434/v1$'
assert_log '^COPILOT_PROVIDER_API_KEY=sk-harbor$'
assert_log '^COPILOT_PROVIDER_WIRE_API=responses$'
assert_log '^COPILOT_MODEL=qwen-chat-model$'
assert_log '^arg=-p$'
assert_log '^arg=hello$'

run_launch "droid writes Factory config and launches Droid CLI" \
  "ollama" "openai-mixed" \
  --backend ollama droid
assert_log '^tool=droid$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_file_json "$droid_config" '.custom_models[] | select(.model == "mixed-openai-model" and .base_url == "http://localhost:11434/v1/" and .provider == "generic-chat-completion-api")'
assert_file_json "$droid_config" '.custom_models[] | select(.model == "mxbai-embed-large" and .base_url == "http://localhost:11434/v1/" and .provider == "generic-chat-completion-api")'
assert_file_json "$droid_config" '.custom_models[] | select(.model == "qwen-chat-model" and .base_url == "http://localhost:11434/v1/" and .provider == "generic-chat-completion-api")'

run_launch "openclaw writes OpenClaw provider config and defaults to TUI" \
  "llamacpp" "root-array" \
  --backend llamacpp openclaw
assert_log '^tool=openclaw$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^arg=tui$'
assert_file_json "$openclaw_config" '.agents.defaults.model.primary == "harbor-llamacpp/root-array-model"'
assert_file_json "$openclaw_config" '.models.providers["harbor-llamacpp"].baseUrl == "http://localhost:33821/v1"'
assert_file_json "$openclaw_config" '.models.providers["harbor-llamacpp"].models[] | select(.id == "root-array-model")'
assert_file_json "$openclaw_config" '.models.providers["harbor-llamacpp"].models[] | select(.id == "root-second-model")'

run_launch "pi writes Pi model and settings config" \
  "ollama" "openai-mixed" \
  --backend ollama pi
assert_log '^tool=pi$'
assert_file_json "$pi_models_config" '.providers["harbor-ollama"].models[] | select(.id == "mixed-openai-model")'
assert_file_json "$pi_models_config" '.providers["harbor-ollama"].models[] | select(.id == "mxbai-embed-large")'
assert_file_json "$pi_models_config" '.providers["harbor-ollama"].models[] | select(.id == "qwen-chat-model")'
assert_file_json "$pi_settings_config" '.defaultProvider == "harbor-ollama" and .defaultModel == "qwen-chat-model"'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^arg=--session-dir$'
assert_log '^arg=.*/\.pi/agent/sessions/'"$launch_repo_slug"'$'

run_launch "pi preserves a non-Harbor caller workspace" \
  "ollama" "openai-mixed" \
  --backend ollama --model qwen-chat-model pi -p "hello"
if ! env \
  HARBOR_LEGACY_CLI=true \
  HARBOR_CAPABILITIES_AUTODETECT=false \
  HARBOR_HOME="$harbor_home" \
  HARBOR_FAKE_RUNNING_SERVICES="ollama" \
  HARBOR_FAKE_MODELS_SCHEMA="openai-mixed" \
  HARBOR_LAUNCH_TOOL_LOG="$tool_log" \
  HARBOR_LAUNCH_PI_MODELS_CONFIG="$pi_models_config" \
  HARBOR_LAUNCH_PI_SETTINGS_CONFIG="$pi_settings_config" \
  PATH="$fake_bin:$PATH" \
  bash -c 'cd "$1" && harbor launch --backend ollama --model qwen-chat-model pi -p hello' bash "$launch_workspace" >"$step_out" 2>&1; then
  cat "$step_out" >&2
  fail "pi non-Harbor caller workspace launch exited non-zero"
fi
assert_log '^cwd='"$launch_workspace"'$'
assert_log '^arg=--session-dir$'
assert_log '^arg=.*/\.pi/agent/sessions/'"$(printf '%s' "$launch_workspace" | sed 's#[^A-Za-z0-9._-]#-#g; s#--*#-#g; s#^-##; s#-$##')"'$'

run_launch "pool uses Poolside environment and model argument" \
  "ollama" "openai-mixed" \
  --backend ollama pool run
assert_log '^tool=pool$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^POOLSIDE_STANDALONE_BASE_URL=http://localhost:11434/v1$'
assert_log '^POOLSIDE_API_KEY=sk-harbor$'
assert_log '^arg=-m$'
assert_log '^arg=qwen-chat-model$'
assert_log '^arg=run$'

run_launch "hermes uses OpenAI-compatible environment and defaults to chat" \
  "ollama" "openai-mixed" \
  --backend ollama hermes
assert_log '^tool=hermes$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_BASE_URL=http://localhost:11434/v1$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^HERMES_MODEL=qwen-chat-model$'
assert_log '^arg=chat$'

run_launch "vscode opens the current workspace through code" \
  "ollama" "openai-mixed" \
  --backend ollama --model mixed-openai-model vscode
assert_log '^tool=code$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^arg='"$HARBOR_TEST_REPO"'$'

run_launch "dmr backend resolves models and launches codex" \
  "dmr" "root-array" \
  --backend dmr codex
assert_log '^tool=codex$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_API_KEY=sk-dmr$'
assert_log '^arg=-m$'
assert_log '^arg=root-array-model$'

run_launch "dmr backend launches claude with correct base URL" \
  "dmr" "root-array" \
  --backend dmr --model root-array-model claude -p "hello"
assert_log '^tool=claude$'
assert_log '^ANTHROPIC_BASE_URL=http://localhost:34920$'
assert_log '^arg=--model$'
assert_log '^arg=root-array-model$'
assert_log '^arg=-p$'
assert_log '^arg=hello$'

run_launch "mlx backend resolves models and launches codex" \
  "mlx" "root-array" \
  --backend mlx codex
assert_log '^tool=codex$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^arg=-m$'
assert_log '^arg=root-array-model$'

run_launch "mlx backend launches opencode with inline provider config" \
  "mlx" "root-array" \
  --backend mlx opencode run
assert_log '^tool=opencode$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_API_KEY=sk-harbor$'
assert_log '^arg=-m$'
assert_log '^arg=harbor-mlx/root-array-model$'
assert_log '^arg=run$'
assert_json '.provider["harbor-mlx"].options.baseURL == "http://localhost:34930/v1"'

run_launch "omlx backend resolves models and launches codex" \
  "omlx" "root-array" \
  --backend omlx codex
assert_log '^tool=codex$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_API_KEY=sk-omlx$'
assert_log '^arg=-m$'
assert_log '^arg=root-array-model$'

run_launch "omlx backend launches hermes with correct environment" \
  "omlx" "openai-mixed" \
  --backend omlx hermes
assert_log '^tool=hermes$'
assert_log '^cwd='"$HARBOR_TEST_REPO"'$'
assert_log '^OPENAI_BASE_URL=http://localhost:34940/v1$'
assert_log '^OPENAI_API_KEY=sk-omlx$'
assert_log '^HERMES_MODEL=qwen-chat-model$'
assert_log '^arg=chat$'

run_launch "dmr backend starts when not running" \
  "" "root-array" \
  --backend dmr --model root-array-model opencode run
assert_log '^tool=opencode$'
assert_log '^arg=harbor-dmr/root-array-model$'
assert_output "Backend 'dmr' is not running; starting it"
assert_docker_log 'compose.dmr.yml.*up -d --wait'

run_parallel_history_smoke

suite_log "OK"
