#!/bin/bash

# Stubbed unit tests for the macOS install path in requirements.sh.
#
# macOS cannot run in the container test matrix, so the Darwin-only branch
# logic (macos_has_docker_provider + brew_install cask decisions) is verified
# here by stubbing uname/brew/docker/open/git/curl as PATH shims and sourcing
# requirements.sh with HARBOR_REQUIREMENTS_SOURCE_ONLY=1.
#
# The whole battery is also re-executed inside a bash:3.2 container (stock
# macOS /bin/bash) to assert the sourced path contains no bash-4isms.
#
# Run via: harbor dev test-requirements-macos
# Flags: --no-bash32 skips the container pass (used for the inner run too).

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
REQUIREMENTS="$REPO_ROOT/requirements.sh"

RUN_BASH32=true
for arg in "$@"; do
    case "$arg" in
        --no-bash32) RUN_BASH32=false ;;
    esac
done

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/harbor-req-macos-test.XXXXXX")
trap 'rm -rf "$WORK_DIR"' EXIT

PASS_COUNT=0
FAIL_COUNT=0

t_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf 'PASS  %s\n' "$1"
}

t_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    printf 'FAIL  %s\n' "$1"
    if [ -n "${2:-}" ]; then
        printf '      %s\n' "$2"
    fi
}

assert_contains() {
    # assert_contains <label> <haystack-file> <needle>
    if grep -qF -- "$3" "$2" 2>/dev/null; then
        t_pass "$1"
    else
        t_fail "$1" "expected to find: $3"
    fi
}

assert_not_contains() {
    if grep -qF -- "$3" "$2" 2>/dev/null; then
        t_fail "$1" "expected NOT to find: $3"
    else
        t_pass "$1"
    fi
}

# --- stub environment -------------------------------------------------------

# Each case gets a fresh stub bin dir + fake HOME + state dir. All external
# commands the macOS code path touches are shimmed; PATH is restricted to the
# stub dir during the call so a real host docker/brew can never leak in.

CASE_DIR=""
STATE_DIR=""
FAKE_HOME=""

write_stub() {
    # write_stub <name> <body...>
    local name="$1"
    shift
    printf '#!/bin/sh\n%s\n' "$*" > "$CASE_DIR/$name"
    chmod +x "$CASE_DIR/$name"
}

