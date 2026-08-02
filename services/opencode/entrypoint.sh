#!/bin/bash
# Harbor entrypoint: fix ownership as root, then drop to the host user so
# everything opencode writes into the data/config bind mounts under
# ./services/opencode stays host-owned. The image installs opencode under
# /root and keeps HOME=/root, so chown the whole (small) /root tree —
# it includes both bind mounts and the opencode install itself.
set -e

UID_T="${TARGET_UID:-1000}"
GID_T="${TARGET_GID:-1000}"

chown -R "$UID_T:$GID_T" /root
chmod 755 /root

exec setpriv --reuid "$UID_T" --regid "$GID_T" --clear-groups \
  env HOME=/root "$@"
