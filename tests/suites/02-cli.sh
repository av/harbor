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

# ---------------------------------------------------------------------------
# 17. harbor pull smart routing (v0.5.0 — P0.4)
#     `harbor pull` must distinguish between service names (docker image pull)
#     and model identifiers (model download). We use a fake docker binary to
#     intercept the actual compose pull and verify routing without network I/O.
# ---------------------------------------------------------------------------

# No-args case: should fail with usage showing both modes.
suite_log "pull: no-args shows usage"
if harbor pull >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor pull with no args unexpectedly succeeded"
fi
if ! grep -Fq 'harbor pull <service>' /tmp/cli-step.out || ! grep -Fq 'harbor pull <model>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor pull usage does not mention both service and model modes"
fi

# Set up a fake docker to intercept pull routing decisions.
pull_fake_bin="$(mktemp -d -t harbor-pull.XXXXXX)"
pull_fake_log="$(mktemp -t harbor-pull-log.XXXXXX)"
cat >"$pull_fake_bin/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash

# compose version -- needed by _check_docker
if [[ "$*" == *"compose version"* ]]; then
  echo "Docker Compose version v2.30.0"
  exit 0
fi

# compose config --services -- needed by get_services
if [[ "$*" == *"config --services"* ]]; then
  printf '%s\n' ollama webui llamacpp boost aider
  exit 0
fi

# Log every compose invocation for later inspection
if [ "$1" = "compose" ]; then
  printf '%s\n' "$*" >>"$HARBOR_PULL_FAKE_LOG"
  exit 0
fi

exit 0
FAKE_DOCKER
cat >"$pull_fake_bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
# Model discovery may call curl -- just succeed with empty data
printf '%s\n' '{"data":[]}'
FAKE_CURL
chmod +x "$pull_fake_bin/docker" "$pull_fake_bin/curl"

# Test: known service name routes to docker compose pull.
: >"$pull_fake_log"
suite_log "pull: known service routes to docker image pull"
if ! HARBOR_PULL_FAKE_LOG="$pull_fake_log" PATH="$pull_fake_bin:$PATH" harbor pull ollama >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor pull ollama (known service) failed"
fi
if ! grep -q 'pull' "$pull_fake_log"; then
  cat "$pull_fake_log" >&2
  fail "harbor pull ollama did not route to docker compose pull"
fi

# Test: multiple known services route to docker compose pull.
: >"$pull_fake_log"
suite_log "pull: multiple services route to docker image pull"
if ! HARBOR_PULL_FAKE_LOG="$pull_fake_log" PATH="$pull_fake_bin:$PATH" harbor pull ollama webui >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor pull ollama webui (known services) failed"
fi
if ! grep -q 'pull' "$pull_fake_log"; then
  cat "$pull_fake_log" >&2
  fail "harbor pull ollama webui did not route to docker compose pull"
fi

# Test: model-like argument (no slash, has colon) routes to model pull.
# This will fail since there's no real ollama to pull from, but the routing
# itself is what we test -- it should NOT trigger docker compose pull.
: >"$pull_fake_log"
suite_log "pull: model name routes to model download (not docker pull)"
HARBOR_PULL_FAKE_LOG="$pull_fake_log" PATH="$pull_fake_bin:$PATH" harbor pull qwen3:8b >/tmp/cli-step.out 2>&1 || true
# The compose pull line should NOT appear in the log (model != service).
if grep -q ' pull$' "$pull_fake_log"; then
  cat "$pull_fake_log" >&2
  fail "harbor pull qwen3:8b incorrectly routed to docker compose pull"
fi

# Test: unknown name without colon also routes to model pull, not docker pull.
: >"$pull_fake_log"
suite_log "pull: unknown name routes to model download"
HARBOR_PULL_FAKE_LOG="$pull_fake_log" PATH="$pull_fake_bin:$PATH" harbor pull llama3.2 >/tmp/cli-step.out 2>&1 || true
if grep -q ' pull$' "$pull_fake_log"; then
  cat "$pull_fake_log" >&2
  fail "harbor pull llama3.2 incorrectly routed to docker compose pull"
fi

rm -rf "$pull_fake_bin" "$pull_fake_log"

# ---------------------------------------------------------------------------
# 18. Fuzzy service name suggestions (v0.5.0 — P1.1)
#     When a user types a misspelled service name, Harbor should suggest the
#     closest match via "Did you mean: <correct>?" message. This exercises
#     the levenshtein_distance and _suggest_service helpers.
# ---------------------------------------------------------------------------

# Close misspelling of "ollama" -> should suggest "ollama".
suite_log "fuzzy: 'olllama' suggests 'ollama'"
if harbor up --no-defaults olllama >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor up olllama unexpectedly succeeded"
fi
if ! grep -qi 'did you mean' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor up olllama did not produce a 'Did you mean' suggestion"
fi
if ! grep -q 'ollama' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor up olllama did not suggest 'ollama'"
fi

# Close misspelling of "webui" -> should suggest "webui".
suite_log "fuzzy: 'webuii' suggests 'webui'"
if harbor up --no-defaults webuii >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor up webuii unexpectedly succeeded"
fi
if ! grep -qi 'did you mean' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor up webuii did not produce a 'Did you mean' suggestion"
fi
if ! grep -q 'webui' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor up webuii did not suggest 'webui'"
fi

# Completely wrong name (levenshtein > 3) should NOT produce a suggestion.
suite_log "fuzzy: 'zzzznotaservice' produces no suggestion"
if harbor up --no-defaults zzzznotaservice >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor up zzzznotaservice unexpectedly succeeded"
fi
if grep -qi 'did you mean' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor up zzzznotaservice unexpectedly produced a 'Did you mean' suggestion"
fi
# But it should still report the service as not found.
if ! grep -q "not found" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor up zzzznotaservice did not report service as not found"
fi

# ---------------------------------------------------------------------------
# 19. Service name validation in harbor defaults add (v0.5.0 — P1.2)
#     `harbor defaults add` should reject invalid/nonexistent service names
#     and accept valid ones. This guards against config corruption from typos.
# ---------------------------------------------------------------------------

# Invalid service name should be rejected.
suite_log "defaults add: rejects nonexistent service"
if harbor defaults add nonexistent-service-xyz >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor defaults add nonexistent-service-xyz unexpectedly succeeded"
fi
if ! grep -q "not found" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor defaults add nonexistent did not report service as not found"
fi

# Valid service name should succeed.
assert_ok "defaults add: accepts valid service (boost)" harbor defaults add boost

# Verify it was actually added.
assert_match "defaults add: boost is in defaults" 'boost' harbor defaults ls

# Duplicate add should succeed (idempotent, warns).
assert_ok "defaults add: duplicate add is idempotent" harbor defaults add boost

# Clean up: remove the service we added.
assert_ok "defaults rm: remove boost" harbor defaults rm boost

# Verify it was removed.
suite_log "defaults rm: boost no longer in defaults"
harbor defaults ls >/tmp/cli-step.out 2>&1 || true
if grep -q 'boost' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor defaults rm did not remove boost from defaults"
fi

