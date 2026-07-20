#!/bin/sh
# Pre-create the storage bind-mount with the ownership the anythingllm image
# expects. Docker creates missing bind-mount targets as root:root; the image
# runs as the fixed uid 1000 (anythingllm) and crash-loops on first boot with
# "unable to open database file" for storage/anythingllm.db. Mirrors the
# langflow/kotaemon/beszel init-sidecar pattern.
set -e
mkdir -p /storage
chown -R 1000:1000 /storage
chmod -R 0775 /storage
