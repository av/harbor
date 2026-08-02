#!/bin/sh
# Pre-create Onyx workspace bind-mount subdirs with host-user ownership.
# Docker creates missing bind-mount targets as root:root by default; the
# Vespa container (onyx-index) runs as a non-root user (uid 1000) and
# fatally fails with "mkdir var/tmp: permission denied" on a root-owned
# /opt/vespa/var. Chowning here before the main containers start also
# keeps the host directory manageable without `sudo`.
#
# Deliberately excludes ./db — postgres manages its own ownership (uid 70)
# and must not be re-chowned on every start.
set -e
for dir in vespa api_logs background_logs minio; do
  mkdir -p "/workspace/$dir"
  chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" "/workspace/$dir"
  chmod -R 0775 "/workspace/$dir"
done
