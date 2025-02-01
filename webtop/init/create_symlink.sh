#!/bin/bash


# Check if the source file exists
if [ ! -f /harbor/harbor.sh ]; then
  echo "Error: /harbor/harbor.sh not found!"
  exit 1
fi

# Create the symbolic link
ln -sf /harbor/harbor.sh /config/.local/bin/harbor

# Confirm the link was created
if [ -L /config/.local/bin/harbor ]; then
  echo "Symbolic link created successfully: /config/.local/bin/harbor -> /harbor/harbor.sh"
else
  echo "Failed to create symbolic link!"
  exit 1
fi

