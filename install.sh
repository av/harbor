#!/bin/bash

set -e

# ========================================

HARBOR_INSTALL_PATH="${HOME}/.harbor"
HARBOR_REPO_URL="https://github.com/av/harbor.git"
HARBOR_VERSION="0.1.1"

# ========================================

check_dependencies() {
  if ! command -v docker >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
    echo "Error: Docker or Git not found. Please install missing dependencies."
    exit 1
  fi
}

install_or_update_project() {
  if [ -d "$HARBOR_INSTALL_PATH" ]; then
    echo "Existing installation found. Updating..."
    cd "$HARBOR_INSTALL_PATH"
    git pull
  else
    echo "Cloning project repository..."
    git clone --depth 1 --branch "$HARBOR_VERSION" "$HARBOR_REPO_URL" "$HARBOR_INSTALL_PATH"
    cd "$HARBOR_INSTALL_PATH"
  fi
}

main() {
  echo "Installing Harbor."

  echo "Checking dependencies..."
  check_dependencies

  echo "Starting installation..."
  install_or_update_project

  ./harbor.sh -v
  ./harbor.sh ln

  echo "Installation complete."
}

main