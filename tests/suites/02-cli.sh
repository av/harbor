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
fake_bin="$(mktemp -d)"
fake_docker_log="$(mktemp)"
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

suite_log "launch --service requires a handle"
if harbor launch --service >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch --service without handle unexpectedly succeeded"
fi
if ! grep -Eq -- 'Usage: harbor launch \[--service\] <service\|tool>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch --service without handle did not print usage"
fi

suite_log "launch opencode missing host tool suggests service mode"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_DOCKER_LOG="$fake_docker_log" PATH="$fake_bin:/usr/bin:/bin" ./harbor.sh launch opencode --backend ollama --model test-model >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch opencode missing host tool unexpectedly succeeded"
fi
if ! grep -Eq -- 'harbor launch --service opencode' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch opencode missing host tool did not suggest service mode"
fi

assert_ok "launch --service opencode" env HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_DOCKER_LOG="$fake_docker_log" PATH="$fake_bin:$PATH" harbor launch --service opencode --help
if ! grep -Eq -- 'run -T --rm opencode --help' "$fake_docker_log"; then
  cat "$fake_docker_log" >&2
  fail "launch --service opencode did not dispatch to docker compose run"
fi
rm -rf "$fake_bin" "$fake_docker_log"

# 7c. launch host adapters — backend/model discovery failures should be
#     actionable from a user's terminal, and --model must avoid parsing
#     /v1/models while still checking that the selected backend is reachable.
launch_fake_bin="$(mktemp -d)"
launch_fake_curl_log="$(mktemp)"
cat >"$launch_fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "compose ps --format {{.Service}}")
    printf '%s\n' ${HARBOR_FAKE_RUNNING_SERVICES:-}
    exit 0
    ;;
  "compose ps --services --filter status=running")
    printf '%s\n' ${HARBOR_FAKE_RUNNING_SERVICES:-}
    exit 0
    ;;
  "compose ps -a --services --filter status=running")
    printf '%s\n' ${HARBOR_FAKE_RUNNING_SERVICES:-}
    exit 0
    ;;
  "port harbor.ollama")
    echo "11434/tcp -> 0.0.0.0:11434"
    exit 0
    ;;
  "port harbor.unsloth-studio")
    echo "34851/tcp -> 0.0.0.0:34851"
    exit 0
    ;;
esac

if [ "$1" = "compose" ]; then
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

suite_log "launch codex reports no running backend"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=webui PATH="$launch_fake_bin:/usr/bin:/bin" ./harbor.sh launch codex --config >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex without running backend unexpectedly succeeded"
fi
if ! grep -Eq -- 'No running Harbor OpenAI-compatible backend found' /tmp/cli-step.out || ! grep -Eq -- 'Start a compatible backend with: harbor up ollama' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex without running backend did not print remediation"
fi

suite_log "launch codex reports explicit backend not running"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=webui PATH="$launch_fake_bin:/usr/bin:/bin" ./harbor.sh launch codex --backend ollama --config >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with stopped explicit backend unexpectedly succeeded"
fi
if ! grep -Eq -- "Backend 'ollama' is not running" /tmp/cli-step.out || ! grep -Eq -- 'harbor up ollama' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with stopped explicit backend did not print remediation"
fi

suite_log "launch codex reports explicit backend unreachable"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=ollama HARBOR_FAKE_CURL_MODE=fail PATH="$launch_fake_bin:/usr/bin:/bin" ./harbor.sh launch codex --backend ollama --model test-model --config >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with unreachable explicit backend unexpectedly succeeded"
fi
if ! grep -Eq -- "Backend 'ollama' is running, but its OpenAI-compatible endpoint is not reachable" /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with unreachable explicit backend did not print reachability error"
fi

suite_log "launch codex reports empty /v1/models"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=unsloth-studio HARBOR_FAKE_CURL_MODE=empty PATH="$launch_fake_bin:/usr/bin:/bin" ./harbor.sh launch codex --backend unsloth-studio --config >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with empty models unexpectedly succeeded"
fi
if ! grep -Eq -- "did not advertise any models" /tmp/cli-step.out || ! grep -Eq -- 'pass one explicitly with --model <model>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with empty models did not print remediation"
fi

suite_log "launch codex reports invalid /v1/models"
if HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=unsloth-studio HARBOR_FAKE_CURL_MODE=invalid PATH="$launch_fake_bin:/usr/bin:/bin" ./harbor.sh launch codex --backend unsloth-studio --config >/tmp/cli-step.out 2>&1; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with invalid models unexpectedly succeeded"
fi
if ! grep -Eq -- "returned an invalid /v1/models response" /tmp/cli-step.out || ! grep -Eq -- 'pass a known model explicitly with --model <model>' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex with invalid models did not print remediation"
fi

suite_log "launch codex --model skips model discovery"
: >"$launch_fake_curl_log"
assert_ok "launch codex --model skips model discovery" env HARBOR_LEGACY_CLI=true HARBOR_CAPABILITIES_AUTODETECT=false HARBOR_FAKE_RUNNING_SERVICES=ollama HARBOR_FAKE_CURL_MODE=invalid HARBOR_FAKE_CURL_LOG="$launch_fake_curl_log" PATH="$launch_fake_bin:/usr/bin:/bin" ./harbor.sh launch codex --backend ollama --model explicit-model --config
if ! grep -Eq -- '^model=explicit-model$' /tmp/cli-step.out; then
  cat /tmp/cli-step.out >&2
  fail "launch codex --model did not use the explicit model"
fi
if [ "$(wc -l <"$launch_fake_curl_log")" -ne 1 ]; then
  cat "$launch_fake_curl_log" >&2
  fail "launch codex --model called curl more than once"
fi
rm -rf "$launch_fake_bin" "$launch_fake_curl_log"

# 8. Doctor — runs without bringing services up. requirements.sh-derived
#    checks (docker, compose v2 >= 2.23, git, curl) all pass against the
#    row image we built.
assert_ok    "harbor doctor"         harbor doctor

# 9. ps — lists harbor-prefixed containers; OK to be empty.
assert_ok    "harbor ps"             harbor ps

# 10. profile listing — exercises profiles/ walking.
assert_ok    "harbor profile ls"     harbor profile ls

rm -f /tmp/cli-step.out
suite_log "OK"
