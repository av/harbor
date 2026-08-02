#!/bin/sh
# Pre-create the workspace bind-mount with host-user ownership so the user
# can manage / delete files without sudo. Docker creates missing bind-mount
# targets as root:root by default; the upstream container then writes into
# them, leaving the host dir undeletable without `sudo`. Chowning here
# before the main container starts keeps host ownership intact.
#
# flowise mounts ${HARBOR_FLOWISE_WORKSPACE} at /home/node/.flowise. Top-level
# chown is sufficient — flowise creates its own subdirs at runtime.
set -e
mkdir -p /workspace
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /workspace
chmod -R 0775 /workspace
