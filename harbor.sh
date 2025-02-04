#!/bin/bash

# Debug output
echo "Current directory: $(pwd)"
echo "Script location: $0"

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Script directory: $SCRIPT_DIR"

# Source common functions with full path
source "$SCRIPT_DIR/harbor/common.sh"

# Debug output for environment
echo "PATH: $PATH"
echo "Command received: $1"

# Command handler
case "$1" in
"doctor")
    h1 "Running Harbor diagnostics..."

    h2 "Checking Docker..."
    check_docker

    h2 "Checking Docker Compose..."
    check_dockercompose

    h2 "Checking active services..."
    "$DOCKER_COMPOSE" ps

    h2 "Checking Harbor home directory..."
    HARBOR_HOME_DIR=$(get_config "HARBOR_HOME_DIR")
    if [ -z "$HARBOR_HOME_DIR" ]; then
        error "HARBOR_HOME_DIR is not set in the configuration."
        exit 1
    fi
    if [ ! -d "$HARBOR_HOME_DIR" ]; then
        error "Harbor home directory does not exist: $HARBOR_HOME_DIR"
        exit 1
    fi
    success "Harbor home directory is set up correctly: $HARBOR_HOME_DIR"

    h2 "Checking default profile..."
    DEFAULT_PROFILE=$(get_config "HARBOR_DEFAULT_PROFILE")
    if [ -z "$DEFAULT_PROFILE" ]; then
        error "HARBOR_DEFAULT_PROFILE is not set in the configuration."
        exit 1
    fi
    PROFILES_DIR=$(get_config "HARBOR_PROFILES_DIR")
    if [ -z "$PROFILES_DIR" ]; then
        error "HARBOR_PROFILES_DIR is not set in the configuration."
        exit 1
    fi
    DEFAULT_PROFILE_PATH="$PROFILES_DIR/$DEFAULT_PROFILE.env"
    if [ ! -f "$DEFAULT_PROFILE_PATH" ]; then
        error "Default profile is missing: $DEFAULT_PROFILE_PATH"
        exit 1
    fi
    if [ ! -r "$DEFAULT_PROFILE_PATH" ]; then
        error "Default profile is not readable: $DEFAULT_PROFILE_PATH"
        exit 1
    fi
    success "Default profile is set up correctly: $DEFAULT_PROFILE_PATH"

    h2 "Checking current profile..."
    CURRENT_PROFILE_PATH="$HARBOR_HOME_DIR/.env"
    if [ ! -f "$CURRENT_PROFILE_PATH" ]; then
        error "Current profile is missing: $CURRENT_PROFILE_PATH"
        exit 1
    fi
    if [ ! -r "$CURRENT_PROFILE_PATH" ]; then
        error "Current profile is not readable: $CURRENT_PROFILE_PATH"
        exit 1
    fi
    success "Current profile is set up correctly: $CURRENT_PROFILE_PATH"

    h2 "Checking CLI link..."
    if [ ! -L "/usr/local/bin/harbor" ]; then
        error "CLI is not linked. Run 'harbor link' to create a symlink."
    else
        success "CLI is linked: /usr/local/bin/harbor -> $(readlink /usr/local/bin/harbor)"
    fi

    h2 "Checking NVIDIA GPU..."
    if ! command -v nvidia-smi &> /dev/null; then
        warn "NVIDIA driver not found. NVIDIA GPU support may not work."
    else
        success "NVIDIA GPU is available"
        nvidia-smi
    fi

    h2 "Checking NVIDIA Container Toolkit..."
    if ! command -v nvidia-container-runtime &> /dev/null; then
        error "NVIDIA Container Toolkit is not installed."
        exit 1
    else
        success "NVIDIA Container Toolkit is installed"
    fi

    success "Diagnostics completed successfully"
    ;;
"logs")
    shift
    h2 "Showing logs..."
    if [ -z "$1" ]; then
        "$DOCKER_COMPOSE" logs --tail=100 -f
    else
        "$DOCKER_COMPOSE" logs --tail=100 -f "$@"
    fi
    ;;
"link")
    h2 "Creating symbolic link to Harbor CLI..."
    if ln -sf "$SCRIPT_DIR/harbor.sh" "/usr/local/bin/harbor"; then
        success "Successfully created symbolic link: /usr/local/bin/harbor -> $SCRIPT_DIR/harbor.sh"
    else
        error "Failed to create symbolic link. Error: $?"
        exit 1
    fi
    ;;
*)
    h1 "Harbor Stack Manager"
    echo "Usage: harbor [command]"
    echo ""
    echo "Commands:"
    echo "  doctor    - Run diagnostics and check system requirements"
    echo "  logs      - Show logs from all containers (or specify a service name)"
    echo "  link      - Create a symbolic link to the Harbor CLI"
    ;;
esac
