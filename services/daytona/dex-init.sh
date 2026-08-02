#!/bin/sh
# Pre-create the dex data dir as the host user. Docker creates missing
# bind-mount targets as root:root, and dexidp/dex runs as uid 1001 —
# either way `touch /var/dex/dex.db` fails on first boot without this.
# The daytona-dex service runs as HARBOR_USER_ID (fallback 1001) so the
# sqlite db stays owned by the host user and remains deletable without sudo.
set -e

mkdir -p /var/dex
chown "${HARBOR_USER_ID:-1001}:${HARBOR_GROUP_ID:-1001}" /var/dex 2>/dev/null || true
if [ -f /var/dex/dex.db ]; then
  chown "${HARBOR_USER_ID:-1001}:${HARBOR_GROUP_ID:-1001}" /var/dex/dex.db 2>/dev/null || true
fi