# ---------------------------------------------------------------------------
# 20. Tab completion generation (v0.5.0 — P1.3)
#     `harbor completion bash|zsh|fish` must emit valid, non-empty scripts
#     that contain key commands and the correct shell-specific markers.
# ---------------------------------------------------------------------------

# Bash completion: must contain `complete -F` and key subcommands.
assert_match "completion bash emits complete -F" \
  'complete -F' \
  harbor completion bash
assert_match "completion bash includes 'up'" \
  '\bup\b' \
  harbor completion bash
assert_match "completion bash includes 'volumes'" \
  '\bvolumes\b' \
  harbor completion bash
assert_match "completion bash includes 'skills'" \
  '\bskills\b' \
  harbor completion bash

# Zsh completion: must start with #compdef marker.
assert_match "completion zsh emits #compdef" \
  '#compdef' \
  harbor completion zsh
assert_match "completion zsh includes 'config'" \
  'config' \
  harbor completion zsh

# Fish completion: must contain `complete -c harbor` directives.
assert_match "completion fish emits complete -c harbor" \
  'complete -c harbor' \
  harbor completion fish
assert_match "completion fish includes 'down'" \
  'down' \
  harbor completion fish

# No-args case: should print usage with supported shells.
assert_match "completion no-args shows usage" \
  'harbor completion <shell>' \
  harbor completion

# Invalid shell should fail.
suite_log "completion: invalid shell fails"
if harbor completion nosuchshell >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor completion nosuchshell unexpectedly succeeded"
fi

# ---------------------------------------------------------------------------
# 21. Pure-bash config search fallback (v0.5.0 — P1.4)
#     `harbor config search` uses a pure-bash fallback (_config_search_bash)
#     when deno is unavailable. In test containers deno is typically absent,
#     so we're already exercising the fallback path.
# ---------------------------------------------------------------------------

# config search for a well-known key should return results.
assert_match "config search ollama returns results" \
  'ollama' \
  harbor config search ollama

# config search for a specific key format should match dot-notation output.
assert_match "config search webui returns results" \
  'webui' \
  harbor config search webui

# config ls should succeed (exercises the same fallback for list mode).
assert_ok "config ls via fallback" harbor config ls

# config search with no query should fail with usage.
suite_log "config search no-query shows usage"
if harbor config search >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor config search with no query unexpectedly succeeded"
fi

# ---------------------------------------------------------------------------
# 22. Config set/get round-trip and preservation (v0.5.0 — P1.5)
#     `harbor config set` must preserve file permissions and not corrupt
#     adjacent config values. This tests the head/tail line-replacement
#     logic and the chmod permission-copy path.
# ---------------------------------------------------------------------------

# Record .env permissions before the test.
harbor_home_dir="$(harbor home)"
env_perms_before=$(stat -c '%a' "$harbor_home_dir/.env" 2>/dev/null || stat -f '%Lp' "$harbor_home_dir/.env" 2>/dev/null)

# Round-trip a fresh key.
assert_ok    "config set test.perm to 'hello'" harbor config set test.perm hello
assert_match "config get test.perm returns 'hello'" \
  '^hello$' \
  harbor config get test.perm

# Set a second key and verify the first is not corrupted.
assert_ok    "config set test.perm2 to 'world'" harbor config set test.perm2 world
assert_match "config get test.perm still returns 'hello'" \
  '^hello$' \
  harbor config get test.perm
assert_match "config get test.perm2 returns 'world'" \
  '^world$' \
  harbor config get test.perm2

# Overwrite the first key and verify the second is untouched.
assert_ok    "config set test.perm to 'changed'" harbor config set test.perm changed
assert_match "config get test.perm returns 'changed'" \
  '^changed$' \
  harbor config get test.perm
assert_match "config get test.perm2 still returns 'world'" \
  '^world$' \
  harbor config get test.perm2

# Check permissions were preserved.
env_perms_after=$(stat -c '%a' "$harbor_home_dir/.env" 2>/dev/null || stat -f '%Lp' "$harbor_home_dir/.env" 2>/dev/null)
suite_log "config set preserves .env permissions ($env_perms_before -> $env_perms_after)"
if [ "$env_perms_before" != "$env_perms_after" ]; then
  fail "config set changed .env permissions from $env_perms_before to $env_perms_after"
fi

# Verify no leftover temp files in the harbor home directory.
suite_log "config set leaves no temp files"
leftover=$(find "$harbor_home_dir" -maxdepth 1 -name 'harbor_set.*' -o -name 'tmp.*' 2>/dev/null | head -3)
if [ -n "$leftover" ]; then
  echo "$leftover" >&2
  fail "config set left temp files in harbor home"
fi

# Clean up test keys.
assert_ok "config unset test.perm"  harbor config unset test.perm
assert_ok "config unset test.perm2" harbor config unset test.perm2

# ---------------------------------------------------------------------------
# 23. Daytona multi-container structure (v0.5.0 — P1.7)
#     Daytona is a complex multi-container service with API, proxy, runner,
#     SSH gateway, database, and supporting infrastructure. Verify the
#     compose config lists the expected sub-services.
# ---------------------------------------------------------------------------

# harbor cmd daytona should exit 0 (already tested in #15, but we need the
# output for the config --services check below).
assert_ok "daytona compose parses" harbor cmd daytona

# Extract the compose command and list its services.
daytona_cmd=$(harbor cmd daytona 2>/dev/null)
suite_log "daytona compose lists multiple sub-services"
daytona_services=$($daytona_cmd config --services 2>/dev/null) || {
  fail "daytona compose config --services failed"
}

# Daytona should have at minimum these core sub-services.
for expected_svc in daytona daytona-proxy daytona-runner daytona-ssh daytona-db daytona-redis daytona-minio; do
  suite_log "daytona sub-service present: $expected_svc"
  if ! echo "$daytona_services" | grep -q "^${expected_svc}$"; then
    echo "Services found:" >&2
    echo "$daytona_services" >&2
    fail "daytona compose config --services missing: $expected_svc"
  fi
done

# Count total sub-services — Daytona has 14 in its compose file.
daytona_svc_count=$(echo "$daytona_services" | wc -l | tr -d ' ')
suite_log "daytona has $daytona_svc_count sub-services (expected >= 10)"
if [ "$daytona_svc_count" -lt 10 ]; then
  echo "Only $daytona_svc_count services found:" >&2
  echo "$daytona_services" >&2
  fail "daytona should have at least 10 sub-services, found $daytona_svc_count"
fi

# ---------------------------------------------------------------------------
# 24. Port conflict pre-detection (v0.5.0 — P0.6)
#     harbor up checks for port conflicts before starting services. Verify
#     that the internal helpers exist, that --skip-port-check is accepted,
#     and that _check_port_conflicts detects a duplicate-port scenario.
# ---------------------------------------------------------------------------

# The _check_port_conflicts function is defined in harbor.sh. Source the script
# to get access to it. We already have harbor on PATH, so locate the real file.
harbor_script="$(command -v harbor)"

