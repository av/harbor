#!/usr/bin/env bash
# Suite: cli
#
# Exercises harbor CLI surface that does NOT require services to be running.
# These are the commands users hit constantly (config, ls, env, url, cmd, …)
# and they share code paths with install (env_manager, .env round-trip,
# profile merging) — so a regression here typically masks a portability bug.
#
# Why "non-container": this suite is fast (~1s on every row), runs with no
# docker traffic, and catches bash-portability bugs (the `tr '[:lower:]'`
# class) on every distro before we spend 30s booting mock-openai.
#
# Each step uses `assert_ok` to keep failures specific. We do NOT trap
# cleanup — the suite leaves the .env in its original state via paired
# set/unset round-trips and runs `harbor config update` last.
set -euo pipefail

suite_log() { echo "[cli] $*"; }
fail() { echo "[cli] FAIL: $*" >&2; exit 1; }

# Run a command, capture its output, assert exit 0.
assert_ok() {
  local name="$1"; shift
  suite_log "$name"
  if ! "$@" >/tmp/cli-step.out 2>&1; then
    cat /tmp/cli-step.out >&2
    fail "$name (exit $?)"
  fi
}

# Run a command, assert exit 0 AND that stdout matches a regex.
assert_match() {
  local name="$1" regex="$2"; shift 2
  suite_log "$name"
  if ! "$@" >/tmp/cli-step.out 2>&1; then
    cat /tmp/cli-step.out >&2
    fail "$name (exit $?)"
  fi
  if ! grep -Eq -- "$regex" /tmp/cli-step.out; then
    cat /tmp/cli-step.out >&2
    fail "$name (output did not match /$regex/)"
  fi
}

assert_not_match() {
  local name="$1" regex="$2"; shift 2
  suite_log "$name"
  if ! "$@" >/tmp/cli-step.out 2>&1; then
    cat /tmp/cli-step.out >&2
    fail "$name (exit $?)"
  fi
  if grep -Eq -- "$regex" /tmp/cli-step.out; then
    cat /tmp/cli-step.out >&2
    fail "$name (output unexpectedly matched /$regex/)"
  fi
}

# 1. Version + help — the script must boot without errors.
assert_match "harbor --version"      'Harbor CLI version: [0-9]+\.[0-9]+\.[0-9]+' harbor --version
assert_match "harbor help (alias)"   'Usage:'                                     harbor --help

# 2. Service listing.
# `harbor ls` walks every services/compose.*.yml; a YAML parse error or a
# new compose lint regression surfaces here as a non-zero exit.
assert_ok    "harbor ls"             harbor ls

# 3. Config — get, set, unset round-trip on a fresh key.
#    This is the exact path that contained the original `tr '[:lower:]'`
#    bug class (incident: hpme_vpuume), so we exercise dot-, dash-, and
#    underscore-separated key names — they all map to the same env var.
assert_match "config get (dot)"      '^harbor$' harbor config get container.prefix
assert_match "config get (dash)"     '^harbor$' harbor config get container-prefix
assert_match "config get (under)"    '^harbor$' harbor config get container_prefix

assert_ok    "config set test.value" harbor config set test.value '42'
assert_match "config get test.value" '^42$'    harbor config get test.value
assert_ok    "config unset test"     harbor config unset test.value

# After unset the key should produce empty output and exit 0.
got=$(harbor config get test.value 2>/dev/null || true)
[ -z "$got" ] || fail "config get after unset returned '$got' (expected empty)"
suite_log "config unset → empty get OK"

# 4. Config search — must find at least one well-known key.
#    `harbor config search` exercises the same lower-case display path
#    (`${key,,}`) that the tr fix moved to.
assert_match "config search ollama"  'ollama\.' harbor config search ollama

# 5. Config update — propagates profiles/default.env into .env, idempotent.
assert_ok    "config update (1st)"   harbor config update
assert_ok    "config update (2nd)"   harbor config update

# 6. Service env reads + writes against a known service (ollama is a default).
#    `harbor env ollama` lists overrides in services/ollama/override.env.
assert_ok    "env ollama (list)"     harbor env ollama
assert_ok    "env ollama port get"   harbor env ollama OLLAMA_HOST 0.0.0.0
# Round-trip: confirm the value persisted, then restore the upstream default
# so the row's env is unchanged for downstream suites.
assert_match "env ollama port read"  '0.0.0.0' harbor env ollama OLLAMA_HOST
assert_ok    "env ollama port reset" harbor env ollama OLLAMA_HOST 0.0.0.0

