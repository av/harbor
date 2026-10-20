#!/bin/sh
# Pre-create the data bind-mount with host-user ownership: rummage runs as
# the host user and writes its config, index, thumbnails and model files there.
set -e
mkdir -p /workspace
chown "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /workspace
chmod 0775 /workspace