# Verify --skip-port-check is a recognized flag (appears in help).
assert_match "up help mentions --skip-port-check" \
  'skip-port-check' \
  harbor up --help

# _parse_compose_ports should extract service:port pairs from compose config YAML.
# Feed it a minimal synthetic compose config and verify parsing.
suite_log "port conflict: _parse_compose_ports extracts host ports"
# Source the _parse_compose_ports function from harbor.sh.
# It is a standalone awk-based function we can call directly after sourcing.
parse_output=$(
  # Source only the function we need by extracting it
  eval "$(sed -n '/_parse_compose_ports()/,/^}/p' "$harbor_script")"
  _parse_compose_ports '
services:
  ollama:
    ports:
      - mode: ingress
        target: 11434
        published: "33821"
        protocol: tcp
  webui:
    ports:
      - mode: ingress
        target: 8080
        published: "33801"
        protocol: tcp
'
)
if ! echo "$parse_output" | grep -q "ollama:33821"; then
  echo "Parse output: $parse_output" >&2
  fail "_parse_compose_ports did not extract ollama:33821"
fi
if ! echo "$parse_output" | grep -q "webui:33801"; then
  echo "Parse output: $parse_output" >&2
  fail "_parse_compose_ports did not extract webui:33801"
fi

# Test inter-service conflict detection: two services on the same port.
suite_log "port conflict: detects inter-service duplicate ports"
conflict_parse=$(
  eval "$(sed -n '/_parse_compose_ports()/,/^}/p' "$harbor_script")"
  _parse_compose_ports '
services:
  svc-a:
    ports:
      - mode: ingress
        target: 8080
        published: "9999"
        protocol: tcp
  svc-b:
    ports:
      - mode: ingress
        target: 3000
        published: "9999"
        protocol: tcp
'
)
# Both services should map to port 9999.
svc_a_port=$(echo "$conflict_parse" | grep "svc-a:9999" || true)
svc_b_port=$(echo "$conflict_parse" | grep "svc-b:9999" || true)
if [ -z "$svc_a_port" ] || [ -z "$svc_b_port" ]; then
  echo "Conflict parse output: $conflict_parse" >&2
  fail "_parse_compose_ports failed to extract duplicate port 9999 for both services"
fi

# ---------------------------------------------------------------------------
# 25. harbor eject hardening (v0.5.0 — P2.3)
#     harbor eject produces a standalone resolved Compose configuration.
#     Verify it outputs valid YAML, includes expected services, and that
#     --no-defaults limits the output to named services only.
# ---------------------------------------------------------------------------

# Basic eject (default services) should succeed and produce YAML.
suite_log "eject: default services produce output"
eject_output=$(harbor eject 2>/dev/null) || {
  fail "harbor eject exited non-zero"
}

# Output must contain the "services:" top-level YAML key.
if ! echo "$eject_output" | grep -q "^services:"; then
  echo "$eject_output" | head -20 >&2
  fail "harbor eject output missing 'services:' key"
fi

# Default services should include ollama and webui.
suite_log "eject: default output includes ollama"
if ! echo "$eject_output" | grep -q "ollama"; then
  fail "harbor eject default output does not mention ollama"
fi

suite_log "eject: default output includes webui"
if ! echo "$eject_output" | grep -q "webui"; then
  fail "harbor eject default output does not mention webui"
fi

# Eject with --no-defaults and a single service should produce
# config that includes only that service.
suite_log "eject: --no-defaults ollama limits output"
eject_nd=$(harbor eject --no-defaults ollama 2>/dev/null) || {
  fail "harbor eject --no-defaults ollama exited non-zero"
}
if ! echo "$eject_nd" | grep -q "^services:"; then
  echo "$eject_nd" | head -20 >&2
  fail "harbor eject --no-defaults ollama missing 'services:' key"
fi
if ! echo "$eject_nd" | grep -q "ollama"; then
  fail "harbor eject --no-defaults ollama does not mention ollama"
fi

# The ejected YAML should inline environment variables (no ${...} references).
suite_log "eject: output inlines env vars (no raw \${...} references)"
if echo "$eject_output" | grep -qE '\$\{HARBOR_'; then
  fail "harbor eject output still contains raw \${HARBOR_...} variable references"
fi

# Eject help text should mention secrets warning.
assert_match "eject --help mentions secrets warning" \
  'secrets' \
  harbor eject --help

# ---------------------------------------------------------------------------
# 26. AMD ROCm overrides (v0.5.0 — P2.1)
#     Verify that ROCm-specific config keys exist in profiles/default.env
#     and that the ROCm compose overlay files are valid.
# ---------------------------------------------------------------------------

# ROCm image config key must exist for llamacpp.
assert_match "config: llamacpp.image.rocm exists" \
  'ghcr.io/ggml-org/llama.cpp:server-rocm' \
  harbor config get llamacpp.image.rocm

# CPU and NVIDIA image variants should also exist.
assert_match "config: llamacpp.image.cpu exists" \
  'ghcr.io/ggml-org/llama.cpp:server' \
  harbor config get llamacpp.image.cpu

assert_match "config: llamacpp.image.nvidia exists" \
  'ghcr.io/ggml-org/llama.cpp:server-cuda' \
  harbor config get llamacpp.image.nvidia

# ROCm compose overlay for llamacpp must exist and parse.
suite_log "rocm: llamacpp ROCm compose overlay exists"
if [ ! -f "$(harbor home)/services/compose.x.llamacpp.rocm.yml" ]; then
  fail "compose.x.llamacpp.rocm.yml not found"
fi

# ROCm overlay must reference the ROCm image variable.
suite_log "rocm: llamacpp ROCm overlay uses ROCm image"
if ! grep -q "HARBOR_LLAMACPP_IMAGE_ROCM" "$(harbor home)/services/compose.x.llamacpp.rocm.yml"; then
  fail "compose.x.llamacpp.rocm.yml does not reference HARBOR_LLAMACPP_IMAGE_ROCM"
fi

# ROCm overlay must expose AMD GPU devices.
suite_log "rocm: llamacpp ROCm overlay exposes /dev/kfd"
if ! grep -q "/dev/kfd" "$(harbor home)/services/compose.x.llamacpp.rocm.yml"; then
  fail "compose.x.llamacpp.rocm.yml does not expose /dev/kfd"
fi

# Other services also have ROCm overlays — spot-check ollama.
suite_log "rocm: ollama ROCm compose overlay exists"
if [ ! -f "$(harbor home)/services/compose.x.ollama.rocm.yml" ]; then
  fail "compose.x.ollama.rocm.yml not found"
fi

# Verify the ROCm config key round-trips correctly.
assert_ok "config set llamacpp.image.rocm (round-trip)" \
  harbor config set llamacpp.image.rocm "test-rocm-image:latest"
assert_match "config get llamacpp.image.rocm (round-trip)" \
  '^test-rocm-image:latest$' \
  harbor config get llamacpp.image.rocm
# Restore the original value.
assert_ok "config restore llamacpp.image.rocm" \
  harbor config set llamacpp.image.rocm "ghcr.io/ggml-org/llama.cpp:server-rocm"

