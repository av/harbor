#!/bin/sh
# Chown the shared cognee workspace bind mount (sqlite/kuzu/lancedb data)
# to the host user before the API/MCP containers start, so files under
# services/cognee/workspace stay manageable without sudo.
set -e
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /workspace
