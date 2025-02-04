#!/bin/bash

# Set Harbor home directory
HARBOR_HOME="/mnt/c/Users/CLD's Tower/AppData/Roaming/npm/node_modules/@avcodes/harbor"
PROFILES_DIR="$HARBOR_HOME/profiles"

# Create required directories
sudo mkdir -p "$PROFILES_DIR"

# Create default profile with WSL prefixes for Docker commands
cat > "$PROFILES_DIR/default.env" << 'EOL'
HARBOR_DOCKER_COMPOSE_CMD="wsl docker compose"
HARBOR_DOCKER_CMD="wsl docker"
HARBOR_HOME_DIR="$HARBOR_HOME"
HARBOR_PROFILES_DIR="$PROFILES_DIR"
HARBOR_DEFAULT_PROFILE="default"
HARBOR_NETWORK_NAME="harbor-network"
EOL

# Copy default profile to current profile
cp "$PROFILES_DIR/default.env" "$HARBOR_HOME/.env"

# Set proper permissions
sudo chown -R $(whoami) "$HARBOR_HOME"
chmod 644 "$PROFILES_DIR/default.env"
chmod 644 "$HARBOR_HOME/.env"

# Create network if it doesn't exist using WSL prefix
wsl docker network inspect harbor-network >/dev/null 2>&1 || wsl docker network create harbor-network

# Ensure /usr/local/bin/harbor is properly set up
# Remove any existing symlink or file before creating a new one
if [ -L "/usr/local/bin/harbor" ] || [ -f "/usr/local/bin/harbor" ]; then
  sudo rm -f "/usr/local/bin/harbor"
fi
sudo ln -sf "$HARBOR_HOME/harbor.sh" "/usr/local/bin/harbor"

# Make harbor.sh executable
chmod +x "$HARBOR_HOME/harbor.sh"

echo "Harbor setup completed. Running diagnostics..."

# Run diagnostics with explicit nvidia-smi check
"$HARBOR_HOME/harbor.sh" doctor

# Link the CLI
"$HARBOR_HOME/harbor.sh" link