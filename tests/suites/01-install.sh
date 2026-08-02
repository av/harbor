#!/usr/bin/env bash
# Suite: install
#
# Installs Harbor into the running row and verifies `harbor --version` works.
#
# Install source is picked from $HARBOR_TEST_INSTALL_SOURCE:
#   - "local"  (default inside the orchestrator's privileged rows): install from
#              the git-tracked staged artifact at /opt/harbor-test/repo (not
#              the host working tree). Tests requirements.sh/harbor.sh against
#              this row's distro without touching the network.
#   - "github": curl the published install.sh — exercises the release artefact
#              plus the one-shot upgrade path a real user takes.
set -euo pipefail

suite_log() { echo "[install] $*"; }

HARBOR_TEST_REPO="${HARBOR_TEST_REPO:-/opt/harbor-test/repo}"
HARBOR_TEST_INSTALL_SOURCE="${HARBOR_TEST_INSTALL_SOURCE:-local}"

case "$HARBOR_TEST_INSTALL_SOURCE" in
  local)
    suite_log "source=local (staged git-tracked repo at ${HARBOR_TEST_REPO})"
    suite_log "Running programmatic app installer path via install.sh..."
    HARBOR_INSTALL_SOURCE_PATH="${HARBOR_TEST_REPO}" \
      HARBOR_REQUIREMENTS_PATH="${HARBOR_TEST_REPO}/requirements.sh" \
      HARBOR_INSTALL_PATH="${HARBOR_HOME:-/opt/harbor-test/work}" \
      HARBOR_INSTALL_VERSION=source \
      bash "${HARBOR_TEST_REPO}/install.sh"
    ;;
  github)
    suite_log "source=github (curl https://.../install.sh)"
    # GITHUB_TOKEN (forwarded by the orchestrator when the host has one) is
    # picked up by install.sh's releases/latest lookup. Without a token the
    # unauthenticated GitHub API allows only 60 req/hour per IP, so a github
    # install can fail on rate limiting alone — fall back to the staged local
    # repo rather than failing the whole row on an environmental limit.
    # HARBOR_INSTALL_PATH must match the row's HARBOR_HOME — otherwise the
    # published installer clones to its default ~/.harbor while harbor.sh
    # resolves state against HARBOR_HOME, and CLI linking fails.
    if ! curl -fsSL https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh \
      | HARBOR_INSTALL_PATH="${HARBOR_HOME:-/opt/harbor-test/work}" bash; then
      suite_log "WARNING: github install failed (likely GitHub API rate limit; set GITHUB_TOKEN on the host to authenticate)"
      suite_log "WARNING: falling back to source=local (staged repo at ${HARBOR_TEST_REPO})"
      HARBOR_INSTALL_SOURCE_PATH="${HARBOR_TEST_REPO}" \
        HARBOR_REQUIREMENTS_PATH="${HARBOR_TEST_REPO}/requirements.sh" \
        HARBOR_INSTALL_PATH="${HARBOR_HOME:-/opt/harbor-test/work}" \
        HARBOR_INSTALL_VERSION=source \
        bash "${HARBOR_TEST_REPO}/install.sh"
    fi
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

suite_log "Verifying first-run stack command is resolvable..."
harbor cmd llamacpp webui >/dev/null

# The App setup backend starts the first-run stack with:
#   harbor up --no-defaults llamacpp webui
if [ "${HARBOR_TEST_APP_INSTALL_FULL_STACK:-false}" = "true" ]; then
  suite_log "HARBOR_TEST_APP_INSTALL_FULL_STACK=true; running harbor up --no-defaults llamacpp webui"
  harbor up --no-defaults llamacpp webui
  harbor ps | grep -E 'llamacpp|webui'
fi

suite_log "OK"
