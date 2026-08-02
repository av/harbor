#!/bin/sh
# Chown the pipelines persistence bind mount to the host user before the main
# container starts, so files under services/pipelines/persistent stay
# manageable without sudo.
set -e
chown -R "${TARGET_UID:-1000}:${TARGET_GID:-1000}" /persistent