# 7. cmd helper — prints the raw `docker compose ...` invocation Harbor
#    would run for the given service. Pure-bash, no container traffic.
#    `harbor url` is intentionally NOT tested here: it computes the URL
#    from the running container's published port, so it only succeeds
#    once the service is up — that path is exercised in the smoke suite.
assert_match "harbor cmd ollama"     'docker[ -]compose'            harbor cmd ollama

# 7b. launch — OpenCode is both a host tool adapter name and a Harbor service.
#     Users need an explicit service mode that does not require the host tool
#     binary and still reuses the active Harbor compose selection.
fake_bin="$(mktemp -d -t harbor.XXXXXX)"
fake_docker_log="$(mktemp -t harbor.XXXXXX)"
cat >"$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "compose ps --format {{.Service}}")
    echo "ollama"
    exit 0
    ;;
  "compose ps --services --filter status=running")
    echo "ollama"
    exit 0
    ;;
  "compose ps -a --services --filter status=running")
    echo "ollama"
    exit 0
    ;;
  "port harbor.ollama")
    echo "11434/tcp -> 0.0.0.0:11434"
    exit 0
    ;;
esac

if [ "$1" = "compose" ]; then
  printf '%s\n' "$*" >>"$HARBOR_FAKE_DOCKER_LOG"
  if [ "${HARBOR_FAKE_PROMPTFOO_UP_EXIT:-0}" != "0" ] && [[ "$*" == *" up -d --wait"* ]]; then
    exit "$HARBOR_FAKE_PROMPTFOO_UP_EXIT"
  fi
  if [ "${HARBOR_FAKE_PROMPTFOO_RUN_EXIT:-0}" != "0" ] && [[ "$*" == *" run -T --rm"* ]] && [[ "$*" == *" --entrypoint promptfoo promptfoo --version"* ]]; then
    exit "$HARBOR_FAKE_PROMPTFOO_RUN_EXIT"
  fi
  exit 0
fi

exit 0
EOF
cat >"$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '{"data":[{"id":"test-model"}]}'
EOF
chmod +x "$fake_bin/docker" "$fake_bin/curl"

assert_match "launch help documents service mode" '--service opencode' harbor launch --help
assert_match "launch help lists supported launch targets" 'Supported launch targets:' harbor launch --help
assert_match "launch help lists host tools" 'Host tools: .*codex.*pi.*vscode' harbor launch --help
assert_match "launch help lists dmr mlx and omlx backends" 'Backends: .*dmr.*mlx.*omlx' harbor launch --help
assert_match "launch help lists service CLI shortcuts" 'Service CLI shortcuts: .*plandex.*promptfoo.*tokscale' harbor launch --help
assert_match "launch help lists container service fallback" "Container services: any service from 'harbor ls'.*mi.*opencode" harbor launch --help
assert_match "launch help documents web as the only tool modifier" '^--model, --config, and --web\.$' harbor launch --help
assert_not_match "launch help does not list removed tool groups" '--time|--notes|--files|--scratch' harbor launch --help

suite_log "launch help avoids broken generic service --help example"
if harbor launch --help >/tmp/cli-step.out 2>&1 && grep -Eq -- 'harbor launch llamacpp --help' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch help advertised a generic service --help example that treats --help as the container command"
fi

suite_log "launch --service requires a handle"
if harbor launch --service >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch --service without handle unexpectedly succeeded"
fi
if ! grep -Eq -- 'Usage: harbor launch \[launch-options\] \[--service\] <service\|tool>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch --service without handle did not print usage"
fi

suite_log "launch opencode missing host tool suggests service mode"
: >"$fake_docker_log"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_DOCKER_LOG="$fake_docker_log" PATH="$fake_bin:$PATH" harbor launch --backend ollama --model test-model opencode >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch opencode missing host tool unexpectedly succeeded"
fi
if ! grep -Eq -- 'harbor launch --service opencode' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch opencode missing host tool did not suggest service mode"
fi
if [ -s "$fake_docker_log" ]; then
  cat "$fake_docker_log" >&2
  fail "launch opencode missing host tool started compose before validating the host binary"
fi

assert_ok "launch --service opencode" env HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_DOCKER_LOG="$fake_docker_log" PATH="$fake_bin:$PATH" harbor launch --service opencode --help
if ! grep -Eq -- 'run -T --rm opencode --help' "$fake_docker_log"; then
  cat "$fake_docker_log" >&2
  fail "launch --service opencode did not dispatch to docker compose run"
