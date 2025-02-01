#!/bin/bash

# This file is to trick Nexa that Nvidia CUDA
# is available during the docker install.

# Nvidia Container Runtime mounts nvidia-smi and other
# nvidia utils at runtime - they are never available at
# build time even on official CUDA images.

# Hence, below, aka "trust me bro"

# Our base iamge
IMAGE=${HARBOR_NEXA_IMAGE}
if [[ $IMAGE == *"nvidia"* ]]; then
  echo "Writing fake nvidia-smi file"
  echo "echo 'CUDA Version: 12.4.0'" > /usr/bin/nvidia-smi
  chmod +x /usr/bin/nvidia-smi

  # Let's test it
  nvidia-smi
else
  echo "Not an Nvidia image, skipping..."
fi