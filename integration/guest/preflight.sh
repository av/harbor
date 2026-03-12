#!/usr/bin/env bash
# Guest-side preflight checks for Harbor integration tests.
# Can be sourced or executed directly.
set -eo pipefail

log_pre() { echo "[preflight] $*"; }

log_pre "=== Harbor Integration Preflight ==="

log_pre "--- OS Info ---"
uname -a
cat /etc/os-release 2>/dev/null || true

log_pre "--- Tool Versions ---"

if docker --version 2>/dev/null; then
  log_pre "docker: $(docker --version 2>/dev/null)"
else
  log_pre "docker: not found (will be installed by bootstrap)"
fi

if docker compose version 2>/dev/null; then
  log_pre "docker compose: $(docker compose version --short 2>/dev/null || echo OK)"
else
  log_pre "docker compose: not found (will be installed by bootstrap)"
fi

log_pre "git: $(git --version 2>/dev/null || echo 'not found')"
log_pre "curl: $(curl --version 2>/dev/null | head -1 || echo 'not found')"
log_pre "deno: $(deno --version 2>/dev/null || echo 'not found')"
log_pre "node: $(node --version 2>/dev/null || echo 'not found')"
log_pre "npm: $(npm --version 2>/dev/null || echo 'not found')"

log_pre "=== Preflight complete ==="
