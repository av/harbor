#!/bin/bash

set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MIN_COMPOSE_VERSION="2.23.1"
HOMEBREW_INSTALL_URL="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"

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

# Run a command with privilege escalation (sudo if needed and available).
# If already root, runs the command directly. If sudo is unavailable and
# not root, logs a clear error and returns 1.
run_privileged() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif check_command sudo; then
        sudo "$@"
    else
        log_error "Root privileges required but 'sudo' is not installed and you are not root."
        log_error "Failed command: $*"
        log_error "Either install sudo, run this script as root, or install the dependencies manually."
        return 1
    fi
}

# Validate that privileged commands will work before starting installs.
# In non-interactive environments (no TTY, piped stdin), sudo may hang or
# fail silently. This catches the problem early with a clear message.
preflight_privilege_check() {
    if [ "$(id -u)" -eq 0 ]; then
        return 0
    fi

    if ! check_command sudo; then
        log_error "'sudo' is not installed and you are not root."
        log_error "Install sudo or run this script as root."
        return 1
    fi

    # Attempt a no-op sudo to validate credentials/cached session.
    # Use -n (non-interactive) first; if that fails, try regular sudo
    # which may prompt for a password (acceptable if TTY is available).
    if sudo -n true 2>/dev/null; then
        return 0
    fi

    if [ -t 0 ]; then
        # TTY available — sudo can prompt for password
        log_info "Sudo access required. You may be prompted for your password."
        if ! sudo true; then
            log_error "Failed to obtain sudo access. Cannot install dependencies."
            return 1
        fi
    else
        # No TTY — sudo cannot prompt interactively
        log_error "Sudo requires a password but no terminal is available for prompting."
        log_error "Run this script in an interactive terminal, or pre-authorize sudo (e.g., 'sudo -v')."
        return 1
    fi

    return 0
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
            alpine)
                PKG_MANAGER="apk"
                ;;
            *)
                if echo "$DISTRO_LIKE" | grep -q "debian"; then
                    PKG_MANAGER="apt"
                elif echo "$DISTRO_LIKE" | grep -Eq "rhel|fedora"; then
                    PKG_MANAGER="dnf"
                elif echo "$DISTRO_LIKE" | grep -q "arch"; then
                    PKG_MANAGER="pacman"
                elif echo "$DISTRO_LIKE" | grep -q "alpine"; then
                    PKG_MANAGER="apk"
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
    local need_docker=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        need_docker=true
    fi

    # Single apt-get update if anything needs installing
    if [ ${#missing[@]} -gt 0 ] || [ "$need_docker" = true ]; then
        log_info "Refreshing apt package index"
        run_privileged apt-get update || return 1
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via apt: ${missing[*]}"
        run_privileged apt-get install -y "${missing[@]}" || return 1
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_docker" = true ]; then
        local compose_pkg=""

        if apt-cache show docker-compose-v2 >/dev/null 2>&1; then
            compose_pkg="docker-compose-v2"
        elif apt-cache show docker-compose-plugin >/dev/null 2>&1; then
            compose_pkg="docker-compose-plugin"
        else
            log_error "Neither 'docker-compose-v2' nor 'docker-compose-plugin' is available via apt repositories."
            log_error "Enable the Docker repository: https://docs.docker.com/engine/install/"
            log_error "Or install Docker Compose v2 manually."
            return 1
        fi

        log_info "Installing Docker Engine and Docker Compose via apt (${compose_pkg})"
        run_privileged apt-get install -y docker.io "${compose_pkg}" || return 1
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

dnf_install() {
    local missing=()
    local need_docker=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        need_docker=true
    fi

    # Refresh dnf metadata if anything needs installing (stale cache causes
    # silent lookup failures with "dnf list --available")
    if [ ${#missing[@]} -gt 0 ] || [ "$need_docker" = true ]; then
        log_info "Refreshing dnf package metadata"
        run_privileged dnf makecache --refresh -q 2>/dev/null || true
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via dnf: ${missing[*]}"
        run_privileged dnf install -y "${missing[@]}" || return 1
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_docker" = true ]; then
        local compose_pkg="" docker_pkg=""

        if dnf list --available docker-compose-plugin 2>/dev/null | grep -q docker-compose-plugin; then
            compose_pkg="docker-compose-plugin"
        elif dnf list --available docker-compose 2>/dev/null | grep -q docker-compose; then
            compose_pkg="docker-compose"
        else
            log_error "Neither 'docker-compose-plugin' nor 'docker-compose' is available via dnf."
            log_error "Enable the Docker repository: https://docs.docker.com/engine/install/fedora/"
            log_error "Or install Docker Compose v2 manually."
            return 1
        fi

        # Prefer docker-ce (Docker's official package) over moby-engine.
        # moby-engine was removed from Fedora 39+; docker-ce requires the
        # Docker repo to be enabled.
        if dnf list --available docker-ce 2>/dev/null | grep -q docker-ce; then
            docker_pkg="docker-ce"
        elif dnf list --available moby-engine 2>/dev/null | grep -q moby-engine; then
            docker_pkg="moby-engine"
        else
            log_error "Neither 'docker-ce' nor 'moby-engine' is available via dnf."
            log_error "Enable the Docker repository: https://docs.docker.com/engine/install/fedora/"
            return 1
        fi

        log_info "Installing Docker Engine and Docker Compose via dnf (${docker_pkg}, ${compose_pkg})"
        run_privileged dnf install -y "${docker_pkg}" "${compose_pkg}" || return 1
    else
        log_info "Docker and Docker Compose are already installed"
    fi
}

pacman_install() {
    local missing=()
    local need_docker=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        need_docker=true
    fi

    # Refresh package database before installing (stale db causes
    # "target not found" errors that confuse users)
    if [ ${#missing[@]} -gt 0 ] || [ "$need_docker" = true ]; then
        log_info "Refreshing pacman package database"
        run_privileged pacman -Sy --noconfirm || return 1
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via pacman: ${missing[*]}"
        run_privileged pacman -S --noconfirm --needed "${missing[@]}" || return 1
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_docker" = true ]; then
        log_info "Installing Docker Engine and Docker Compose plugin via pacman"
        run_privileged pacman -S --noconfirm --needed docker docker-compose || return 1
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

apk_install() {
    # Alpine's community repo provides `docker` and `docker-compose` (v2).
    # We also ensure `bash` is present — harbor.sh uses bash-only constructs.
    local missing=()
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")
    check_command bash || missing+=("bash")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via apk: ${missing[*]}"
        run_privileged apk add --no-cache "${missing[@]}" || return 1
    else
        log_info "git, curl, and bash are already installed"
    fi

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        log_info "Installing Docker Engine and Docker Compose plugin via apk"
        run_privileged apk add --no-cache docker docker-cli-compose || return 1
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

load_homebrew_shellenv() {
    local brew_path

    if check_command brew; then
        return 0
    fi

    for brew_path in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$brew_path" ]; then
            eval "$("$brew_path" shellenv)"
            return 0
        fi
    done

    return 1
}

install_homebrew() {
    log_info "Homebrew is not installed. Installing Homebrew through the official installer."
    /bin/bash -c "$(curl -fsSL "$HOMEBREW_INSTALL_URL")" || return 1
    load_homebrew_shellenv
}

start_macos_docker_desktop() {
    if [ "$PLATFORM" != "macos" ] || ! check_command open; then
        return 1
    fi

    log_info "Starting Docker Desktop"
    open -g -a Docker >/dev/null 2>&1 || open -g -a "Docker Desktop" >/dev/null 2>&1
}

wait_for_docker_access() {
    local timeout_seconds="${1:-180}"
    local deadline=$((SECONDS + timeout_seconds))

    while [ "$SECONDS" -lt "$deadline" ]; do
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        log_info "Waiting for Docker daemon"
        sleep 5
    done

    return 1
}

brew_install() {
    if ! load_homebrew_shellenv; then
        install_homebrew || {
            log_error "Homebrew installation did not complete"
            log_error "Install Homebrew from https://brew.sh, then retry Harbor setup."
            return 1
        }
    fi

    local missing=()
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via brew: ${missing[*]}"
        brew install "${missing[@]}" || return 1
    else
        log_info "git and curl are already installed"
    fi

    if ! check_command docker; then
        log_info "Installing Docker Desktop via Homebrew cask"
        brew install --cask docker || return 1
    else
        log_info "docker CLI is already installed"
    fi

    if ! docker compose version >/dev/null 2>&1; then
        log_warn "Docker Compose v2 not detected"
        log_warn "Install and start Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/"
    fi
}

ensure_linux_docker_service() {
    if [ "$PLATFORM" != "linux" ]; then
        return 0
    fi

    # In WSL, Docker can come from two sources:
    # 1. Docker Desktop on Windows with WSL integration (no service needed)
    # 2. Docker Engine installed natively in WSL2 with systemd
    # Only skip service management if Docker is already reachable (case 1).
    if [ "$IS_WSL" = true ]; then
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        # Docker not reachable in WSL — fall through to try systemd if available
        if ! check_command systemctl || ! systemctl is-system-running >/dev/null 2>&1; then
            log_warn "Docker is not reachable in WSL and systemd is not active."
            log_warn "Either enable Docker Desktop WSL integration, or enable systemd in WSL:"
            log_warn "  Add [boot] systemd=true to /etc/wsl.conf and restart WSL."
            return 0
        fi
    fi

    if check_command systemctl && systemctl is-system-running >/dev/null 2>&1; then
        if ! systemctl is-enabled docker >/dev/null 2>&1; then
            log_info "Enabling Docker service"
            run_privileged systemctl enable docker >/dev/null 2>&1 || true
        fi

        if ! systemctl is-active docker >/dev/null 2>&1; then
            log_info "Starting Docker service"
            run_privileged systemctl start docker || true
            wait_for_docker_access 30
        fi
    elif check_command rc-service && check_command rc-update; then
        log_info "Enabling and starting Docker service (OpenRC)"
        run_privileged rc-update add docker default >/dev/null 2>&1 || true
        run_privileged rc-service docker start >/dev/null 2>&1 || true
        wait_for_docker_access 30
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
    if docker_access_output=$(docker info 2>&1); then
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
            run_privileged groupadd docker >/dev/null 2>&1 || true
        fi

        if getent group docker >/dev/null 2>&1; then
            local add_ok=false
            if run_privileged usermod -aG docker "$remediation_user" >/dev/null 2>&1; then
                add_ok=true
            fi

            if [ "$add_ok" = true ]; then
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
        if [ "$PLATFORM" = "macos" ]; then
            log_warn "Docker daemon is not running"
            if start_macos_docker_desktop && wait_for_docker_access 180; then
                log_info "Docker daemon is reachable"
                return 0
            fi
            log_warn "Start Docker Desktop (or an alternative like OrbStack) before using Harbor services"
            return 0
        fi
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
        linux:apk)
            apk_install
            ;;
        *)
            log_error "No installer path for platform='${PLATFORM}' pkg_manager='${PKG_MANAGER}'"
            return 1
            ;;
    esac
}

setup_stage() {
    echo "HARBOR_SETUP_STAGE=$1"
}

main() {
    setup_stage "checking-platform"
    log_info "Detecting platform and package manager"
    detect_platform

    if [ "$PLATFORM" = "linux" ]; then
        log_info "Platform: Linux (distro='${DISTRO_ID:-unknown}', pkg='${PKG_MANAGER:-unknown}')"
    elif [ "$PLATFORM" = "macos" ]; then
        log_info "Platform: macOS"
    fi

    require_supported_platform || exit 1

    setup_stage "installing-prerequisites"
    # On macOS, brew doesn't need sudo; on Linux, verify sudo works before
    # attempting any package installs (catches no-TTY / no-sudo early).
    if [ "$PLATFORM" = "linux" ]; then
        preflight_privilege_check || exit 1
    fi
    install_requirements || exit 1
    ensure_linux_docker_service

    setup_stage "checking-prerequisites"
    verify_required_tools || exit 1
    check_optional_gpu_support

    if [ "$PLATFORM" = "linux" ] && [ "${HARBOR_APP:-}" != "1" ]; then
        log_info "If you were added to the docker group, re-login before running Harbor commands."
    fi

    setup_stage "ready"
    if [ "${HARBOR_APP:-}" = "1" ]; then
        log_info "Dependency setup complete."
    else
        log_info "Dependency setup complete. Run 'harbor doctor' to validate full Harbor readiness."
    fi
}

main
