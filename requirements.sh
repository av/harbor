#!/bin/bash

set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MIN_COMPOSE_VERSION="2.23.1"

PLATFORM=""
DISTRO_ID=""
DISTRO_LIKE=""
PKG_MANAGER=""
IS_WSL=false

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    command -v "$1" >/dev/null 2>&1
}

detect_platform() {
    case "$(uname -s)" in
        Linux)
            PLATFORM="linux"
            ;;
        Darwin)
            PLATFORM="macos"
            ;;
        *)
            PLATFORM="unknown"
            ;;
    esac

    if [ "$PLATFORM" = "linux" ]; then
        if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null || [ -n "${WSL_INTEROP:-}" ]; then
            IS_WSL=true
        fi

        if [ -f /etc/os-release ]; then
            DISTRO_ID=$(awk -F= '/^ID=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
            DISTRO_LIKE=$(awk -F= '/^ID_LIKE=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
        fi

        case "$DISTRO_ID" in
            ubuntu|debian)
                PKG_MANAGER="apt"
                ;;
            fedora|rhel|centos|rocky|almalinux)
                PKG_MANAGER="dnf"
                ;;
            arch|manjaro|endeavouros)
                PKG_MANAGER="pacman"
                ;;
            *)
                if echo "$DISTRO_LIKE" | grep -q "debian"; then
                    PKG_MANAGER="apt"
                elif echo "$DISTRO_LIKE" | grep -Eq "rhel|fedora"; then
                    PKG_MANAGER="dnf"
                elif echo "$DISTRO_LIKE" | grep -q "arch"; then
                    PKG_MANAGER="pacman"
                fi
                ;;
        esac
    fi
}

require_supported_platform() {
    if [ "$PLATFORM" = "macos" ]; then
        return 0
    fi

    if [ "$PLATFORM" != "linux" ]; then
        log_error "Unsupported platform: $(uname -s)"
        log_error "Please install Docker, Docker Compose v2 (>= ${MIN_COMPOSE_VERSION}), Git, and curl manually."
        return 1
    fi

    if [ -z "$PKG_MANAGER" ]; then
        log_error "Unsupported Linux distribution (ID='${DISTRO_ID:-unknown}', ID_LIKE='${DISTRO_LIKE:-unknown}')"
        log_error "Please install Docker Engine, docker compose plugin (v2 >= ${MIN_COMPOSE_VERSION}), git, and curl manually."
        return 1
    fi

    return 0
}