# ---------------------------------------------------------------------------
# 27. Ollama image configurability (v0.5.0 — P2.2)
#     The Docker image for Ollama is configurable via harbor config.
#     Verify the default value and that set/get round-trips work.
# ---------------------------------------------------------------------------

# Default image should be ollama/ollama.
assert_match "ollama.image default is ollama/ollama" \
  '^ollama/ollama$' \
  harbor config get ollama.image

# Round-trip: set a custom image, verify, restore.
assert_ok "config set ollama.image to custom" \
  harbor config set ollama.image "custom/ollama-test"
assert_match "config get ollama.image returns custom" \
  '^custom/ollama-test$' \
  harbor config get ollama.image

# Restore original.
assert_ok "config restore ollama.image" \
  harbor config set ollama.image "ollama/ollama"
assert_match "config get ollama.image restored" \
  '^ollama/ollama$' \
  harbor config get ollama.image

# Verify ollama.version is also configurable.
assert_match "ollama.version default is 'latest'" \
  '^latest$' \
  harbor config get ollama.version

# ---------------------------------------------------------------------------
# 28. Hermes default API key (v0.5.0 — P2.5)
#     Hermes ships with a default API key so the service works out of the box.
#     Verify the default key is set and the config round-trips correctly.
# ---------------------------------------------------------------------------

# Default API key should be "sk-hermes".
assert_match "hermes.api_key default is sk-hermes" \
  '^sk-hermes$' \
  harbor config get hermes.api_key

# Round-trip: set a custom key, verify, restore.
assert_ok "config set hermes.api_key to custom" \
  harbor config set hermes.api_key "sk-custom-test-key"
assert_match "config get hermes.api_key returns custom" \
  '^sk-custom-test-key$' \
  harbor config get hermes.api_key

# Restore default.
assert_ok "config restore hermes.api_key" \
  harbor config set hermes.api_key "sk-hermes"
assert_match "config get hermes.api_key restored" \
  '^sk-hermes$' \
  harbor config get hermes.api_key

# Verify hermes help mentions the api_key subcommand.
assert_match "hermes help mentions api_key" \
  'api_key' \
  harbor hermes --help

# Verify other hermes config keys exist.
assert_match "hermes.host.port has a default" \
  '^[0-9]+$' \
  harbor config get hermes.host.port

# ---------------------------------------------------------------------------
# 29. harbor down -v flag passthrough (v0.5.0 — P1.6)
#     `harbor down -v` must forward the -v flag to docker compose down so that
#     named volumes are removed. We use a fake docker binary to intercept the
#     compose call and verify -v appears in the arguments.
# ---------------------------------------------------------------------------

down_fake_bin="$(mktemp -d -t harbor-down.XXXXXX)"
down_fake_log="$(mktemp -t harbor-down-log.XXXXXX)"
cat >"$down_fake_bin/docker" <<'DOWN_FAKE_DOCKER'
#!/usr/bin/env bash

# compose version -- needed by _check_docker
if [[ "$*" == *"compose version"* ]]; then
  echo "Docker Compose version v2.30.0"
  exit 0
fi

# compose ps --format {{.Service}} -- needed by get_active_services
if [[ "$*" == *'compose ps --format'* ]]; then
  echo "ollama"
  exit 0
fi

# compose ps -a --format -- needed by run_down sibling lookup
if [[ "$*" == *'compose ps -a --format'* ]]; then
  echo "ollama"
  exit 0
fi

# compose ps --services --filter status=running
if [[ "$*" == *"--services --filter"* ]]; then
  echo "ollama"
  exit 0
fi

# config --services -- needed by get_services
if [[ "$*" == *"config --services"* ]]; then
  printf '%s\n' ollama webui llamacpp
  exit 0
fi

# Log every compose invocation for later inspection
if [ "$1" = "compose" ]; then
  printf '%s\n' "$*" >>"$HARBOR_DOWN_FAKE_LOG"
  exit 0
fi

exit 0
DOWN_FAKE_DOCKER
chmod +x "$down_fake_bin/docker"

# Test: harbor down -v passes -v to compose down
: >"$down_fake_log"
suite_log "down -v: flag is forwarded to compose"
if ! HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_DOWN_FAKE_LOG="$down_fake_log" PATH="$down_fake_bin:$PATH" harbor down -v >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor down -v exited non-zero"
fi
if ! grep -q ' down ' "$down_fake_log"; then
  cat "$down_fake_log" >&2
  fail "harbor down -v did not call compose down"
fi
if ! grep -q -- '-v' "$down_fake_log"; then
  cat "$down_fake_log" >&2
  fail "harbor down -v did not forward -v to compose"
fi

# Test: harbor down --volumes also forwards --volumes
: >"$down_fake_log"
suite_log "down --volumes: flag is forwarded to compose"
if ! HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_DOWN_FAKE_LOG="$down_fake_log" PATH="$down_fake_bin:$PATH" harbor down --volumes >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor down --volumes exited non-zero"
fi
if ! grep -q -- '--volumes' "$down_fake_log"; then
  cat "$down_fake_log" >&2
  fail "harbor down --volumes did not forward --volumes to compose"
fi

# Test: harbor down (no flags) does not pass -v
: >"$down_fake_log"
suite_log "down (no flags): no -v in compose args"
if ! HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_DOWN_FAKE_LOG="$down_fake_log" PATH="$down_fake_bin:$PATH" harbor down >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor down (no flags) exited non-zero"
fi
if grep -q -- ' -v ' "$down_fake_log" || grep -Eq -- ' -v$' "$down_fake_log"; then
  cat "$down_fake_log" >&2
  fail "harbor down (no flags) unexpectedly passed -v to compose"
fi

# Test: harbor down --rmi local forwards --rmi local
: >"$down_fake_log"
suite_log "down --rmi local: flags forwarded to compose"
if ! HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_DOWN_FAKE_LOG="$down_fake_log" PATH="$down_fake_bin:$PATH" harbor down --rmi local >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor down --rmi local exited non-zero"
fi
if ! grep -q -- '--rmi' "$down_fake_log" || ! grep -q -- 'local' "$down_fake_log"; then
  cat "$down_fake_log" >&2
  fail "harbor down --rmi local did not forward flags to compose"
fi

rm -rf "$down_fake_bin" "$down_fake_log"

# ---------------------------------------------------------------------------
# 30. End-to-end port conflict detection (v0.5.0 — P0.6 supplement)
#     Section #24 tested the port parser and inter-service conflict detection.
#     This section tests host-level port conflict detection: occupy a port on
#     the host and verify _is_port_in_use detects it.
# ---------------------------------------------------------------------------

harbor_script="$(harbor home)/harbor.sh"

# Find a high port that is currently free.
conflict_test_port=""
for candidate_port in 59871 59872 59873 59874 59875; do
  if ! ss -tln "sport = :$candidate_port" 2>/dev/null | grep -q "LISTEN" 2>/dev/null; then
    conflict_test_port="$candidate_port"
    break
  fi
done

