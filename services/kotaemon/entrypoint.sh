#!/bin/sh
# Start as root, then drop to the host user so runtime files written into the
# workspace bind mount stay host-owned. A plain compose `user:` remap does not
# work for this image: the uv-managed python interpreter the /app/.venv
# symlinks point to lives under /root (mode 700), unreachable for non-root.
# Opening traversal (not listing) on /root lets the remapped user execute it.
set -e
chmod 711 /root
# In-image scratch dirs kotaemon creates at runtime (workspace itself is a
# bind mount chowned by the init sidecar)
mkdir -p /app/.theflow
chown "${HARBOR_USER_ID:-1000}:${HARBOR_GROUP_ID:-1000}" /app /app/.theflow
# gradio regenerates .pyi stubs next to the ktem sources on startup
chown -R "${HARBOR_USER_ID:-1000}:${HARBOR_GROUP_ID:-1000}" /app/libs
exec setpriv --reuid "${HARBOR_USER_ID:-1000}" --regid "${HARBOR_GROUP_ID:-1000}" --clear-groups \
  /app/.venv/bin/python app.py
