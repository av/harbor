#!/bin/sh
# Pre-create the storage bind-mount with the ownership the anythingllm image
# expects. Docker creates missing bind-mount targets as root:root; the image
# runs as the fixed uid 1000 (anythingllm) and crash-loops on first boot with
# "unable to open database file" for storage/anythingllm.db. Mirrors the
# langflow/kotaemon/beszel init-sidecar pattern.
set -e
mkdir -p /storage
chown -R 1000:1000 /storage
# Keep existing files' permissions, especially the settings file with API keys.
find /storage -type d -exec chmod 0775 {} +
touch /storage/.env
chown 1000:1000 /storage/.env
chmod 0600 /storage/.env

if [ -n "${HARBOR_ANYTHINGLLM_DEFAULT_EMBEDDING_MODEL:-}" ] &&
  ! grep -q '^EMBEDDING_MODEL_PREF=' /storage/.env; then
  printf 'EMBEDDING_MODEL_PREF=%s\n' "$HARBOR_ANYTHINGLLM_DEFAULT_EMBEDDING_MODEL" >> /storage/.env
fi