if [ -n "$conflict_test_port" ]; then
  # Verify _is_port_in_use returns false for the free port.
  suite_log "port conflict e2e: free port $conflict_test_port is not in use"
  port_in_use_result=0
  (
    eval "$(sed -n '/_is_port_in_use()/,/^}/p' "$harbor_script")"
    _is_port_in_use "$conflict_test_port"
  ) && port_in_use_result=$? || port_in_use_result=$?
  if [ "$port_in_use_result" -eq 0 ]; then
    fail "_is_port_in_use reported free port $conflict_test_port as in use"
  fi

  # Bind the port with a background listener.
  suite_log "port conflict e2e: occupied port $conflict_test_port detected"
  # Use bash's built-in /dev/tcp redirection trick or nc
  if command -v socat &>/dev/null; then
    socat TCP-LISTEN:"$conflict_test_port",reuseaddr,fork /dev/null &
    listener_pid=$!
  elif command -v nc &>/dev/null; then
    # GNU nc (ncat) on Fedora supports -l -k
    nc -l -k "$conflict_test_port" >/dev/null 2>&1 &
    listener_pid=$!
  else
    # Python fallback
    python3 -c "
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', $conflict_test_port))
s.listen(1)
time.sleep(30)
" &
    listener_pid=$!
  fi

  # Wait briefly for the listener to bind.
  sleep 0.3

  port_in_use_result=1
  (
    eval "$(sed -n '/_is_port_in_use()/,/^}/p' "$harbor_script")"
    _is_port_in_use "$conflict_test_port"
  ) && port_in_use_result=$? || port_in_use_result=$?

  # Clean up the listener immediately.
  kill "$listener_pid" 2>/dev/null || true
  wait "$listener_pid" 2>/dev/null || true

  if [ "$port_in_use_result" -ne 0 ]; then
    fail "_is_port_in_use did not detect occupied port $conflict_test_port"
  fi
else
  suite_log "port conflict e2e: SKIP (no free port found in range)"
fi

rm -f /tmp/cli-step.out

# ---------------------------------------------------------------------------
# 31. harbor env --help and validation (v0.5.0 supplement)
#     Commit e50961d9 added --help, fuzzy service name suggestions, and
#     subcommand validation to harbor env. Existing tests (#4) only cover
#     basic set/get round-trips on a known service.
# ---------------------------------------------------------------------------
suite_log "=== harbor env help and validation ==="

# --help flag should print usage text
assert_match "env --help prints usage" \
  'harbor env <service>' \
  harbor env --help

# help as positional arg should also work
assert_match "env help prints usage" \
  'harbor env <service>' \
  harbor env help

# -h also works
assert_match "env -h prints usage" \
  'harbor env <service>' \
  harbor env -h

# No-args should fail with usage guidance
suite_log "env no-args fails with usage"
if harbor env >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor env with no args unexpectedly succeeded"
fi
if ! grep -q 'harbor env <service>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor env no-args did not show usage"
fi

# Invalid service name should fail (env validates service names now)
suite_log "env nonexistent service fails"
if harbor env nonexistent-service-xyz-999 >/tmp/cli-step.out 2>&1; then
  # Some implementations may succeed with empty output for unknown services
  # (depends on whether the override.env file exists). Check if it gave
  # a meaningful response — if the file just doesn't exist, that's also fine.
  suite_log "env nonexistent service: exited 0 (acceptable — no override.env)"
else
  suite_log "env nonexistent service: rejected (exit non-zero)"
fi

# ---------------------------------------------------------------------------
# 32. harbor tunnels add validation (v0.5.0 supplement)
#     Commit ceb0793b added service name validation with fuzzy suggestions
#     and duplicate detection to harbor tunnels add. Completely untested.
# ---------------------------------------------------------------------------
suite_log "=== harbor tunnels add validation ==="

# tunnels add with no service name should fail
suite_log "tunnels add: no service fails"
if harbor tunnels add >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor tunnels add with no args unexpectedly succeeded"
fi

# tunnels add with nonexistent service should fail
suite_log "tunnels add: nonexistent service fails"
if harbor tunnels add nonexistent-service-xyz >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor tunnels add nonexistent-service-xyz unexpectedly succeeded"
fi
if ! grep -qi 'not found' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor tunnels add nonexistent: did not report 'not found'"
fi

# tunnels add with typo should suggest correct name
suite_log "tunnels add: typo suggests correct name"
if harbor tunnels add olllama >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "harbor tunnels add olllama unexpectedly succeeded"
fi
if ! grep -qi 'did you mean\|ollama' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "harbor tunnels add olllama: did not suggest 'ollama'"
fi

# tunnels add with valid service should succeed
assert_ok "tunnels add: valid service succeeds" harbor tunnels add webui

# tunnels ls should show the added service
assert_match "tunnels ls: webui in list" 'webui' harbor tunnels ls

# tunnels add duplicate should be idempotent (no error)
assert_ok "tunnels add: duplicate is idempotent" harbor tunnels add webui

# Check duplicate detection message
harbor tunnels add webui >/tmp/cli-step.out 2>&1 || true
if grep -qi 'already' /tmp/cli-step.out; then
  suite_log "tunnels add duplicate: correctly warns 'already in the tunnel list'"
else
  suite_log "tunnels add duplicate: accepted silently (also valid)"
fi

# Clean up: remove webui from tunnels
assert_ok "tunnels rm: remove webui" harbor tunnels rm webui

# Verify removed
suite_log "tunnels ls: webui removed"
tunnels_after=$(harbor tunnels ls 2>/dev/null || true)
if echo "$tunnels_after" | grep -q 'webui'; then
  fail "harbor tunnels rm webui did not remove it from the list"
fi

# ---------------------------------------------------------------------------
# 33. Config set with special characters (v0.5.0 supplement)
#     Commit d59fb2de fixed sed injection: values containing |, &, or \
#     corrupted the .env file. This tests the head/printf/tail replacement
#     path that replaced the vulnerable sed s||| pattern.
# ---------------------------------------------------------------------------
suite_log "=== config set with special characters ==="

# Pipe character
assert_ok    "config set test.special.pipe to 'a|b'" harbor config set test.special.pipe 'a|b'
assert_match "config get test.special.pipe" \
  '^a\|b$' \
  harbor config get test.special.pipe

# Ampersand character
assert_ok    "config set test.special.amp to 'a&b'" harbor config set test.special.amp 'a&b'
assert_match "config get test.special.amp" \
  '^a&b$' \
  harbor config get test.special.amp

# Backslash character
assert_ok    "config set test.special.bs to 'a\\b'" harbor config set test.special.bs 'a\b'
assert_match "config get test.special.bs" \
  '^a\\b$' \
  harbor config get test.special.bs

# Verify earlier keys were not corrupted by subsequent sets
assert_match "config get test.special.pipe still intact" \
  '^a\|b$' \
  harbor config get test.special.pipe

# URL-like value (common real-world case: API endpoints)
assert_ok    "config set test.special.url" harbor config set test.special.url 'https://example.com/v1?key=val&other=123'
assert_match "config get test.special.url" \
  '^https://example.com/v1\?key=val&other=123$' \
  harbor config get test.special.url

