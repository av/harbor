#!/bin/sh
# Pre-create the sqlite data bind-mount with host-user ownership and an
# empty database file. Docker creates missing bind-mount targets as
# root:root, but the upstream image runs as uid 1001 and cannot write
# /app/data — first boot then fails with "Database not ready".
# Chowning to the host user here (and running the gateway as that user)
# keeps the host dir manageable without sudo.
set -e
mkdir -p /workspace
touch /workspace/mcp.db
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /workspace
chmod -R 0775 /workspace