fi

suite_log "launch promptfoo propagates startup failure"
: >"$fake_docker_log"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_DOCKER_LOG="$fake_docker_log" HARBOR_FAKE_PROMPTFOO_UP_EXIT=42 PATH="$fake_bin:$PATH" harbor launch promptfoo --version >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch promptfoo startup failure unexpectedly succeeded"
fi
if grep -Eq -- 'run .*--entrypoint promptfoo promptfoo --version' "$fake_docker_log"; then
  cat "$fake_docker_log" >&2
  fail "launch promptfoo continued to CLI run after startup failure"
fi

suite_log "launch promptfoo uses noninteractive run flag and propagates CLI failure"
: >"$fake_docker_log"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_DOCKER_LOG="$fake_docker_log" HARBOR_FAKE_PROMPTFOO_RUN_EXIT=43 PATH="$fake_bin:$PATH" harbor launch promptfoo --version >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch promptfoo CLI failure unexpectedly succeeded"
fi
if ! grep -Eq -- 'run -T --rm .* --entrypoint promptfoo promptfoo --version' "$fake_docker_log"; then
  cat "$fake_docker_log" >&2
  fail "launch promptfoo did not use noninteractive compose run"
fi
if grep -Eq -- 'run .* -it ' "$fake_docker_log"; then
  cat "$fake_docker_log" >&2
  fail "launch promptfoo used interactive compose run without a TTY"
fi
rm -rf "$fake_bin" "$fake_docker_log"

# 7c. launch host adapters — backend/model discovery failures should be
#     actionable from a user's terminal, and --model must avoid parsing
#     /v1/models while still checking that the selected backend is reachable.
launch_fake_bin="$(mktemp -d -t harbor.XXXXXX)"
launch_fake_curl_log="$(mktemp -t harbor.XXXXXX)"
launch_fake_docker_state="$(mktemp -t harbor.XXXXXX)"
cat >"$launch_fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
running_services() {
  printf '%s\n' ${HARBOR_FAKE_RUNNING_SERVICES:-}
  if [ -n "${HARBOR_FAKE_DOCKER_STATE:-}" ] && [ -f "$HARBOR_FAKE_DOCKER_STATE" ]; then
    cat "$HARBOR_FAKE_DOCKER_STATE"
  fi
}

case "$*" in
  "compose ps --format {{.Service}}")
    running_services
    exit 0
    ;;
  "compose ps --services --filter status=running")
    running_services
    exit 0
    ;;
  "compose ps -a --services --filter status=running")
    running_services
    exit 0
    ;;
  "port harbor.ollama")
    echo "11434/tcp -> 0.0.0.0:11434"
    exit 0
    ;;
  "port harbor.llamacpp")
    echo "8080/tcp -> 0.0.0.0:33821"
    exit 0
    ;;
  "port harbor.unsloth-studio")
    echo "34851/tcp -> 0.0.0.0:34851"
    exit 0
    ;;
esac

if [ "$1" = "compose" ]; then
  if [ -n "${HARBOR_FAKE_DOCKER_STATE:-}" ] && [[ " $* " == *" up -d --wait "* ]]; then
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
  fi
  exit 0
fi

exit 0
EOF
cat >"$launch_fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
if [ -n "${HARBOR_FAKE_CURL_LOG:-}" ]; then
  printf '%s\n' "$*" >>"$HARBOR_FAKE_CURL_LOG"
fi

case "${HARBOR_FAKE_CURL_MODE:-models}" in
  fail)
    exit 7
    ;;
  empty)
    printf '%s\n' '{"data":[]}'
    ;;
  invalid)
    printf '%s\n' 'not-json'
    ;;
  *)
    printf '%s\n' '{"data":[{"id":"fake-discovered"}]}'
    ;;
esac
EOF
chmod +x "$launch_fake_bin/docker" "$launch_fake_bin/curl"

assert_launch_missing_option() {
  local name="$1"
  local expected="$2"
  shift 2

  suite_log "$name"
  : >"$launch_fake_docker_state"
  if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=ollama HARBOR_FAKE_DOCKER_STATE="$launch_fake_docker_state" PATH="$launch_fake_bin:$PATH" harbor launch "$@" >/tmp/cli-step.out 2>&1; then
    cat /tmp/cli-step.out >&2
    fail "$name unexpectedly succeeded"
  fi
  if ! grep -Fq -- "$expected" /tmp/cli-step.out; then
    cat /tmp/cli-step.out >&2
    fail "$name did not print usage"
  fi
}