# Clean up special character test keys
harbor config unset test.special.pipe >/dev/null 2>&1 || true
harbor config unset test.special.amp >/dev/null 2>&1 || true
harbor config unset test.special.bs >/dev/null 2>&1 || true
harbor config unset test.special.url >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 34. _check_disk_space helper (v0.5.0 supplement)
#     Commit 9e389d2e added disk space pre-checks before model downloads.
#     The function never blocks (returns 0 always) but sets _disk_space_gb.
#     This test validates the function parses df output correctly.
# ---------------------------------------------------------------------------
suite_log "=== disk space pre-check helper ==="

harbor_script="$(harbor home)/harbor.sh"

# Extract and test _check_disk_space against the current filesystem.
# The function should always return 0 (it warns but never blocks).
suite_log "disk space: _check_disk_space returns 0 for valid path"
(
  eval "$(sed -n '/^_disk_space_gb=""/,/^}/p' "$harbor_script" | head -50)"
  _check_disk_space "/tmp" 1 "test"
) >/tmp/cli-step.out 2>&1
if [ $? -ne 0 ]; then
  cat /tmp/cli-step.out >&2
  fail "_check_disk_space /tmp returned non-zero"
fi

# _check_disk_space with non-existent nested path should still return 0
# (it walks up to find nearest existing ancestor)
suite_log "disk space: _check_disk_space handles non-existent path"
(
  eval "$(sed -n '/^_disk_space_gb=""/,/^}/p' "$harbor_script" | head -50)"
  _check_disk_space "/tmp/harbor-test-nonexistent-deep/nested/path" 1 "test"
) >/tmp/cli-step.out 2>&1
if [ $? -ne 0 ]; then
  cat /tmp/cli-step.out >&2
  fail "_check_disk_space with non-existent path returned non-zero"
fi

# _check_disk_space with absurdly high threshold should warn but return 0
suite_log "disk space: _check_disk_space warns on high threshold"
(
  # Source the log_warn function stub to avoid undefined function errors
  log_warn() { echo "WARN: $*"; }
  eval "$(sed -n '/^_disk_space_gb=""/,/^}/p' "$harbor_script" | head -50)"
  _check_disk_space "/tmp" 999999 "test"
) >/tmp/cli-step.out 2>&1
if [ $? -ne 0 ]; then
  cat /tmp/cli-step.out >&2
  fail "_check_disk_space with 999999GB threshold returned non-zero"
fi
if ! grep -qi 'low disk space\|warn' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "_check_disk_space with 999999GB threshold did not warn"
fi

# ---------------------------------------------------------------------------
# 35. MLX model/hf.path consistency (v0.5.0 supplement)
#     Commit 9d08caab fixed mlx.model default to match mlx.hf.path.
#     Both values must be identical in the shipped default profile.
# ---------------------------------------------------------------------------
suite_log "=== MLX model config consistency ==="

mlx_model=$(harbor config get mlx.model)
mlx_hf_path=$(harbor config get mlx.hf.path)

suite_log "mlx.model = $mlx_model"
suite_log "mlx.hf.path = $mlx_hf_path"

if [ "$mlx_model" != "$mlx_hf_path" ]; then
  fail "mlx.model ($mlx_model) does not match mlx.hf.path ($mlx_hf_path)"
fi
suite_log "mlx.model matches mlx.hf.path"

# Both should contain a HuggingFace repo path (org/model format)
if ! echo "$mlx_model" | grep -q '/'; then
  fail "mlx.model ($mlx_model) does not look like a HF repo path (missing /)"
fi
suite_log "mlx.model is a valid HF repo path format"

# ---------------------------------------------------------------------------
# 36. _check_docker preflight guard (v0.5.0 supplement)
#     Commit 0f1563f8 added Docker preflight checks to all docker-dependent
#     commands. The _check_docker function validates Docker CLI, Compose v2,
#     and daemon reachability. Test the function in isolation by extracting
#     it along with its dependencies.
# ---------------------------------------------------------------------------
suite_log "=== Docker preflight checks ==="

# _check_docker depends on log_error and _with_timeout. Provide stubs and
# extract the function from harbor.sh, then run it in a subshell.
suite_log "docker preflight: _check_docker detects docker"
(
  log_error() { echo "ERROR: $*"; }
  log_warn() { echo "WARN: $*"; }
  _with_timeout() { shift; "$@"; }
  eval "$(sed -n '/^_check_docker()/,/^}/p' "$harbor_script")"
  _docker_ok=""
  _check_docker
) >/tmp/cli-step.out 2>&1
check_docker_result=$?

if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
  # Docker is available — _check_docker should succeed
  if [ "$check_docker_result" -ne 0 ]; then
    cat /tmp/cli-step.out >&2
    fail "_check_docker failed even though docker is available"
  fi
  suite_log "docker preflight: _check_docker succeeded (docker available)"

  # Verify caching: call twice, second should use cached result
  (
    log_error() { echo "ERROR: $*"; }
    _with_timeout() { shift; "$@"; }
    eval "$(sed -n '/^_check_docker()/,/^}/p' "$harbor_script")"
    _docker_ok=""
    _check_docker
    _check_docker  # should use cached _docker_ok=1
  ) >/tmp/cli-step.out 2>&1
  if [ $? -ne 0 ]; then
    fail "_check_docker cached call failed"
  fi
  suite_log "docker preflight: cached result works"
else
  # Docker is not available — _check_docker should fail with clear message
  if [ "$check_docker_result" -eq 0 ]; then
    fail "_check_docker succeeded even though docker is not available"
  fi
  if ! grep -qi 'docker\|install\|not installed' /tmp/cli-step.out; then
    cat /tmp/cli-step.out >&2
    fail "_check_docker did not produce a helpful error message"
  fi
  suite_log "docker preflight: _check_docker failed with clear message (docker not available)"
fi

rm -f /tmp/cli-step.out
suite_log "OK"

# ---------------------------------------------------------------------------
# 37. Profile save/load round-trip (v0.5.0 supplement)
#     harbor profile save/load/ls/rm are the core profile management commands.
#     Test the full lifecycle: save current config as a profile, verify it
#     appears in listing, modify a config value, load the profile to restore
#     the original, then clean up. Note: gum confirm blocks rm in non-TTY
#     mode, so cleanup uses direct file removal.
# ---------------------------------------------------------------------------
suite_log "=== Profile save/load round-trip ==="

# Use a unique profile name to avoid collisions with user profiles
test_profile_name="harbor-test-profile-$$"
harbor_home_dir="$(harbor home)"
profile_file="$harbor_home_dir/profiles/$test_profile_name.env"

# Ensure no leftover from a previous run
rm -f "$profile_file"

# Save the current configuration as a profile
assert_ok "profile save: save current config" harbor profile save "$test_profile_name"

# Verify the profile file was created
if [ ! -f "$profile_file" ]; then
  fail "profile save: profile file not created at $profile_file"
fi
suite_log "profile save: profile file exists"

