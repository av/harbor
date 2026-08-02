#!/bin/sh
# Pre-create the state bind-mount with the ownership OpenHands expects.
# Docker creates missing bind-mount targets as root:root; the openhands
# entrypoint remaps its app user to SANDBOX_USER_ID (HARBOR_USER_ID) and
# crashes on first boot with PermissionError writing /.openhands/.jwt_secret.
# Mirrors the anythingllm/langflow/kotaemon init-sidecar pattern.
set -e
mkdir -p /state
chown -R "${HARBOR_USER_ID:-1000}:${HARBOR_GROUP_ID:-1000}" /state
chmod -R 0775 /state