suite_log "launch host options reject missing values"
assert_launch_missing_option "launch --backend rejects omitted value" "Usage: harbor launch --backend <value> <tool> [args]" --backend
assert_launch_missing_option "launch --backend rejects option as value" "Usage: harbor launch --backend <value> <tool> [args]" --backend --model explicit codex
assert_launch_missing_option "launch --backend= rejects empty inline value" "Usage: harbor launch --backend <value> <tool> [args]" --backend= --model explicit codex
assert_launch_missing_option "launch --model rejects omitted value" "Usage: harbor launch --model <value> <tool> [args]" --model
assert_launch_missing_option "launch --model rejects option as value" "Usage: harbor launch --model <value> <tool> [args]" --model --config codex
assert_launch_missing_option "launch --model= rejects empty inline value" "Usage: harbor launch --model <value> <tool> [args]" --model= --backend ollama codex

suite_log "launch --time is not a launch option"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=ollama HARBOR_FAKE_DOCKER_STATE="$launch_fake_docker_state" PATH="$launch_fake_bin:$PATH" harbor launch --time codex >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch --time unexpectedly succeeded"
fi
if ! grep -Eq -- "Service '--time' not found" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch --time did not fail as an unsupported launch target"
fi

suite_log "launch codex starts llamacpp when no backend is running"
: >"$launch_fake_docker_state"
if ! HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=webui HARBOR_FAKE_DOCKER_STATE="$launch_fake_docker_state" PATH="$launch_fake_bin:$PATH" harbor launch --config codex >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex without running backend did not start llamacpp"
fi
if ! grep -Eq -- 'No running Harbor OpenAI-compatible backend found; starting llamacpp' /tmp/cli-step.out || ! grep -Eq -- '^backend=llamacpp$' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex without running backend did not use llamacpp"
fi

suite_log "launch codex starts explicit backend when missing"
: >"$launch_fake_docker_state"
if ! HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=webui HARBOR_FAKE_DOCKER_STATE="$launch_fake_docker_state" PATH="$launch_fake_bin:$PATH" harbor launch --backend ollama --config codex >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with stopped explicit backend did not start it"
fi
if ! grep -Eq -- "Backend 'ollama' is not running; starting it" /tmp/cli-step.out || ! grep -Eq -- '^backend=ollama$' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with stopped explicit backend did not use ollama"
fi

suite_log "launch codex reports explicit backend unreachable"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=ollama HARBOR_FAKE_CURL_MODE=fail PATH="$launch_fake_bin:$PATH" harbor launch --backend ollama --model test-model --config codex >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with unreachable explicit backend unexpectedly succeeded"
fi
if ! grep -Eq -- "Backend 'ollama' is running, but its OpenAI-compatible endpoint is not reachable" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with unreachable explicit backend did not print reachability error"
fi

suite_log "launch codex reports empty /v1/models"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=unsloth-studio HARBOR_FAKE_CURL_MODE=empty PATH="$launch_fake_bin:$PATH" harbor launch --backend unsloth-studio --config codex >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with empty models unexpectedly succeeded"
fi
if ! grep -Eq -- "did not advertise any models" /tmp/cli-step.out || ! grep -Eq -- 'harbor launch --backend unsloth-studio --model <model> codex' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with empty models did not print remediation"
fi

suite_log "launch codex reports invalid /v1/models"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=unsloth-studio HARBOR_FAKE_CURL_MODE=invalid PATH="$launch_fake_bin:$PATH" harbor launch --backend unsloth-studio --config codex >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with invalid models unexpectedly succeeded"
fi
if ! grep -Eq -- "returned an invalid /v1/models response" /tmp/cli-step.out || ! grep -Eq -- 'pass a known model explicitly with --model <model>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with invalid models did not print remediation"
fi

suite_log "launch codex --model skips model discovery"
: >"$launch_fake_curl_log"
assert_ok "launch codex --model skips model discovery" env HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=ollama HARBOR_FAKE_CURL_MODE=invalid HARBOR_FAKE_CURL_LOG="$launch_fake_curl_log" PATH="$launch_fake_bin:$PATH" harbor launch --backend ollama --model explicit-model --config codex
if ! grep -Eq -- '^model=explicit-model$' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex --model did not use the explicit model"
fi
if [ "$(wc -l <"$launch_fake_curl_log" | tr -d ' ')" -ne 1 ]; then
  cat "$launch_fake_curl_log" >&2
  fail "launch codex --model called curl more than once"
