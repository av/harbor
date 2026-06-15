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

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-/opt/harbor-test/repo}"
BOOST_DIR="${HARBOR_TEST_REPO}/services/boost"
AGENTIC_MODE="${HARBOR_TEST_AGENTIC_MODE:-container}"
PYTEST_TIMEOUT_SECONDS="${HARBOR_TEST_AGENTIC_TIMEOUT:-600}"

# shellcheck source=../lib/boost-agentic.sh
source "${HARBOR_TEST_REPO}/tests/lib/boost-agentic.sh"

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
    timeout "${PYTEST_TIMEOUT_SECONDS}" \
      run_boost_agentic_pytest container "${BOOST_DIR}" "${boost_image}"
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