setup_case() {
    CASE_DIR="$WORK_DIR/case-$1"
    STATE_DIR="$CASE_DIR/state"
    FAKE_HOME="$CASE_DIR/home"
    mkdir -p "$CASE_DIR" "$STATE_DIR" "$FAKE_HOME"

    write_stub uname 'echo Darwin'
    write_stub git 'echo "git version 2.39.0 (stub)"'
    write_stub curl 'exit 0'
    write_stub open 'echo "open $*" >> "'"$STATE_DIR"'/open.log"'
    write_stub sleep 'exit 0'
    # _with_timeout prefers GNU timeout; shim it so perl is never needed.
    # Inherits the restricted PATH so "timeout 10 docker info" can never
    # resolve a real host docker binary.
    write_stub timeout 'shift; exec "$@"'
    # brew logs every invocation; a cask install of docker "provisions" the
    # daemon (marker file) and the docker CLI, like Docker Desktop does.
    # PATH is extended (appended) so cp/touch resolve without unshadowing stubs.
    write_stub brew "PATH=\"\$PATH:/usr/bin:/bin\"
echo \"\$*\" >> '$STATE_DIR/brew.log'
if [ \"\$1\" = install ] && [ \"\$2\" = --cask ] && [ \"\$3\" = docker ]; then
    touch '$STATE_DIR/daemon-up'
    cp '$CASE_DIR/.docker-stub' '$CASE_DIR/docker' 2>/dev/null || true
fi
exit 0"
    # docker stub template: info/compose succeed only once the daemon marker
    # exists. Installed per-case as $CASE_DIR/docker when the CLI should exist.
    printf '#!/bin/sh\nif [ -e "%s/daemon-up" ]; then exit 0; fi\nexit 1\n' \
        "$STATE_DIR" > "$CASE_DIR/.docker-stub"
    chmod +x "$CASE_DIR/.docker-stub"
}

give_docker_cli() {
    cp "$CASE_DIR/.docker-stub" "$CASE_DIR/docker"
}

daemon_up() {
    touch "$STATE_DIR/daemon-up"
}

# Source requirements.sh fresh in a subshell with the restricted stub PATH
# and run the given snippet. Output (stdout+stderr) lands in $1.
run_case() {
    local out="$1"
    local rc=0
    shift
    (
        export HOME="$FAKE_HOME"
        export HARBOR_REQUIREMENTS_SOURCE_ONLY=1
        # shellcheck disable=SC1090
        . "$REQUIREMENTS"
        PATH="$CASE_DIR"
        export PATH
        # Darwin uname stub -> PLATFORM=macos, as on a real macOS run
        detect_platform
        "$@"
    ) > "$out" 2>&1 || rc=$?
    echo "exit=${rc:-0}" >> "$out"
}

# --- tests ------------------------------------------------------------------

test_detect_platform() {
    setup_case detect
    run_case "$CASE_DIR/out" eval 'detect_platform; echo "platform=$PLATFORM"'
    assert_contains "detect_platform: Darwin uname -> macos" "$CASE_DIR/out" "platform=macos"
}

test_provider_detection() {
    # daemon reachable
    setup_case prov-daemon
    give_docker_cli
    daemon_up
    run_case "$CASE_DIR/out" eval 'macos_has_docker_provider && echo provider=yes || echo provider=no'
    assert_contains "provider: reachable daemon" "$CASE_DIR/out" "provider=yes"

    # Docker.app in ~/Applications
    setup_case prov-dockerapp
    give_docker_cli
    mkdir -p "$FAKE_HOME/Applications/Docker.app"
    run_case "$CASE_DIR/out" eval 'macos_has_docker_provider && echo provider=yes || echo provider=no'
    assert_contains "provider: ~/Applications/Docker.app" "$CASE_DIR/out" "provider=yes"

    # OrbStack in ~/Applications
    setup_case prov-orbstack
    give_docker_cli
    mkdir -p "$FAKE_HOME/Applications/OrbStack.app"
    run_case "$CASE_DIR/out" eval 'macos_has_docker_provider && echo provider=yes || echo provider=no'
    assert_contains "provider: ~/Applications/OrbStack.app" "$CASE_DIR/out" "provider=yes"

    # colima on PATH
    setup_case prov-colima
    give_docker_cli
    write_stub colima 'exit 0'
    run_case "$CASE_DIR/out" eval 'macos_has_docker_provider && echo provider=yes || echo provider=no'
    assert_contains "provider: colima on PATH" "$CASE_DIR/out" "provider=yes"

    # podman on PATH
    setup_case prov-podman
    give_docker_cli
    write_stub podman 'exit 0'
    run_case "$CASE_DIR/out" eval 'macos_has_docker_provider && echo provider=yes || echo provider=no'
    assert_contains "provider: podman on PATH" "$CASE_DIR/out" "provider=yes"

    # nothing at all
    setup_case prov-none
    give_docker_cli
    run_case "$CASE_DIR/out" eval 'macos_has_docker_provider && echo provider=yes || echo provider=no'
    assert_contains "provider: bare CLI, nothing else" "$CASE_DIR/out" "provider=no"
}

test_no_docker_installs_cask() {
    setup_case no-docker
    run_case "$CASE_DIR/out" brew_install
    assert_contains "no docker: cask install requested" "$STATE_DIR/brew.log" "install --cask docker"
    assert_contains "no docker: Desktop launched" "$STATE_DIR/open.log" "open -g -a Docker"
    assert_contains "no docker: daemon came up" "$CASE_DIR/out" "Docker Desktop is running"
    assert_contains "no docker: brew_install succeeded" "$CASE_DIR/out" "exit=0"
}

test_bare_cli_installs_cask_with_warning() {
    setup_case bare-cli
    give_docker_cli
    run_case "$CASE_DIR/out" brew_install
    assert_contains "bare CLI: warning printed" "$CASE_DIR/out" \
        "docker CLI is installed, but no container engine was found"
    assert_contains "bare CLI: cask install requested" "$STATE_DIR/brew.log" "install --cask docker"
    assert_contains "bare CLI: daemon came up" "$CASE_DIR/out" "Docker Desktop is running"
    assert_contains "bare CLI: brew_install succeeded" "$CASE_DIR/out" "exit=0"
}

test_provider_present_no_cask() {
    setup_case has-provider
    give_docker_cli
    mkdir -p "$FAKE_HOME/Applications/OrbStack.app"
    # Daemon is down; brew_install will try to start Docker Desktop and wait.
    # Shorten the wait to a single probe so the test stays fast.
    run_case "$CASE_DIR/out" eval \
        'wait_for_docker_access() { docker info >/dev/null 2>&1; }; brew_install'
    assert_not_contains "provider present: no cask install" "$STATE_DIR/brew.log" "install --cask docker"
    assert_contains "provider present: CLI acknowledged" "$CASE_DIR/out" "docker CLI is already installed"
    assert_contains "provider present: brew_install succeeded" "$CASE_DIR/out" "exit=0"
}

test_reachable_daemon_proceeds() {
    setup_case daemon-up
    give_docker_cli
    daemon_up
    run_case "$CASE_DIR/out" brew_install
    assert_not_contains "daemon up: no cask install" "$STATE_DIR/brew.log" "install --cask docker"
    assert_not_contains "daemon up: no warnings" "$CASE_DIR/out" "[WARN]"
    assert_contains "daemon up: CLI acknowledged" "$CASE_DIR/out" "docker CLI is already installed"
    assert_contains "daemon up: brew_install succeeded" "$CASE_DIR/out" "exit=0"
}

# --- bash 3.2 container pass ------------------------------------------------

run_bash32_pass() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "SKIP  bash 3.2 pass: docker not available on host"
        return 0
    fi
    echo "--- re-running battery under bash 3.2 (bash:3.2 container) ---"
    if docker run --rm \
        -v "$REPO_ROOT/requirements.sh:/harbor/requirements.sh:ro" \
        -v "$SCRIPT_DIR/test-requirements-macos.sh:/harbor/.scripts/test-requirements-macos.sh:ro" \
        bash:3.2 \
        bash /harbor/.scripts/test-requirements-macos.sh --no-bash32; then
        t_pass "bash 3.2: full battery green under bash 3.2"
    else
        t_fail "bash 3.2: full battery green under bash 3.2" "see container output above"
    fi
}

# --- main -------------------------------------------------------------------

echo "bash version: $BASH_VERSION"

test_detect_platform
test_provider_detection
test_no_docker_installs_cask
test_bare_cli_installs_cask_with_warning
test_provider_present_no_cask
test_reachable_daemon_proceeds

if [ "$RUN_BASH32" = true ]; then
    run_bash32_pass
fi

echo
echo "passed=$PASS_COUNT failed=$FAIL_COUNT"
if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