fi
rm -rf "$launch_fake_bin" "$launch_fake_curl_log" "$launch_fake_docker_state"

# 8. Doctor — runs without bringing services up. requirements.sh-derived
#    checks (docker, compose v2 >= 2.23, git, curl) all pass against the
#    row image we built.
assert_ok    "harbor doctor"         harbor doctor

# 9. ps — lists harbor-prefixed containers; OK to be empty.
assert_ok    "harbor ps"             harbor ps

# 10. profile listing — exercises profiles/ walking.
assert_ok    "harbor profile ls"     harbor profile ls

# ---------------------------------------------------------------------------
# 11. llamacpp is a default service (v0.5.0)
#     The biggest user-facing change: `harbor up` with no args now starts
#     llamacpp alongside ollama and webui. Verify the shipped profile and
#     the live config both include it.
# ---------------------------------------------------------------------------
assert_match "default services include llamacpp (profile)" \
  'llamacpp' \
  grep 'HARBOR_SERVICES_DEFAULT' "$(harbor home)/profiles/default.env"

assert_match "default services include llamacpp (config)" \
  'llamacpp' \
  harbor config get services.default

assert_match "default services include ollama (profile)" \
  'ollama' \
  grep 'HARBOR_SERVICES_DEFAULT' "$(harbor home)/profiles/default.env"

assert_match "default services include webui (profile)" \
  'webui' \
  grep 'HARBOR_SERVICES_DEFAULT' "$(harbor home)/profiles/default.env"

# harbor cmd with no args should resolve the default services including llamacpp.
assert_match "harbor cmd (defaults) includes llamacpp compose" \
  'compose\.llamacpp\.yml' \
  harbor cmd

# ---------------------------------------------------------------------------
# 12. harbor volumes CLI round-trip (v0.5.0)
#     New CLI surface for managing custom host volume mounts per service.
#     Exercises add, ls, rm, clear without needing a running container.
# ---------------------------------------------------------------------------

# ls on a clean service should succeed (no volumes yet).
assert_ok "volumes ls ollama (initial)" harbor volumes ls ollama

# Add a volume mount and verify it shows up in ls.
assert_ok    "volumes add ollama /tmp/test-vol:/data" \
  harbor volumes add ollama /tmp/test-vol:/data
assert_match "volumes ls ollama (after add)" \
  '/tmp/test-vol:/data' \
  harbor volumes ls ollama

# Remove by index 0 and verify it's gone.
assert_ok "volumes rm ollama 0" harbor volumes rm ollama 0
suite_log "volumes ls ollama (after rm)"
harbor volumes ls ollama >/tmp/cli-step.out 2>&1 || true
if grep -Fq '/tmp/test-vol:/data' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "volumes rm did not remove the entry"
fi

# Add two, clear all, verify empty.
assert_ok "volumes add ollama /a:/b" harbor volumes add ollama /a:/b
assert_ok "volumes add ollama /c:/d" harbor volumes add ollama /c:/d
assert_match "volumes ls ollama (two entries)" '/a:/b' harbor volumes ls ollama
assert_ok    "volumes clear ollama" harbor volumes clear ollama

suite_log "volumes ls ollama (after clear)"
harbor volumes ls ollama >/tmp/cli-step.out 2>&1 || true
if grep -Fq '/a:/b' /tmp/cli-step.out || grep -Fq '/c:/d' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "volumes clear did not remove all entries"
fi

# ---------------------------------------------------------------------------
# 13. harbor doctor --check mode (v0.5.0)
#     CI/scripts use exit-code-only health check. In test rows, Docker and
#     Compose are available, so --check should pass (exit 0).
# ---------------------------------------------------------------------------
assert_match "harbor doctor --check passes" \
  'essential checks passed' \
  harbor doctor --check

# Plain doctor (already tested above in #8) also succeeds; --check is the
# new surface we need to validate produces machine-friendly exit codes.

# ---------------------------------------------------------------------------
# 14. harbor skills command (v0.5.0)
#     Agent-facing skill docs shipped with the CLI.
# ---------------------------------------------------------------------------

# List should find at least the built-in "harbor" skill.
assert_match "harbor skills list" 'harbor' harbor skills list

# Bare `harbor skills` is an alias for list.
assert_match "harbor skills (bare)" 'harbor' harbor skills

# Get a known skill — should output content.
assert_ok "harbor skills get harbor" harbor skills get harbor

