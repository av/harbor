#!/bin/bash
# Harbor entrypoint: start as root only to fix ownership, then drop to the
# host user so everything presenton writes into the ./services/presenton/app_data
# bind mount (and the shared HF cache) stays host-owned.
#
# Root fixups needed because the upstream image assumes a root runtime:
# - /app/presentation-export: start.js copies index.js -> index.cjs in place
# - /etc/nginx, /var/log/nginx, /var/lib/nginx, /run: nginx runs as the host
#   user (master included), so its config sync, pid and logs must be writable
# - /root gets traversal-only 711 so the ollama/llama.cpp cache mounts under
#   /root/* stay reachable for the non-root runtime user
set -e

UID_T="${TARGET_UID:-1000}"
GID_T="${TARGET_GID:-1000}"

chown -R "$UID_T:$GID_T" /app_data /app/presentation-export \
  /var/log/nginx /var/lib/nginx /etc/nginx /run
chmod 711 /root
mkdir -p /tmp/presenton
chown "$UID_T:$GID_T" /tmp/presenton

exec setpriv --reuid "$UID_T" --regid "$GID_T" --clear-groups \
  env HOME=/tmp node /app/start.js
