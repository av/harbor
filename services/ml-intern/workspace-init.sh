#!/bin/sh
set -eu

uid="${TARGET_UID:-1000}"
gid="${TARGET_GID:-1000}"

case "$uid" in
  ''|*[!0-9]*) uid=1000 ;;
esac

case "$gid" in
  ''|*[!0-9]*) gid=1000 ;;
esac

mkdir -p /workspace/data /workspace/workspace
chown -R "$uid:$gid" /workspace
chmod -R 775 /workspace

mkdir -p /run/harbor
touch /run/harbor/ml-intern-init-done
tail -f /dev/null
