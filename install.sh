#!/bin/bash

set -e

# This is an installation script for the Harbor project.
# See https://github.com/av/harbor for more information.

# ========================================

HARBOR_INSTALL_PATH="${HOME}/.harbor"
HARBOR_REPO_URL="https://github.com/av/harbor.git"
HARBOR_RELEASE_URL="https://api.github.com/repos/av/harbor/releases/latest"
HARBOR_VERSION=""

# ========================================

resolve_harbor_version() {
  curl -s "$HARBOR_RELEASE_URL" | sed -n 's/.*"tag_name": "\(.*\)".*/\1/p'
}

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
    git fetch --all --tags
    git checkout "tags/$HARBOR_VERSION"
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

  echo "Resolving version..."
  HARBOR_VERSION=$(resolve_harbor_version)

  if [ -z "$HARBOR_VERSION" ]; then
    echo "Error: Unable to resolve Harbor version."
    exit 1
  else
    echo "Resolved Harbor version: $HARBOR_VERSION"
  fi

  echo "Starting installation..."
  install_or_update_project

  ./harbor.sh -v
  ./harbor.sh ln

  echo "Installation complete."
}

main