#!/bin/bash

if [ -z "$HARBOR_HOME" ]; then
  echo "Error: HARBOR_HOME is not set!"
  exit 1
fi

CLI_PATH="$HARBOR_HOME/harbor.sh"

# Check if the source file exists
if [ ! -f "$CLI_PATH" ]; then
  echo "Error: $CLI_PATH not found!"
  exit 1
fi

# Create the symbolic link
ln -sf "$CLI_PATH" /config/.local/bin/harbor

# Confirm the link was created
if [ -L /config/.local/bin/harbor ]; then
  echo "Symbolic link created successfully: /config/.local/bin/harbor -> $CLI_PATH"
else
  echo "Failed to create symbolic link!"
  exit 1
fi