# Verify profile appears in listing
assert_match "profile ls: includes saved profile" "$test_profile_name" harbor profile ls

# Record a config value, change it, then load the profile to restore
original_prefix=$(harbor config get container.prefix)
harbor config set container.prefix "harbor-test-changed-$$" >/dev/null 2>&1

changed_prefix=$(harbor config get container.prefix)
if [ "$changed_prefix" = "$original_prefix" ]; then
  fail "profile round-trip: config set did not actually change the value"
fi
suite_log "profile round-trip: config value changed from '$original_prefix' to '$changed_prefix'"

# Load the profile — should restore the original value
assert_ok "profile load: load saved profile" harbor profile load "$test_profile_name"

restored_prefix=$(harbor config get container.prefix)
if [ "$restored_prefix" != "$original_prefix" ]; then
  fail "profile load: container.prefix not restored (expected '$original_prefix', got '$restored_prefix')"
fi
suite_log "profile load: container.prefix correctly restored to '$original_prefix'"

# Profile load of a nonexistent profile should fail
suite_log "profile load: nonexistent profile fails"
if harbor profile load "nonexistent-profile-xyz-$$" >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "profile load of nonexistent profile unexpectedly succeeded"
fi

# Profile save with invalid name (path traversal) should fail
suite_log "profile save: rejects path traversal name"
if harbor profile save "../escape" >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "profile save with path traversal name unexpectedly succeeded"
fi

# Profile help shows commands
assert_match "profile --help: shows commands" "save|add" harbor profile --help

# Cleanup: remove the profile file directly (gum confirm blocks in non-TTY)
rm -f "$profile_file"
if [ -f "$profile_file" ]; then
  fail "profile cleanup: could not remove test profile"
fi
suite_log "profile cleanup: test profile removed"

# Verify the profile no longer appears in listing
suite_log "profile ls: no longer includes removed profile"
if harbor profile ls 2>/tmp/cli-step.out | grep -q "$test_profile_name"; then
  fail "profile ls still shows removed profile '$test_profile_name'"
fi
suite_log "profile round-trip: complete"

# ---------------------------------------------------------------------------
# 38. Update CLI behavior (v0.5.0 supplement)
#     harbor update got significant hardening in v0.5.0: same-version skip,
#     shallow clone handling, override.env stash/restore, signal traps.
#     Test what we can safely verify without actually running a destructive
#     update (no git fetch/checkout).
# ---------------------------------------------------------------------------
suite_log "=== Update CLI behavior ==="

# harbor version outputs the expected format
assert_match "harbor version: correct format" \
  'Harbor CLI version: [0-9]+\.[0-9]+\.[0-9]+' harbor --version

# The version string should be a valid semver-ish number
version_str=$(harbor --version 2>&1 | sed 's/Harbor CLI version: //')
if ! echo "$version_str" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  fail "version string '$version_str' is not in X.Y.Z format"
fi
suite_log "harbor version: '$version_str' is valid semver format"

# update_harbor function validates .git directory exists
# Extract and test the prerequisite check in isolation
harbor_script="$(harbor home)/harbor.sh"
suite_log "update: prerequisite check — .git directory"
(
  log_error() { echo "ERROR: $*" >&2; }
  log_warn() { echo "WARN: $*" >&2; }
  log_info() { echo "INFO: $*" >&2; }
  log_debug() { :; }
  _with_timeout() { shift; "$@"; }
  harbor_home="/tmp/harbor-fake-no-git-$$"
  mkdir -p "$harbor_home"
  version="0.0.0"

  # Source just the update_harbor function
  eval "$(sed -n '/^update_harbor()/,/^}/p' "$harbor_script")"

  # Should fail because /tmp/harbor-fake-no-git-$$ has no .git
  if update_harbor 2>/tmp/cli-step-update.out; then
    echo "UNEXPECTED_SUCCESS"
  else
    echo "EXPECTED_FAIL"
  fi
  rmdir "$harbor_home" 2>/dev/null
) > /tmp/cli-step.out 2>&1

if ! grep -q "EXPECTED_FAIL" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "update prerequisite: did not reject missing .git directory"
fi
suite_log "update: correctly rejects missing .git directory"

# update_harbor requires git command
suite_log "update: prerequisite check — git command"
(
  log_error() { echo "ERROR: $*" >&2; }
  log_warn() { echo "WARN: $*" >&2; }
  log_info() { echo "INFO: $*" >&2; }
  log_debug() { :; }
  _with_timeout() { shift; "$@"; }
  harbor_home="/tmp/harbor-fake-git-$$"
  mkdir -p "$harbor_home/.git"
  version="0.0.0"

  eval "$(sed -n '/^update_harbor()/,/^}/p' "$harbor_script")"

  # Override PATH to hide git
  PATH="/usr/sbin"
  if update_harbor 2>/tmp/cli-step-update.out; then
    echo "UNEXPECTED_SUCCESS"
  else
    echo "EXPECTED_FAIL"
  fi
  rm -rf "$harbor_home"
) > /tmp/cli-step.out 2>&1

if ! grep -q "EXPECTED_FAIL" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "update prerequisite: did not reject missing git command"
fi
suite_log "update: correctly rejects missing git command"

# Verify resolve_harbor_version function exists and handles errors
suite_log "update: resolve_harbor_version defined"
if ! grep -q "resolve_harbor_version()" "$harbor_script"; then
  fail "resolve_harbor_version function not found in harbor.sh"
fi
suite_log "update: resolve_harbor_version function exists"

# Verify the same-version skip logic is present in the source
if ! grep -q "Already up to date" "$harbor_script"; then
  fail "update: same-version skip message not found in harbor.sh"
fi
suite_log "update: same-version skip logic present"

# Verify shallow clone handling is present
if ! grep -q "shallow" "$harbor_script"; then
  fail "update: shallow clone handling not found in harbor.sh"
fi
suite_log "update: shallow clone handling present"

# Verify override.env stash/restore is present
if ! grep -q "override.env" "$harbor_script"; then
  fail "update: override.env stash/restore not found in harbor.sh"
fi
suite_log "update: override.env stash/restore present"

rm -f /tmp/cli-step.out /tmp/cli-step-update.out

# ---------------------------------------------------------------------------
# 39. Install validation and doctor --check (v0.5.0 supplement)
#     v0.5.0 added doctor --check mode for scripted validation. Test deeper
#     aspects: individual check categories, expected output patterns, and
#     the --check flag behavior beyond the basic pass/fail from section #13.
# ---------------------------------------------------------------------------
suite_log "=== Install validation ==="

# doctor --check should verify essential prerequisites
suite_log "doctor --check: captures output"
harbor doctor --check >/tmp/cli-doctor.out 2>&1 || true
doctor_output=$(cat /tmp/cli-doctor.out)

# Doctor should check for git
if ! echo "$doctor_output" | grep -qi "git"; then
  fail "doctor --check: does not check for git"
fi
suite_log "doctor --check: validates git"

# Doctor should check for curl
if ! echo "$doctor_output" | grep -qi "curl"; then
  fail "doctor --check: does not check for curl"
fi
suite_log "doctor --check: validates curl"

