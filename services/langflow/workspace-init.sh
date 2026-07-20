#!/bin/sh
# Pre-create the data bind-mount with host-user ownership so the user can
# manage / delete files without sudo. Docker creates missing bind-mount
# targets as root:root by default; langflow runs as a non-root user and
# fails on first boot with PermissionError writing /var/lib/langflow.
# Chowning here before the main container starts fixes first boot and keeps
# host ownership intact. Mirrors the kotaemon/unsloth-studio/beszel pattern.
set -e
mkdir -p /workspace
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /workspace
chmod -R 0775 /workspace
