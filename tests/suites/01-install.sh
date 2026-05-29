#!/usr/bin/env bash
# Suite: install
#
# Installs Harbor into the running row and verifies `harbor --version` works.
#
# Install source is picked from $HARBOR_TEST_INSTALL_SOURCE:
#   - "local"  (default inside the orchestrator's privileged rows): reuse the
#              bind-mounted repo at /opt/harbor-test/repo — tests the shipped
#              requirements.sh/harbor.sh against this row's distro without
#              touching the network. This is what catches the `tr '[:lower:]'`
#              class of bugs: the code that runs is the code in the working
#              tree, not a stale release on GitHub.
#   - "github": curl the published install.sh — exercises the release artefact
#              plus the one-shot upgrade path a real user takes.
set -euo pipefail

suite_log() { echo "[install] $*"; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-/opt/harbor-test/repo}"
HARBOR_TEST_INSTALL_SOURCE="${HARBOR_TEST_INSTALL_SOURCE:-local}"

case "$HARBOR_TEST_INSTALL_SOURCE" in
  local)
    suite_log "source=local (bind-mounted repo at ${HARBOR_TEST_REPO})"
    suite_log "Running requirements.sh..."
    bash "${HARBOR_TEST_REPO}/requirements.sh"

    suite_log "Linking harbor into PATH via 'harbor ln'..."
    bash "${HARBOR_TEST_REPO}/harbor.sh" ln
    ;;
  github)
    suite_log "source=github (curl https://.../install.sh)"
    curl -fsSL https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh \
      | bash
    ;;
  *)
    echo "[install] ERROR: unknown HARBOR_TEST_INSTALL_SOURCE='${HARBOR_TEST_INSTALL_SOURCE}'" >&2
    exit 1
    ;;
esac

suite_log "Verifying 'harbor --version'..."
# Use hash -r to refresh shell path cache in case ln just dropped a new file.
hash -r || true
harbor --version

suite_log "OK"