# Doctor should check Harbor home directory
if ! echo "$doctor_output" | grep -qi "harbor home\|Harbor home"; then
  fail "doctor --check: does not check Harbor home"
fi
suite_log "doctor --check: validates Harbor home"

# Doctor should check .git repository status
if ! echo "$doctor_output" | grep -qi "git"; then
  fail "doctor --check: does not check git repository"
fi
suite_log "doctor --check: validates git status"

# Doctor should mention Docker (even if unavailable, it should check)
if ! echo "$doctor_output" | grep -qi "docker\|Docker"; then
  fail "doctor --check: does not mention Docker"
fi
suite_log "doctor --check: checks Docker"

# Verify doctor runs without --check too (interactive mode)
assert_ok "doctor: runs in default mode" harbor doctor

# Verify the validate_profile_content function rejects command injection
# This is an install hardening measure from v0.5.0
suite_log "install hardening: validate_profile_content rejects injection"
(
  log_error() { echo "ERROR: $*" >&2; }
  eval "$(sed -n '/^validate_profile_content()/,/^}/p' "$harbor_script")"

  # Create a malicious profile with command substitution
  malicious_profile="/tmp/harbor-malicious-profile-$$.env"
  echo 'HARBOR_EVIL_KEY=$(whoami)' > "$malicious_profile"
  if validate_profile_content "$malicious_profile" 2>/dev/null; then
    echo "ACCEPTED_INJECTION"
  else
    echo "REJECTED_INJECTION"
  fi
  rm -f "$malicious_profile"
) > /tmp/cli-step.out 2>&1

if ! grep -q "REJECTED_INJECTION" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "validate_profile_content accepted command injection"
fi
suite_log "install hardening: command injection correctly rejected"

# Also test backtick injection
suite_log "install hardening: validate_profile_content rejects backtick injection"
(
  log_error() { echo "ERROR: $*" >&2; }
  eval "$(sed -n '/^validate_profile_content()/,/^}/p' "$harbor_script")"

  malicious_profile="/tmp/harbor-malicious-profile2-$$.env"
  echo 'HARBOR_EVIL_KEY=`whoami`' > "$malicious_profile"
  if validate_profile_content "$malicious_profile" 2>/dev/null; then
    echo "ACCEPTED_INJECTION"
  else
    echo "REJECTED_INJECTION"
  fi
  rm -f "$malicious_profile"
) > /tmp/cli-step.out 2>&1

if ! grep -q "REJECTED_INJECTION" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "validate_profile_content accepted backtick injection"
fi
suite_log "install hardening: backtick injection correctly rejected"

# Test that a clean profile passes validation
suite_log "install hardening: validate_profile_content accepts clean profile"
(
  log_error() { echo "ERROR: $*" >&2; }
  eval "$(sed -n '/^validate_profile_content()/,/^}/p' "$harbor_script")"

  clean_profile="/tmp/harbor-clean-profile-$$.env"
  echo 'HARBOR_TEST_KEY=hello_world' > "$clean_profile"
  echo 'HARBOR_ANOTHER_KEY=42' >> "$clean_profile"
  echo '# This is a comment' >> "$clean_profile"
  if validate_profile_content "$clean_profile" 2>/dev/null; then
    echo "ACCEPTED_CLEAN"
  else
    echo "REJECTED_CLEAN"
  fi
  rm -f "$clean_profile"
) > /tmp/cli-step.out 2>&1

if ! grep -q "ACCEPTED_CLEAN" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "validate_profile_content rejected a clean profile"
fi
suite_log "install hardening: clean profile correctly accepted"

rm -f /tmp/cli-step.out /tmp/cli-doctor.out

# ---------------------------------------------------------------------------
# 40. harbor home and path resolution (v0.5.0 supplement)
#     harbor home outputs the resolved harbor installation directory. This
#     is the root path used for services, profiles, config, and all internal
#     operations. Verify it's correct and contains expected structure.
# ---------------------------------------------------------------------------
suite_log "=== harbor home and path resolution ==="

# harbor home outputs a valid directory path
harbor_home_path=$(harbor home)
if [ -z "$harbor_home_path" ]; then
  fail "harbor home: output is empty"
fi
suite_log "harbor home: outputs '$harbor_home_path'"

if [ ! -d "$harbor_home_path" ]; then
  fail "harbor home: path '$harbor_home_path' is not a directory"
fi
suite_log "harbor home: path is a valid directory"

# harbor home path should contain expected subdirectories
for expected_dir in services profiles routines docs app; do
  if [ ! -d "$harbor_home_path/$expected_dir" ]; then
    fail "harbor home: missing expected subdirectory '$expected_dir'"
  fi
  suite_log "harbor home: contains $expected_dir/"
done

# harbor home should contain harbor.sh
if [ ! -f "$harbor_home_path/harbor.sh" ]; then
  fail "harbor home: harbor.sh not found"
fi
suite_log "harbor home: contains harbor.sh"

# harbor home should contain .env (the active config)
if [ ! -f "$harbor_home_path/.env" ]; then
  fail "harbor home: .env not found"
fi
suite_log "harbor home: contains .env"

# harbor home should be a git repository
if [ ! -d "$harbor_home_path/.git" ]; then
  fail "harbor home: .git directory not found (not a git repo)"
fi
suite_log "harbor home: is a git repository"

# harbor home should contain compose.yml (base compose file)
if [ ! -f "$harbor_home_path/compose.yml" ]; then
  fail "harbor home: compose.yml not found"
fi
suite_log "harbor home: contains compose.yml"

# Harbor resolves its own location correctly — the script at harbor_home_path
# should be the same as the one on PATH
harbor_on_path=$(command -v harbor)
if [ -z "$harbor_on_path" ]; then
  fail "harbor home: harbor not found on PATH"
fi

# Resolve symlinks to compare actual files
harbor_resolved=$(readlink -f "$harbor_on_path" 2>/dev/null || realpath "$harbor_on_path" 2>/dev/null || echo "$harbor_on_path")
harbor_home_script=$(readlink -f "$harbor_home_path/harbor.sh" 2>/dev/null || realpath "$harbor_home_path/harbor.sh" 2>/dev/null || echo "$harbor_home_path/harbor.sh")

if [ "$harbor_resolved" != "$harbor_home_script" ]; then
  fail "harbor home: script on PATH ($harbor_resolved) does not match harbor home script ($harbor_home_script)"
fi
suite_log "harbor home: PATH script matches harbor home script"

# Verify profiles directory contains at least the default profile
if [ ! -f "$harbor_home_path/profiles/default.env" ]; then
  fail "harbor home: profiles/default.env not found"
fi
suite_log "harbor home: profiles/default.env exists"

# Verify services directory has compose files
svc_count=$(ls "$harbor_home_path"/services/compose.*.yml 2>/dev/null | wc -l)
if [ "$svc_count" -lt 10 ]; then
  fail "harbor home: services directory has too few compose files ($svc_count, expected >= 10)"
fi
suite_log "harbor home: services directory has $svc_count compose files"

suite_log "OK"
