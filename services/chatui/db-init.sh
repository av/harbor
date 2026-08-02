#!/bin/sh
# Chown the mongo data bind mount to the host user before the DB starts, so
# files under services/chatui/data stay manageable without sudo. Docker
# creates missing bind-mount targets as root:root; mongod (remapped to the
# host uid via `user:`) then needs the dir writable.
set -e
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /data/db
