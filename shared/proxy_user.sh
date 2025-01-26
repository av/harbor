#!/usr/bin/env bash

set -eo pipefail

if [ -z "$HARBOR_USER_ID" ] || [ -z "$HARBOR_GROUP_ID" ]; then
  echo "HARBOR_USER_ID or HARBOR_GROUP_ID not set!"
  exit 1
fi

USER_NAME="$(getent passwd "$HARBOR_USER_ID" | cut -d: -f1)"
GROUP_NAME="$(getent group "$HARBOR_GROUP_ID" | cut -d: -f1)"

# Create group if it doesn't exist
if [ -z "$GROUP_NAME" ]; then
  GROUP_NAME="harbor_group"
  groupadd -g "$HARBOR_GROUP_ID" "$GROUP_NAME"
fi

# Create user if it doesn't exist
if [ -z "$USER_NAME" ]; then
  USER_NAME="harbor_user"
  useradd -u "$HARBOR_USER_ID" -g "$GROUP_NAME" "$USER_NAME"
fi

# Handle docker sock
DOCKER_SOCKET=/var/run/docker.sock
if [ -S "$DOCKER_SOCKET" ]; then
  DOCKER_GID=$(stat -c '%g' "$DOCKER_SOCKET")
  DOCKER_GROUP_NAME="$(getent group "$DOCKER_GID" | cut -d: -f1)"
  if [ -z "$DOCKER_GROUP_NAME" ]; then
    DOCKER_GROUP_NAME="docker"
    groupadd -g "$DOCKER_GID" "$DOCKER_GROUP_NAME"
  fi
  usermod -aG "$DOCKER_GROUP_NAME" "$USER_NAME"
else
  echo "Docker socket not found or not a socket!"
fi

# Run the command on behalf of the user
exec su -m "$USER_NAME" -c "$*"