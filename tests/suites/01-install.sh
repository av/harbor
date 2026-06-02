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
    suite_log "Running programmatic app installer path via install.sh..."
    HARBOR_INSTALL_SOURCE_PATH="${HARBOR_TEST_REPO}" \
      HARBOR_REQUIREMENTS_PATH="${HARBOR_TEST_REPO}/requirements.sh" \
      HARBOR_INSTALL_PATH="${HARBOR_HOME:-/opt/harbor-test/work}" \
      HARBOR_INSTALL_VERSION=source \
      bash "${HARBOR_TEST_REPO}/install.sh"
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

suite_log "Verifying first-run stack command is resolvable..."
harbor cmd llamacpp webui >/dev/null

if [ -f "${HARBOR_TEST_REPO}/app/src-tauri/src/setup.rs" ]; then
  suite_log "Verifying App setup uses the model-aware llama.cpp pull path..."
  grep -Fq 'harbor_script(&["models", "pull", "--source", "llamacpp", FIRST_RUN_MODEL])' \
    "${HARBOR_TEST_REPO}/app/src-tauri/src/setup.rs"
  ! grep -Fq 'harbor_script(&["pull", "--source", "llamacpp", FIRST_RUN_MODEL])' \
    "${HARBOR_TEST_REPO}/app/src-tauri/src/setup.rs"
fi

# The App setup backend starts the first-run stack with:
#   harbor up --no-defaults llamacpp webui
if [ "${HARBOR_TEST_APP_INSTALL_FULL_STACK:-false}" = "true" ]; then
  suite_log "HARBOR_TEST_APP_INSTALL_FULL_STACK=true; running harbor up --no-defaults llamacpp webui"
  harbor up --no-defaults llamacpp webui
  harbor ps | grep -E 'llamacpp|webui'
fi

suite_log "OK"