apt_install() {
    local missing=()
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via apt: ${missing[*]}"
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    else
        log_info "git and curl are already installed"
    fi

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        local compose_pkg=""
        sudo apt-get update

        if apt-cache show docker-compose-v2 >/dev/null 2>&1; then
            compose_pkg="docker-compose-v2"
        elif apt-cache show docker-compose-plugin >/dev/null 2>&1; then
            compose_pkg="docker-compose-plugin"
        else
            log_error "Neither 'docker-compose-v2' nor 'docker-compose-plugin' is available via apt repositories. Enable the appropriate Docker/Ubuntu repositories or install Docker Compose v2 manually."
            return 1
        fi

        log_info "Installing Docker Engine and Docker Compose via apt (${compose_pkg})"
        sudo apt-get install -y docker.io "${compose_pkg}"
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

dnf_install() {
    local missing=()
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via dnf: ${missing[*]}"
        sudo dnf install -y "${missing[@]}"
    else
        log_info "git and curl are already installed"
    fi

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        log_info "Installing Docker Engine and Docker Compose plugin via dnf"
        sudo dnf install -y docker docker-compose-plugin
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

pacman_install() {
    local missing=()
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via pacman: ${missing[*]}"
        sudo pacman -Sy --noconfirm "${missing[@]}"
    else
        log_info "git and curl are already installed"
    fi

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        log_info "Installing Docker Engine and Docker Compose plugin via pacman"
        sudo pacman -Sy --noconfirm docker docker-compose
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

brew_install() {
    if ! check_command brew; then
        log_error "Homebrew is required on macOS but was not found"
        log_error "Install Homebrew first: https://brew.sh"
        return 1
    fi

    local missing=()
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")
    check_command docker || missing+=("docker")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via brew: ${missing[*]}"
        brew install "${missing[@]}"
    else
        log_info "git, curl, and docker are already installed"
    fi

    if ! docker compose version >/dev/null 2>&1; then
        log_warn "Docker Compose v2 not detected"
        log_warn "Install and start Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/"
    fi
}

ensure_linux_docker_service() {
    if [ "$PLATFORM" != "linux" ] || [ "$IS_WSL" = true ]; then
        return 0
    fi

    if check_command systemctl; then
        if ! systemctl is-enabled docker >/dev/null 2>&1; then
            log_info "Enabling Docker service"
            sudo systemctl enable docker >/dev/null 2>&1 || true
        fi

        if ! systemctl is-active docker >/dev/null 2>&1; then
            log_info "Starting Docker service"
            sudo systemctl start docker || true
        fi
    fi
}

version_to_int() {
    local version="$1"
    local major minor patch
    major=0
    minor=0
    patch=0
    IFS='.' read -r major minor patch <<< "$version"
    printf '%d%03d%03d\n' "$major" "$minor" "$patch"
}

extract_semver_core() {
    local version="$1"
    printf '%s\n' "$version" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1
}

is_compose_modern() {
    local compose_version_raw compose_version semver_core
    compose_version_raw=$(docker compose version --short 2>/dev/null | sed -e 's/-desktop//')
    compose_version=${compose_version_raw#v}

    if [ -z "$compose_version" ]; then
        return 1
    fi

    if [ "$compose_version" = "dev" ]; then
        return 0
    fi

    semver_core=$(extract_semver_core "$compose_version")
    if [ -z "$semver_core" ]; then
        return 0
    fi

    [ "$(version_to_int "$semver_core")" -ge "$(version_to_int "$MIN_COMPOSE_VERSION")" ]
}

verify_docker_access() {
    if ! check_command docker; then
        log_error "Docker is not installed or not in PATH"
        return 1
    fi

    local docker_access_output
    docker_access_output=$(docker info 2>&1)
    if [ $? -eq 0 ]; then
        log_info "Docker daemon is reachable without sudo"
        return 0
    fi

    if echo "$docker_access_output" | grep -qi "permission denied\|got permission denied while trying to connect to the docker daemon socket"; then
        local remediation_user user_in_docker_group add_group_cmd add_user_cmd
        remediation_user="${SUDO_USER:-${USER:-$(id -un 2>/dev/null || echo unknown)}}"
        if [ "$remediation_user" = "root" ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
            remediation_user="$SUDO_USER"
        fi

        user_in_docker_group=false
        if id -nG "$remediation_user" 2>/dev/null | grep -qw docker; then
            user_in_docker_group=true
        fi

        if [ "$user_in_docker_group" = true ]; then
            log_warn "Docker access is blocked in this shell because group membership has not been refreshed yet"
            log_warn "Re-login or run: newgrp docker"
            log_warn "Then run: harbor doctor"
            return 0
        fi

        add_group_cmd="groupadd docker"
        add_user_cmd="usermod -aG docker ${remediation_user}"

        if ! getent group docker >/dev/null 2>&1; then
            if [ "$(id -u)" -eq 0 ]; then
                groupadd docker >/dev/null 2>&1
            elif check_command sudo; then
                sudo groupadd docker >/dev/null 2>&1
            fi
        fi

        if getent group docker >/dev/null 2>&1; then
            if [ "$(id -u)" -eq 0 ]; then
                usermod -aG docker "$remediation_user" >/dev/null 2>&1
            elif check_command sudo; then
                sudo usermod -aG docker "$remediation_user" >/dev/null 2>&1
            else
                false
            fi

            if [ $? -eq 0 ]; then
                log_warn "Added '${remediation_user}' to docker group"
                log_warn "Re-login or run: newgrp docker"
                log_warn "Then run: harbor doctor"
                return 0
            fi
        fi

        log_error "Docker requires elevated privileges for this user"
        log_error "Could not auto-add '${remediation_user}' to docker group"
        log_error "Run: sudo ${add_group_cmd} (if group is missing)"
        log_error "Run: sudo ${add_user_cmd}"
        log_error "Then log out and log back in (or run: newgrp docker)."
    else
        log_error "Docker daemon is not running or not reachable"
        if [ "$IS_WSL" = true ]; then
            log_error "In WSL, start Docker Desktop and enable WSL integration for this distro."
        elif [ "$PLATFORM" = "linux" ]; then
            log_error "Try: sudo systemctl start docker"
        else
            log_error "Start Docker Desktop and retry"
        fi
    fi

    return 1
}

verify_required_tools() {
    local failed=false

    for tool in git curl docker; do
        if check_command "$tool"; then
            log_info "$tool is installed: $($tool --version 2>/dev/null | head -n1)"
        else
            log_error "$tool is not installed"
            failed=true
        fi
    done

    if docker compose version >/dev/null 2>&1; then
        local compose_version
        compose_version=$(docker compose version --short 2>/dev/null)
        log_info "Docker Compose detected: ${compose_version}"
        if ! is_compose_modern; then
            log_error "Docker Compose must be >= ${MIN_COMPOSE_VERSION}. Current: ${compose_version}"
            log_error "Update Docker Compose plugin (Linux) or Docker Desktop (macOS/WSL)."
            failed=true
        fi
    else
        log_error "Docker Compose v2 is not installed or unavailable"
        log_error "Install Docker Compose plugin and retry"
        failed=true
    fi

    verify_docker_access
    local docker_access_status=$?
    if [ $docker_access_status -eq 1 ]; then
        failed=true
    fi

    if [ "$failed" = true ]; then
        return 1
    fi

    return 0
}

check_optional_gpu_support() {
    if check_command nvidia-smi; then
        log_info "NVIDIA GPU detected"
        if check_command nvidia-ctk || check_command nvidia-container-toolkit; then
            log_info "NVIDIA container toolkit detected"
        else
            log_warn "NVIDIA GPU detected but NVIDIA container toolkit is missing (optional)"
        fi
    else
        log_warn "NVIDIA GPU not detected (optional)"
    fi
}

install_requirements() {
    if [ "$IS_WSL" = true ]; then
        log_warn "WSL environment detected"
        log_warn "Preferred setup is Docker Desktop on Windows with WSL integration enabled"
    fi

    case "$PLATFORM:$PKG_MANAGER" in
        macos:)
            brew_install
            ;;
        linux:apt)
            apt_install
            ;;
        linux:dnf)
            dnf_install
            ;;
        linux:pacman)
            pacman_install
            ;;
        *)
            log_error "No installer path for platform='${PLATFORM}' pkg_manager='${PKG_MANAGER}'"
            return 1
            ;;
    esac
}

main() {
    log_info "Detecting platform and package manager"
    detect_platform

    if [ "$PLATFORM" = "linux" ]; then
        log_info "Platform: Linux (distro='${DISTRO_ID:-unknown}', pkg='${PKG_MANAGER:-unknown}')"
    elif [ "$PLATFORM" = "macos" ]; then
        log_info "Platform: macOS"
    fi

    require_supported_platform || exit 1

    install_requirements || exit 1
    ensure_linux_docker_service

    verify_required_tools || exit 1
    check_optional_gpu_support

    if [ "$PLATFORM" = "linux" ]; then
        log_info "If you were added to the docker group, re-login before running Harbor commands."
    fi

    log_info "Dependency setup complete. Run 'harbor doctor' to validate full Harbor readiness."
}

main
