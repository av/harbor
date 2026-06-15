#!/usr/bin/env bash
# Suite: boost-agentic-smoke
#
# Builds the Harbor Boost image in the nested docker daemon, then runs the
# agentic module pytest battery inside that image with the working tree
# bind-mounted. No live LLM backend is required — tests mock downstream calls.
#
# Override HARBOR_TEST_AGENTIC_MODE=host to run pytest from the host via uv
# instead (useful for quick local iteration outside the matrix).
set -euo pipefail

suite_log() { echo "[boost-agentic-smoke] $*"; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BOOST_DIR="${HARBOR_TEST_REPO}/services/boost"
AGENTIC_MODE="${HARBOR_TEST_AGENTIC_MODE:-container}"
PYTEST_TIMEOUT_SECONDS="${HARBOR_TEST_AGENTIC_TIMEOUT:-600}"

# Matrix rows run this suite without 01-install; bootstrap harbor when needed.
ensure_harbor_cli() {
  if command -v harbor >/dev/null 2>&1; then
    return 0
  fi
  suite_log "harbor not on PATH; bootstrapping from staged repo (skip requirements)..."
  HARBOR_INSTALL_SOURCE_PATH="${HARBOR_TEST_REPO}" \
    HARBOR_REQUIREMENTS_PATH="${HARBOR_TEST_REPO}/requirements.sh" \
    HARBOR_INSTALL_PATH="${HARBOR_HOME:-${HARBOR_TEST_REPO}}" \
    HARBOR_INSTALL_VERSION=source \
    bash "${HARBOR_TEST_REPO}/install.sh" --skip-requirements
  hash -r || true
  command -v harbor >/dev/null 2>&1 || {
    echo "[boost-agentic-smoke] ERROR: harbor install did not place CLI on PATH" >&2
    exit 1
  }
}

# shellcheck source=../lib/boost-agentic.sh
source "${HARBOR_TEST_REPO}/tests/lib/boost-agentic.sh"

if [[ "${AGENTIC_MODE}" == "container" ]]; then
  ensure_harbor_cli
fi

cleanup() {
  local rc=$?
  if [[ "${AGENTIC_MODE}" == "container" ]]; then
    suite_log "Tearing down boost (trap, exit=${rc})..."
    harbor down boost >/dev/null 2>&1 || true
  fi
  return $rc
}
trap cleanup EXIT

case "$AGENTIC_MODE" in
  container)
    suite_log "mode=container (harbor build boost → pytest in Boost image)"
    suite_log "harbor build boost"
    harbor build boost

    boost_image="$(discover_boost_image)" || {
      echo "[boost-agentic-smoke] ERROR: Boost image not found after build" >&2
      exit 1
    }
    suite_log "Boost image: ${boost_image}"

    suite_log "Running agentic pytest battery (timeout: ${PYTEST_TIMEOUT_SECONDS}s)..."
    # timeout(1) cannot invoke shell functions directly; run via a sourced bash -s.
    timeout "${PYTEST_TIMEOUT_SECONDS}" bash -euo pipefail -s <<EOF
source "${HARBOR_TEST_REPO}/tests/lib/boost-agentic.sh"
run_boost_agentic_pytest container "${BOOST_DIR}" "${boost_image}"
EOF
    ;;
  host)
    suite_log "mode=host (uv run pytest from ${BOOST_DIR})"
    trap - EXIT
    suite_log "Running agentic pytest battery..."
    run_boost_agentic_pytest host "${BOOST_DIR}"
    ;;
  *)
    echo "[boost-agentic-smoke] ERROR: unknown HARBOR_TEST_AGENTIC_MODE='${AGENTIC_MODE}'" >&2
    exit 1
    ;;
esac

suite_log "OK"