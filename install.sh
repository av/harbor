#!/bin/bash

set -e

# This is an installation script for the Harbor project.
# See https://github.com/av/harbor for more information.

# ========================================

HARBOR_INSTALL_PATH="${HARBOR_INSTALL_PATH:-${HOME}/.harbor}"
HARBOR_REPO_URL="${HARBOR_REPO_URL:-https://github.com/av/harbor.git}"
HARBOR_RELEASE_URL="${HARBOR_RELEASE_URL:-https://api.github.com/repos/av/harbor/releases/latest}"
HARBOR_REQUIREMENTS_URL="${HARBOR_REQUIREMENTS_URL:-https://raw.githubusercontent.com/av/harbor/refs/heads/main/requirements.sh}"
HARBOR_REQUIREMENTS_PATH="${HARBOR_REQUIREMENTS_PATH:-}"
HARBOR_INSTALL_SOURCE_PATH="${HARBOR_INSTALL_SOURCE_PATH:-}"
HARBOR_VERSION="${HARBOR_INSTALL_VERSION:-}"
INSTALL_REQUIREMENTS=true

# ========================================

setup_stage() {
  echo "HARBOR_SETUP_STAGE=$1"
}

resolve_harbor_version() {
  curl -s "$HARBOR_RELEASE_URL" | sed -n 's/.*"tag_name": "\(.*\)".*/\1/p'
}

print_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install Harbor from the latest release.
Run with options from a pipe as: bash -s -- [OPTIONS]

Options:
  --skip-requirements      Skip automatic dependency installation
  --install-requirements   (no-op, kept for backward compatibility)
  --source-path PATH       Install from a local Harbor source tree
  --requirements-path PATH Run requirements from a local requirements.sh
  --version VERSION        Install a specific Harbor version or tag
  -h, --help               Show this help message and exit
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --skip-requirements)
        INSTALL_REQUIREMENTS=false
        ;;
      --install-requirements|--hands-off)
        ;;
      --source-path)
        shift
        if [ -z "${1:-}" ]; then
          echo "Error: --source-path requires a path"
          exit 1
        fi
        HARBOR_INSTALL_SOURCE_PATH="$1"
        ;;
      --requirements-path)
        shift
        if [ -z "${1:-}" ]; then
          echo "Error: --requirements-path requires a path"
          exit 1
        fi
        HARBOR_REQUIREMENTS_PATH="$1"
        ;;
      --version)
        shift
        if [ -z "${1:-}" ]; then
          echo "Error: --version requires a version"
          exit 1
        fi
        HARBOR_VERSION="$1"
        ;;
      -h|--help)
        print_help
        exit 0
        ;;
      *)
        echo "Error: Unknown option: $1"
        echo
        print_help
        exit 1
        ;;
    esac
    shift
  done
}

install_or_update_project() {
  if [ -n "$HARBOR_INSTALL_SOURCE_PATH" ]; then
    if [ ! -d "$HARBOR_INSTALL_SOURCE_PATH" ]; then
      echo "Error: Local source path does not exist: $HARBOR_INSTALL_SOURCE_PATH"
      exit 1
    fi

    echo "Installing from local source path: $HARBOR_INSTALL_SOURCE_PATH"
    rm -rf "$HARBOR_INSTALL_PATH"
    mkdir -p "$HARBOR_INSTALL_PATH"
    (
      cd "$HARBOR_INSTALL_SOURCE_PATH"
      tar \
        --exclude='./.git' \
        --exclude='./.env' \
        --exclude='./tests/artifacts' \
        -cf - .
    ) | tar -C "$HARBOR_INSTALL_PATH" -xf -
    cd "$HARBOR_INSTALL_PATH"
    return 0
  fi

  if [ -d "$HARBOR_INSTALL_PATH" ]; then
    echo "Existing installation found. Updating..."
    cd "$HARBOR_INSTALL_PATH"
    git fetch --depth 1 origin "+refs/tags/$HARBOR_VERSION:refs/tags/$HARBOR_VERSION"
    git checkout "tags/$HARBOR_VERSION"
  else
    echo "Cloning project repository..."
    git clone --depth 1 --branch "$HARBOR_VERSION" "$HARBOR_REPO_URL" "$HARBOR_INSTALL_PATH"
    cd "$HARBOR_INSTALL_PATH"
  fi
}

doctor_requires_refresh() {
  printf '%s\n' "$1" | grep -qi \
    "Docker requires sudo\|docker group\|newgrp docker\|re-login\|permission denied"
}

doctor_requires_blocked() {
  printf '%s\n' "$1" | grep -qi \
    "Docker daemon is not running\|Docker daemon is not.*reachable\|Please start Docker\|Cannot connect to the Docker daemon\|Start Docker Desktop"
}

main() {
  parse_args "$@"

  setup_stage "checking-platform"
  echo "Installing Harbor."

  if [ "$INSTALL_REQUIREMENTS" = true ]; then
    setup_stage "installing-prerequisites"
    echo "Installing requirements..."
    if [ -n "$HARBOR_REQUIREMENTS_PATH" ]; then
      if ! bash "$HARBOR_REQUIREMENTS_PATH"; then
        echo "Error: Failed to execute requirements installer at $HARBOR_REQUIREMENTS_PATH"
        exit 1
      fi
    else
      if ! (set -o pipefail; curl -fsSL "$HARBOR_REQUIREMENTS_URL" | bash); then
        echo "Error: Failed to download or execute requirements installer from $HARBOR_REQUIREMENTS_URL"
        exit 1
      fi
    fi
  fi

  setup_stage "installing-cli"
  echo "Resolving version..."
  if [ -z "$HARBOR_VERSION" ]; then
    if [ -n "$HARBOR_INSTALL_SOURCE_PATH" ]; then
      HARBOR_VERSION="source"
    else
      HARBOR_VERSION=$(resolve_harbor_version)
    fi
  fi

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

  echo ""
  setup_stage "verifying-cli"
  if doctor_output=$(./harbor.sh doctor 2>&1); then
    printf '%s\n' "$doctor_output"
  else
    printf '%s\n' "$doctor_output"
    if doctor_requires_refresh "$doctor_output"; then
      setup_stage "refresh-required"
      echo "Harbor CLI is installed, but Docker access needs a refreshed shell session."
      echo "Re-login or run 'newgrp docker', then retry Harbor App setup."
      exit 1
    fi
    if doctor_requires_blocked "$doctor_output"; then
      setup_stage "blocked"
      echo "Harbor CLI is installed, but Docker is not reachable."
      echo "Start Docker Desktop or the Docker daemon, then retry Harbor App setup."
      exit 1
    fi
    setup_stage "failed"
    echo "Error: Harbor verification failed. Resolve the doctor errors above, then retry setup."
    exit 1
  fi
  setup_stage "ready"
  echo "Installation complete."
  echo "Restart your shell, then run 'harbor doctor' to verify your setup."
}

main "$@"