# skills path should output a directory path.
assert_ok "harbor skills path" harbor skills path

# skills path <name> should also work for a known skill.
assert_match "harbor skills path harbor" 'harbor' harbor skills path harbor

# skills get of a nonexistent skill should fail.
suite_log "harbor skills get nonexistent (should fail)"
if harbor skills get nonexistent-skill-xyz >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor skills get nonexistent unexpectedly succeeded"
fi

# ---------------------------------------------------------------------------
# 15. New backend services compose validation (v0.5.0 — P0.7)
#     DMR, MLX, oMLX, and Daytona were added in this release. Their compose
#     files must exist and parse without errors.
# ---------------------------------------------------------------------------

# Compose files exist at the expected paths.
harbor_home="$(harbor home)"
for svc in dmr mlx omlx daytona; do
  suite_log "compose file exists: $svc"
  [ -f "$harbor_home/services/compose.${svc}.yml" ] \
    || fail "compose file missing: services/compose.${svc}.yml"
done

# harbor ls includes all four new services.
assert_match "harbor ls includes dmr"     '\bdmr\b'     harbor ls
assert_match "harbor ls includes mlx"     '\bmlx\b'     harbor ls
assert_match "harbor ls includes omlx"    '\bomlx\b'    harbor ls
assert_match "harbor ls includes daytona" '\bdaytona\b' harbor ls

# harbor cmd exits 0 for each (compose parses correctly).
assert_ok "harbor cmd dmr"     harbor cmd dmr
assert_ok "harbor cmd mlx"     harbor cmd mlx
assert_ok "harbor cmd omlx"    harbor cmd omlx
assert_ok "harbor cmd daytona" harbor cmd daytona

# ---------------------------------------------------------------------------
# 16. Cross-service integration file validity spot-checks (v0.5.0 — P0.8)
#     78+ new compose.x.<satellite>.<backend>.yml files were added for DMR,
#     MLX, oMLX, and llamacpp integrations. Validate a representative sample
#     of ~20 pairs by checking that `harbor cmd <satellite> <backend>` exits 0
#     (meaning all compose files — base + service + integration — parse).
# ---------------------------------------------------------------------------

# llamacpp integrations (now a default service — highest priority).
assert_ok "integration: webui + llamacpp"       harbor cmd webui llamacpp
assert_ok "integration: boost + llamacpp"       harbor cmd boost llamacpp
assert_ok "integration: aider + llamacpp"       harbor cmd aider llamacpp
assert_ok "integration: chatui + llamacpp"      harbor cmd chatui llamacpp
assert_ok "integration: hermes + llamacpp"      harbor cmd hermes llamacpp
assert_ok "integration: cognee + llamacpp"      harbor cmd cognee llamacpp
assert_ok "integration: openhands + llamacpp"   harbor cmd openhands llamacpp
assert_ok "integration: perplexica + llamacpp"  harbor cmd perplexica llamacpp
assert_ok "integration: lobechat + llamacpp"    harbor cmd lobechat llamacpp
assert_ok "integration: sillytavern + llamacpp" harbor cmd sillytavern llamacpp
assert_ok "integration: plandex + llamacpp"     harbor cmd plandex llamacpp
assert_ok "integration: promptfoo + llamacpp"   harbor cmd promptfoo llamacpp
assert_ok "integration: bifrost + llamacpp"     harbor cmd bifrost llamacpp

# DMR integrations.
assert_ok "integration: aider + dmr"    harbor cmd aider dmr
assert_ok "integration: boost + dmr"    harbor cmd boost dmr
assert_ok "integration: chatui + dmr"   harbor cmd chatui dmr
assert_ok "integration: hermes + dmr"   harbor cmd hermes dmr
assert_ok "integration: litellm + dmr"  harbor cmd litellm dmr

# MLX integrations.
assert_ok "integration: aider + mlx"   harbor cmd aider mlx
assert_ok "integration: chatui + mlx"  harbor cmd chatui mlx
assert_ok "integration: cognee + mlx"  harbor cmd cognee mlx

# oMLX integrations.
assert_ok "integration: aider + omlx"    harbor cmd aider omlx
assert_ok "integration: bifrost + omlx"  harbor cmd bifrost omlx
assert_ok "integration: boost + omlx"    harbor cmd boost omlx

# Cross-backend triple — satellite with two backends at once.
assert_ok "integration: aider + llamacpp + dmr" harbor cmd aider llamacpp dmr

rm -f /tmp/cli-step.out
suite_log "OK"
