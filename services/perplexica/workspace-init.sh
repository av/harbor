#!/bin/sh
# Pre-create the data bind-mount with host-user ownership so the user
# can manage / delete files without sudo. Docker creates missing bind-mount
# targets as root:root by default; chowning here before the backend starts
# keeps host ownership intact (the backend runs as the host user).
set -e
mkdir -p /workspace
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /workspace
chmod -R 0775 /workspace
