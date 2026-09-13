#!/bin/sh
# Follow the TEI init-sidecar pattern. Repair root-owned HF entries left by
# older containers, without following cache symlinks or re-owning other users' files.
set -e
uid="${TARGET_UID:-1000}"
gid="${TARGET_GID:-1000}"

chown "$uid:$gid" /cache
for path in /cache/hub /cache/xet /cache/assets /cache/token /cache/stored_tokens; do
  [ -e "$path" ] || [ -L "$path" ] || continue
  find "$path" -xdev -user 0 -exec chown -h "$uid:$gid" {} +
done
