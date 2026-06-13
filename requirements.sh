#!/bin/bash

# Guard: requirements.sh uses bash-only features (arrays, +=, process
# substitution). Running with sh/dash produces a cryptic "Bad substitution"
# on the BASH_VERSINFO check below. Detect and bail early with guidance.
# shellcheck disable=SC2128
if [ -z "${BASH_VERSION:-}" ]; then
    _current_shell=$(ps -p $$ -o comm= 2>/dev/null || echo "unknown shell")
    echo "Error: requirements.sh requires bash, but is running under ${_current_shell}." >&2
    echo "Please run:  bash requirements.sh" >&2
    echo "         or: curl -fsSL <url> | bash" >&2
    exit 1
fi

# Enable nounset only on bash >= 4.4. Older versions (notably macOS's
# bash 3.2) treat empty arrays as "unbound variable" under set -u,
# crashing the script when git/curl are already installed (empty missing array).
if [ "${BASH_VERSINFO[0]:-0}" -gt 4 ] || \
   { [ "${BASH_VERSINFO[0]:-0}" -eq 4 ] && [ "${BASH_VERSINFO[1]:-0}" -ge 4 ]; }; then
    set -u
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MIN_COMPOSE_VERSION="2.23.1"
HOMEBREW_INSTALL_URL="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"

PLATFORM=""
DISTRO_ID=""
DISTRO_LIKE=""
DISTRO_VARIANT=""
PKG_MANAGER=""
IS_WSL=false
WSL_VERSION=""
IS_IMMUTABLE=false

log_info() {
    printf '%b[INFO]%b %s\n' "$GREEN" "$NC" "$1"
}

log_warn() {
    printf '%b[WARN]%b %s\n' "$YELLOW" "$NC" "$1"
}

log_error() {
    printf '%b[ERROR]%b %s\n' "$RED" "$NC" "$1"
}

check_command() {
    command -v "$1" >/dev/null 2>&1
}

# Run a command with a timeout. Uses GNU timeout if available, falls back to
# a perl alarm-based approach, and runs without a time limit if neither exists.
_with_timeout() {
    local secs="$1"; shift
    if check_command timeout; then
        timeout "$secs" "$@"
        return $?
    elif check_command perl; then
        perl -e '
            my $t=shift @ARGV;
            my $pid=fork;
            if(!$pid){exec @ARGV;die "exec: $!"}
            $SIG{ALRM}=sub{kill 15,$pid;exit 124};
            alarm $t;
            waitpid $pid,0;
            exit($?>>8)
        ' "$secs" "$@"
        return $?
    else
        "$@"
        return $?
    fi
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

    if [ -c /dev/tty ]; then
        # TTY available — sudo can prompt for password (via /dev/tty, not stdin)
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
            # Detect WSL version: WSL2 has a real Linux kernel (microsoft-standard),
            # WSL1 has a translation layer (Microsoft). WSL_INTEROP only exists in WSL2.
            if [ -n "${WSL_INTEROP:-}" ]; then
                WSL_VERSION="2"
            elif grep -qi "microsoft-standard\|microsoft-WSL2" /proc/version 2>/dev/null; then
                WSL_VERSION="2"
            else
                WSL_VERSION="1"
            fi
        fi

        if [ -f /etc/os-release ]; then
            DISTRO_ID=$(awk -F= '/^ID=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
            DISTRO_LIKE=$(awk -F= '/^ID_LIKE=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
            DISTRO_VARIANT=$(awk -F= '/^VARIANT_ID=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
        fi

        # Detect immutable/OSTree-based distros where dnf/apt install does
        # not work (Fedora Silverblue/Kinoite, Fedora CoreOS, Fedora IoT,
        # RHEL for Edge, Universal Blue, etc.)
        if [ -n "$DISTRO_VARIANT" ]; then
            case "$DISTRO_VARIANT" in
                silverblue|kinoite|sericea|onyx|coreos|iot)
                    IS_IMMUTABLE=true
                    ;;
            esac
        fi
        # openSUSE MicroOS is an immutable distro (uses transactional-update,
        # not zypper directly). Its DISTRO_ID is "opensuse-microos".
        if [ "$IS_IMMUTABLE" = false ] && [ "$DISTRO_ID" = "opensuse-microos" ]; then
            IS_IMMUTABLE=true
        fi
        # Also detect via rpm-ostree presence (catches variants we don't
        # list above, and custom OSTree-based images)
        if [ "$IS_IMMUTABLE" = false ] && check_command rpm-ostree && [ -d /ostree ]; then
            IS_IMMUTABLE=true
        fi
        # Detect transactional-update (openSUSE MicroOS, SLE Micro) as immutable
        if [ "$IS_IMMUTABLE" = false ] && check_command transactional-update; then
            IS_IMMUTABLE=true
        fi

        case "$DISTRO_ID" in
            ubuntu|debian)
                PKG_MANAGER="apt"
                ;;
            fedora|rhel|centos|rocky|almalinux)
                PKG_MANAGER="dnf"
                ;;
            opensuse-leap|opensuse-tumbleweed|sles|sled)
                PKG_MANAGER="zypper"
                ;;
            arch|manjaro|endeavouros)
                PKG_MANAGER="pacman"
                ;;
            alpine)
                PKG_MANAGER="apk"
                ;;
            *)
                if echo "$DISTRO_LIKE" | grep -Eq "debian|ubuntu"; then
                    PKG_MANAGER="apt"
                elif echo "$DISTRO_LIKE" | grep -Eq "rhel|fedora"; then
                    PKG_MANAGER="dnf"
                elif echo "$DISTRO_LIKE" | grep -Eq "suse|opensuse"; then
                    PKG_MANAGER="zypper"
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
        log_error "Docker install docs: https://docs.docker.com/engine/install/"
        log_error "Then retry with: curl ... | bash -s -- --skip-requirements"
        return 1
    fi

    return 0
}

apt_install() {
    local missing=()
    local need_engine=false
    local need_compose=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker; then
        need_engine=true
        need_compose=true
    elif ! docker compose version >/dev/null 2>&1; then
        need_compose=true
    fi

    # In WSL with Docker Desktop integration, Docker is provided by the
    # Windows host. Installing docker.io/docker-ce creates conflicts.
    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        if is_wsl_docker_desktop; then
            log_info "Docker is provided by Docker Desktop (WSL integration) — skipping package install"
            need_engine=false
            need_compose=false
        fi
    fi

    # Single apt-get update if anything needs installing
    if [ ${#missing[@]} -gt 0 ] || [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        log_info "Refreshing apt package index"
        run_privileged apt-get update || \
            log_warn "apt-get update had errors (possibly a stale third-party PPA); continuing — install steps will report any real failures."
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via apt: ${missing[*]}"
        if ! run_privileged apt-get install -y "${missing[@]}"; then
            log_error "Failed to install ${missing[*]} via apt."
            log_error "Try running 'sudo apt-get install -y ${missing[*]}' manually to see detailed errors."
            return 1
        fi
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        local compose_pkg="" docker_pkg=""

        if [ "$need_compose" = true ]; then
            if apt-cache show docker-compose-v2 2>/dev/null | grep -q '^Package:'; then
                compose_pkg="docker-compose-v2"
            elif apt-cache show docker-compose-plugin 2>/dev/null | grep -q '^Package:'; then
                compose_pkg="docker-compose-plugin"
            else
                log_error "Neither 'docker-compose-v2' nor 'docker-compose-plugin' is available via apt repositories."
                log_error "Enable the Docker repository: https://docs.docker.com/engine/install/"
                log_error "Or install Docker Compose v2 manually."
                return 1
            fi
        fi

        if [ "$need_engine" = true ]; then
            # Prefer docker-ce (Docker's official package) if available;
            # fall back to docker.io (distro package).
            if apt-cache show docker-ce 2>/dev/null | grep -q '^Package:'; then
                docker_pkg="docker-ce"
            else
                docker_pkg="docker.io"
            fi

            local apt_pkgs=("${docker_pkg}")
            if [ -n "$compose_pkg" ]; then
                apt_pkgs+=("${compose_pkg}")
            fi
            log_info "Installing Docker packages via apt: ${apt_pkgs[*]}"
            if ! run_privileged apt-get install -y "${apt_pkgs[@]}"; then
                log_error "Failed to install Docker packages via apt."
                log_error "Try running 'sudo apt-get install -y ${apt_pkgs[*]}' manually."
                log_error "If packages are missing, add the Docker repository: https://docs.docker.com/engine/install/"
                return 1
            fi
        else
            log_info "Installing Docker Compose plugin via apt (${compose_pkg})"
            if ! run_privileged apt-get install -y "${compose_pkg}"; then
                log_error "Failed to install ${compose_pkg} via apt."
                log_error "Try running 'sudo apt-get install -y ${compose_pkg}' manually."
                log_error "If packages are missing, add the Docker repository: https://docs.docker.com/engine/install/"
                return 1
            fi
        fi
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

# Return the correct Docker Engine install URL for the current dnf-based distro.
# Fedora, CentOS, and RHEL each have their own install page.
_dnf_docker_install_url() {
    case "$DISTRO_ID" in
        centos)
            echo "https://docs.docker.com/engine/install/centos/"
            ;;
        rhel|rocky|almalinux)
            echo "https://docs.docker.com/engine/install/rhel/"
            ;;
        *)
            # Fedora and anything else that uses dnf
            echo "https://docs.docker.com/engine/install/fedora/"
            ;;
    esac
}

dnf_install() {
    local missing=()
    local need_engine=false
    local need_compose=false
    local docker_url
    docker_url=$(_dnf_docker_install_url)
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker; then
        need_engine=true
        need_compose=true
    elif ! docker compose version >/dev/null 2>&1; then
        need_compose=true
    fi

    # In WSL with Docker Desktop integration, Docker is provided by the
    # Windows host. Installing docker-ce/moby-engine creates conflicts.
    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        if is_wsl_docker_desktop; then
            log_info "Docker is provided by Docker Desktop (WSL integration) — skipping package install"
            need_engine=false
            need_compose=false
        fi
    fi

    # Refresh dnf metadata if anything needs installing (stale cache causes
    # silent lookup failures with "dnf list --available")
    if [ ${#missing[@]} -gt 0 ] || [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        log_info "Refreshing dnf package metadata"
        run_privileged dnf makecache --refresh -q 2>/dev/null || true
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via dnf: ${missing[*]}"
        if ! run_privileged dnf install -y "${missing[@]}"; then
            log_error "Failed to install ${missing[*]} via dnf."
            log_error "Try running 'sudo dnf install -y ${missing[*]}' manually to see detailed errors."
            return 1
        fi
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        local docker_pkg=""

        if [ "$need_engine" = true ]; then
            # Check already-installed packages first (rpm -q), then fall back
            # to --available. dnf list --available excludes installed packages,
            # so relying on it alone misses an already-installed docker-ce.
            # Anchor grep to "^pkg." to avoid false positives on dnf5 where
            # advisory or suggestion text can contain the package name.
            if rpm -q docker-ce >/dev/null 2>&1; then
                docker_pkg="docker-ce"
            elif dnf list --available docker-ce 2>/dev/null | grep -q '^docker-ce\.'; then
                docker_pkg="docker-ce"
            elif rpm -q moby-engine >/dev/null 2>&1; then
                docker_pkg="moby-engine"
            elif dnf list --available moby-engine 2>/dev/null | grep -q '^moby-engine\.'; then
                docker_pkg="moby-engine"
            else
                log_error "Neither 'docker-ce' nor 'moby-engine' is available via dnf."
                log_error "Enable the Docker repository: $docker_url"
                return 1
            fi

            log_info "Installing Docker Engine via dnf (${docker_pkg})"
            if ! run_privileged dnf install -y "${docker_pkg}"; then
                log_error "Failed to install ${docker_pkg} via dnf."
                log_error "Try running 'sudo dnf install -y ${docker_pkg}' manually."
                log_error "If packages are missing, add the Docker repository: $docker_url"
                return 1
            fi

            # Modern docker-ce bundles Compose v2 as a built-in subcommand.
            # Re-check before trying to install a separate compose package.
            if [ "$need_compose" = true ] && docker compose version >/dev/null 2>&1; then
                log_info "Docker Compose v2 is bundled with ${docker_pkg}"
                need_compose=false
            fi
        fi

        if [ "$need_compose" = true ]; then
            local compose_pkg=""
            if rpm -q docker-compose-plugin >/dev/null 2>&1; then
                compose_pkg="docker-compose-plugin"
            elif dnf list --available docker-compose-plugin 2>/dev/null | grep -q '^docker-compose-plugin\.'; then
                compose_pkg="docker-compose-plugin"
            elif dnf list --available docker-compose 2>/dev/null | grep -q '^docker-compose\.'; then
                compose_pkg="docker-compose"
            else
                log_error "Neither 'docker-compose-plugin' nor 'docker-compose' is available via dnf."
                log_error "Enable the Docker repository: $docker_url"
                log_error "Or install Docker Compose v2 manually."
                return 1
            fi

            log_info "Installing Docker Compose plugin via dnf (${compose_pkg})"
            if ! run_privileged dnf install -y "${compose_pkg}"; then
                log_error "Failed to install ${compose_pkg} via dnf."
                log_error "Try running 'sudo dnf install -y ${compose_pkg}' manually."
                log_error "If packages are missing, add the Docker repository: $docker_url"
                return 1
            fi
        fi
    else
        log_info "Docker and Docker Compose are already installed"
    fi
}

pacman_install() {
    local missing=()
    local need_engine=false
    local need_compose=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker; then
        need_engine=true
        need_compose=true
    elif ! docker compose version >/dev/null 2>&1; then
        need_compose=true
    fi

    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        if is_wsl_docker_desktop; then
            log_info "Docker is provided by Docker Desktop (WSL integration) — skipping package install"
            need_engine=false
            need_compose=false
        fi
    fi

    if [ ${#missing[@]} -gt 0 ] || [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        log_info "Tip: run 'sudo pacman -Syu' first if your system hasn't been updated recently"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via pacman: ${missing[*]}"
        if ! run_privileged pacman -S --noconfirm --needed "${missing[@]}"; then
            log_error "Failed to install ${missing[*]} via pacman."
            log_error "Try running 'sudo pacman -S ${missing[*]}' manually to see detailed errors."
            return 1
        fi
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        # Arch packages Docker Compose v2 as 'docker-compose' (provides both
        # the standalone binary and the CLI plugin). pacman --needed prevents
        # reinstalling packages that are already current.
        log_info "Installing Docker packages via pacman"
        if ! run_privileged pacman -S --noconfirm --needed docker docker-compose; then
            log_error "Failed to install Docker packages via pacman."
            log_error "Try running 'sudo pacman -S docker docker-compose' manually."
            return 1
        fi
    else
        log_info "Docker and Docker Compose plugin are already installed"
    fi
}

apk_install() {
    # Alpine's community repo provides `docker` and `docker-cli-compose` (v2).
    # We also ensure `bash` is present — harbor.sh uses bash-only constructs.
    local missing=()
    local need_docker=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")
    check_command bash || missing+=("bash")

    if ! check_command docker || ! docker compose version >/dev/null 2>&1; then
        if is_wsl_docker_desktop; then
            log_info "Docker is provided by Docker Desktop (WSL integration) — skipping package install"
        else
            need_docker=true
        fi
    fi

    # Refresh the apk index if anything needs installing. Stale indexes
    # (common on minimal Docker images or long-running Alpine installs)
    # cause "unable to select packages" or 404 download errors.
    if [ ${#missing[@]} -gt 0 ] || [ "$need_docker" = true ]; then
        log_info "Refreshing apk package index"
        run_privileged apk update >/dev/null 2>&1 || \
            log_warn "apk update had errors (possibly unreachable repository); continuing"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via apk: ${missing[*]}"
        if ! run_privileged apk add --no-cache "${missing[@]}"; then
            log_error "Failed to install ${missing[*]} via apk."
            log_error "Check your internet connection and that the community repository is enabled."
            return 1
        fi
    else
        log_info "git, curl, and bash are already installed"
    fi

    if [ "$need_docker" = true ]; then
        log_info "Installing Docker Engine and Docker Compose plugin via apk"
        if ! run_privileged apk add --no-cache docker docker-cli-compose; then
            log_error "Failed to install Docker packages via apk."
            log_error "Ensure the community repository is enabled in /etc/apk/repositories."
            return 1
        fi
    else
        if [ "$need_docker" = false ]; then
            log_info "Docker and Docker Compose plugin are already installed"
        fi
    fi
}

zypper_install() {
    local missing=()
    local need_engine=false
    local need_compose=false
    check_command git || missing+=("git")
    check_command curl || missing+=("curl")

    if ! check_command docker; then
        need_engine=true
        need_compose=true
    elif ! docker compose version >/dev/null 2>&1; then
        need_compose=true
    fi

    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        if is_wsl_docker_desktop; then
            log_info "Docker is provided by Docker Desktop (WSL integration) — skipping package install"
            need_engine=false
            need_compose=false
        fi
    fi

    # Refresh zypper metadata if anything needs installing. Stale metadata
    # causes package-not-found errors, especially after adding the Docker
    # CE repository.
    if [ ${#missing[@]} -gt 0 ] || [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        log_info "Refreshing zypper repository metadata"
        run_privileged zypper --non-interactive refresh >/dev/null 2>&1 || \
            log_warn "zypper refresh had errors (possibly unreachable repository); continuing"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via zypper: ${missing[*]}"
        if ! run_privileged zypper --non-interactive install "${missing[@]}"; then
            log_error "Failed to install ${missing[*]} via zypper."
            log_error "Try running 'sudo zypper install ${missing[*]}' manually to see detailed errors."
            return 1
        fi
    else
        log_info "git and curl are already installed"
    fi

    if [ "$need_engine" = true ] || [ "$need_compose" = true ]; then
        if [ "$need_engine" = true ]; then
            # Prefer docker-ce from Docker's official repo if available;
            # fall back to docker from the distro repo.
            local docker_pkg=""
            if zypper se -x docker-ce 2>/dev/null | grep -q 'docker-ce'; then
                docker_pkg="docker-ce"
            elif zypper se -x docker 2>/dev/null | grep -q '| docker '; then
                docker_pkg="docker"
            else
                log_error "Neither 'docker-ce' nor 'docker' is available via zypper."
                log_error "Add the Docker repository: https://docs.docker.com/engine/install/sles/"
                return 1
            fi

            log_info "Installing Docker Engine via zypper (${docker_pkg})"
            if ! run_privileged zypper --non-interactive install "${docker_pkg}"; then
                log_error "Failed to install ${docker_pkg} via zypper."
                log_error "Try running 'sudo zypper install ${docker_pkg}' manually."
                log_error "If packages are missing, add the Docker repository: https://docs.docker.com/engine/install/sles/"
                return 1
            fi

            # docker-ce bundles Compose v2; re-check before installing separately
            if [ "$need_compose" = true ] && docker compose version >/dev/null 2>&1; then
                log_info "Docker Compose v2 is bundled with ${docker_pkg}"
                need_compose=false
            fi
        fi

        if [ "$need_compose" = true ]; then
            local compose_pkg=""
            if zypper se -x docker-compose-plugin 2>/dev/null | grep -q 'docker-compose-plugin'; then
                compose_pkg="docker-compose-plugin"
            elif zypper se -x docker-compose 2>/dev/null | grep -q 'docker-compose'; then
                compose_pkg="docker-compose"
            else
                log_error "Neither 'docker-compose-plugin' nor 'docker-compose' is available via zypper."
                log_error "Add the Docker repository: https://docs.docker.com/engine/install/sles/"
                log_error "Or install Docker Compose v2 manually."
                return 1
            fi

            log_info "Installing Docker Compose plugin via zypper (${compose_pkg})"
            if ! run_privileged zypper --non-interactive install "${compose_pkg}"; then
                log_error "Failed to install ${compose_pkg} via zypper."
                log_error "Try running 'sudo zypper install ${compose_pkg}' manually."
                return 1
            fi
        fi
    else
        log_info "Docker and Docker Compose are already installed"
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
    # The Homebrew installer prompts "Press RETURN to continue" by default.
    # Download the installer first so a silent curl failure (empty output)
    # does not silently succeed via `/bin/bash -c ""`.
    local homebrew_script
    homebrew_script="$(curl -fsSL --connect-timeout 15 --max-time 60 "$HOMEBREW_INSTALL_URL")" || {
        log_error "Failed to download Homebrew installer from $HOMEBREW_INSTALL_URL"
        return 1
    }
    if [ -z "$homebrew_script" ]; then
        log_error "Homebrew installer script is empty; download may have failed."
        return 1
    fi
    # When run in a pipe (curl | bash), stdin is consumed and the prompt may
    # hang or fail. NONINTERACTIVE=1 suppresses the prompt.
    if [ ! -t 0 ]; then
        if ! NONINTERACTIVE=1 /bin/bash -c "$homebrew_script"; then
            log_error "Homebrew installer failed. Review the errors above."
            log_error "Try installing Homebrew manually: https://brew.sh"
            return 1
        fi
    else
        if ! /bin/bash -c "$homebrew_script"; then
            log_error "Homebrew installer failed. Review the errors above."
            log_error "Try installing Homebrew manually: https://brew.sh"
            return 1
        fi
    fi
    if ! load_homebrew_shellenv; then
        log_warn "Homebrew installed but could not load its shell environment."
        log_warn "You may need to restart your terminal or run: eval \"\$(brew shellenv)\""
        return 1
    fi
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
        if _with_timeout 10 docker info >/dev/null 2>&1; then
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
    # On macOS, /usr/bin/git is an Xcode CLT shim: `command -v git` returns
    # true even when CLT is not installed. The shim either triggers a GUI
    # install dialog (interactive) or fails silently (non-interactive/Tauri).
    # Use `git --version` to verify git actually works, not just exists.
    git --version >/dev/null 2>&1 || missing+=("git")
    check_command curl || missing+=("curl")

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "Installing missing tools via brew: ${missing[*]}"
        if ! brew install "${missing[@]}"; then
            log_error "Failed to install ${missing[*]} via Homebrew."
            log_error "Try running 'brew install ${missing[*]}' manually to see detailed errors."
            return 1
        fi
    else
        log_info "git and curl are already installed"
    fi

    if ! check_command docker; then
        log_info "Installing Docker Desktop via Homebrew cask"
        if ! brew install --cask docker; then
            log_error "Failed to install Docker Desktop via Homebrew."
            log_error "Try installing Docker Desktop manually from https://docker.com/products/docker-desktop"
            return 1
        fi
        # Docker Desktop needs to be launched once after cask install to
        # complete setup (accept license, provision CLI tools, start daemon).
        log_info "Starting Docker Desktop for initial setup (this may take a moment)..."
        if start_macos_docker_desktop; then
            if wait_for_docker_access 180; then
                log_info "Docker Desktop is running"
            else
                log_warn "Docker Desktop was started but the daemon did not become reachable within 3 minutes."
                log_warn "Open Docker Desktop manually and complete the initial setup."
            fi
        else
            log_warn "Could not start Docker Desktop automatically."
            log_warn "Open Docker Desktop from Applications to complete the initial setup."
        fi
    else
        log_info "docker CLI is already installed"
        # Docker Desktop may be installed but not running. Attempt to start it
        # so that `docker compose version` and later verification steps succeed.
        if ! _with_timeout 15 docker info >/dev/null 2>&1; then
            log_info "Docker daemon is not running — attempting to start Docker Desktop..."
            if start_macos_docker_desktop; then
                if wait_for_docker_access 180; then
                    log_info "Docker Desktop is running"
                else
                    log_warn "Docker Desktop was started but the daemon did not become reachable within 3 minutes."
                    log_warn "Open Docker Desktop manually and complete the initial setup."
                fi
            else
                log_warn "Could not start Docker Desktop automatically."
                log_warn "Open Docker Desktop from Applications to start the daemon."
            fi
        fi
    fi

    if ! docker compose version >/dev/null 2>&1; then
        if ! _with_timeout 15 docker info >/dev/null 2>&1; then
            log_warn "Docker daemon is not running. Start Docker Desktop to enable Docker Compose."
        else
            log_warn "Docker Compose v2 not detected."
            log_warn "Update Docker Desktop: https://docs.docker.com/desktop/setup/install/mac-install/"
        fi
    fi
}

# Detect whether Docker is provided by Docker Desktop for Windows via WSL integration.
# Docker Desktop injects its own docker binary into WSL (typically at
# /usr/bin/docker or via /mnt/wsl/docker-desktop/...). When this is the case,
# installing docker.io or docker-ce via the package manager creates conflicts
# (two Docker daemons, socket confusion). This function returns 0 if Docker
# Desktop is providing Docker in WSL, 1 otherwise.
is_wsl_docker_desktop() {
    [ "$IS_WSL" = true ] || return 1
    check_command docker || return 1
    # Docker Desktop integration puts its socket at a well-known path
    local docker_info_output
    if [ -S "/var/run/docker.sock" ] && docker_info_output=$(_with_timeout 10 docker info 2>/dev/null); then
        # Check if docker info references Docker Desktop
        if echo "$docker_info_output" | grep -qi "docker desktop\|com.docker.depi"; then
            return 0
        fi
        # Docker Desktop WSL integration creates a special context
        if _with_timeout 10 docker context ls 2>/dev/null | grep -qi "desktop-linux"; then
            return 0
        fi
    fi
    return 1
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
        if [ "$WSL_VERSION" = "1" ]; then
            log_warn "WSL1 cannot run Docker natively. Docker Desktop WSL integration is required."
            return 1
        fi
        if _with_timeout 15 docker info >/dev/null 2>&1; then
            return 0
        fi
        # Docker not reachable in WSL2 — fall through to try systemd if available
        if ! check_command systemctl || ! systemctl is-system-running 2>/dev/null | grep -qE '^(running|degraded|starting)$'; then
            log_warn "Docker is not reachable in WSL2 and systemd is not active."
            log_warn "Either enable Docker Desktop WSL integration, or enable systemd in WSL:"
            log_warn "  Add [boot] systemd=true to /etc/wsl.conf and restart WSL."
            return 1
        fi
    fi

    if check_command systemctl && systemctl is-system-running 2>/dev/null | grep -qE '^(running|degraded|starting)$'; then
        # Enable docker to start on boot. Check docker.service, docker.socket
        # (default on many distros), and snap.docker.dockerd (snap installs).
        if ! systemctl is-enabled docker >/dev/null 2>&1 && \
           ! systemctl is-enabled docker.socket >/dev/null 2>&1 && \
           ! systemctl is-enabled snap.docker.dockerd >/dev/null 2>&1; then
            log_info "Enabling Docker service"
            # enable can fail if Docker was installed via snap or non-standard means
            run_privileged systemctl enable docker >/dev/null 2>&1 || true
        fi

        # Docker may already be reachable via socket activation (docker.socket)
        # even if docker.service is not active. Check reachability first to
        # avoid unnecessary start and confusing "Starting Docker service" output.
        if _with_timeout 5 docker info >/dev/null 2>&1; then
            return 0
        fi

        if ! systemctl is-active docker >/dev/null 2>&1; then
            # Snap-installed Docker uses a different service name
            if systemctl is-active snap.docker.dockerd >/dev/null 2>&1; then
                # Snap Docker service is running but daemon isn't reachable.
                # This can happen if the snap socket is at a non-standard path
                # and DOCKER_HOST is not set.
                log_warn "Snap Docker service is running but the daemon is not reachable."
                log_warn "Try: sudo snap restart docker"
                log_warn "If the issue persists, check: snap logs docker"
                return 1
            fi
            log_info "Starting Docker service"
            if ! run_privileged systemctl start docker; then
                # Check if this is a snap Docker that just needs a different command
                if snap list docker >/dev/null 2>&1; then
                    log_warn "Docker appears to be installed via Snap."
                    log_warn "Try: sudo snap start docker"
                    log_warn "If the issue persists: snap logs docker"
                else
                    log_warn "Failed to start Docker service via systemctl"
                    log_warn "Check the service log for details: journalctl -xeu docker.service"
                    log_warn "Common causes: missing kernel modules, storage driver issues, or port conflicts"
                fi
                return 1
            fi
            if ! wait_for_docker_access 30; then
                log_warn "Docker service started but daemon did not become reachable within 30 seconds"
                return 1
            fi
        fi
    elif check_command rc-service && check_command rc-update; then
        log_info "Enabling and starting Docker service (OpenRC)"
        # enable can fail if already added; not critical
        run_privileged rc-update add docker default >/dev/null 2>&1 || true
        if ! run_privileged rc-service docker start >/dev/null 2>&1; then
            log_warn "Failed to start Docker service via OpenRC"
            log_warn "Check the service log: cat /var/log/docker.log"
            return 1
        fi
        if ! wait_for_docker_access 30; then
            log_warn "Docker service started but daemon did not become reachable within 30 seconds"
            return 1
        fi
    else
        # No init system (systemd/OpenRC) — common in Docker containers
        # and CI environments. Docker may still be reachable via a mounted
        # socket or already-running daemon. Check rather than assuming.
        if _with_timeout 10 docker info >/dev/null 2>&1; then
            return 0
        fi
        # Docker is not reachable and we have no way to start it
        log_warn "No init system (systemd/OpenRC) detected and Docker daemon is not reachable."
        log_warn "If running in a container, mount the Docker socket (-v /var/run/docker.sock:/var/run/docker.sock)."
        return 1
    fi
}

version_to_int() {
    local version="$1"
    local major minor patch
    major=0
    minor=0
    patch=0
    IFS='.' read -r major minor patch <<< "$version"
    # Strip leading zeros to prevent printf interpreting as octal (e.g., "08")
    major=$((10#${major:-0}))
    minor=$((10#${minor:-0}))
    patch=$((10#${patch:-0}))
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
        log_error "Docker is not installed or not in PATH."
        if [ -x /usr/bin/docker ] || [ -x /usr/local/bin/docker ]; then
            log_error "Docker binary exists but is not in the current PATH."
            log_error "Restart your terminal or run: export PATH=\"\$PATH:/usr/bin:/usr/local/bin\""
        else
            log_error "Install Docker: https://docs.docker.com/engine/install/"
        fi
        return 1
    fi

    local docker_access_output
    if docker_access_output=$(_with_timeout 15 docker info 2>&1); then
        # When running as root (or via sudo), docker info always succeeds
        # because root has full socket access. But the real user (SUDO_USER)
        # may not be in the docker group yet — they'll get "permission denied"
        # when they run harbor as themselves. Proactively add them.
        if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
            if ! id -nG "$SUDO_USER" 2>/dev/null | grep -qw docker; then
                log_info "Docker daemon is reachable (running as root)"
                # Ensure docker group exists and add the real user
                if check_command groupadd; then
                    groupadd docker >/dev/null 2>&1 || true
                fi
                if usermod -aG docker "$SUDO_USER" >/dev/null 2>&1; then
                    log_warn "Added '${SUDO_USER}' to docker group so Harbor works without sudo"
                    log_warn "Re-login or run: newgrp docker"
                else
                    log_warn "Docker works as root but '${SUDO_USER}' is not in the docker group"
                    log_warn "Run: sudo usermod -aG docker ${SUDO_USER}"
                fi
                return 0
            fi
        fi
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

        # getent may not be available on Alpine or other minimal systems;
        # fall back to checking /etc/group directly.
        _group_exists() {
            if check_command getent; then
                getent group "$1" >/dev/null 2>&1
            elif [ -f /etc/group ]; then
                grep -q "^$1:" /etc/group 2>/dev/null
            else
                return 1
            fi
        }

        if ! _group_exists docker; then
            run_privileged groupadd docker >/dev/null 2>&1 || true
        fi

        if _group_exists docker; then
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
            return 1
        fi
        log_error "Docker daemon is not running or not reachable"
        if [ "$IS_WSL" = true ]; then
            log_error "Native Docker Engine: sudo systemctl start docker"
            log_error "Docker Desktop: ensure it is running and WSL integration is enabled for this distro"
        elif [ "$PLATFORM" = "linux" ]; then
            if snap list docker >/dev/null 2>&1; then
                log_error "Docker appears to be installed via Snap."
                log_error "Try: sudo snap start docker"
            else
                log_error "Try: sudo systemctl start docker"
            fi
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
            log_error "$tool is not installed."
            case "$tool" in
                docker) log_error "  Install Docker: https://docs.docker.com/engine/install/" ;;
                *)      log_error "  Install it with your system package manager (e.g., apt/dnf/brew install $tool)" ;;
            esac
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
        log_error "Docker Compose v2 is not installed or unavailable."
        if _with_timeout 5 docker info >/dev/null 2>&1; then
            log_error "Docker daemon is running but the Compose plugin is missing."
            log_error "Install it: https://docs.docker.com/compose/install/linux/"
        else
            log_error "Docker daemon may not be running — start Docker first, then check Compose."
        fi
        failed=true
    fi

    if ! verify_docker_access; then
        failed=true
    fi

    if [ "$failed" = true ]; then
        return 1
    fi

    return 0
}

check_optional_gpu_support() {
    local has_nvidia_hardware=false
    local has_nvidia_driver=false

    # Check for actual NVIDIA GPU hardware via multiple methods.
    # nvidia-smi alone is insufficient: it can be installed without a GPU
    # (CUDA toolkit), and hardware can exist without nvidia-smi (no driver).
    if check_command nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
        has_nvidia_hardware=true
        has_nvidia_driver=true
    elif check_command lspci && lspci 2>/dev/null | grep -qi "nvidia"; then
        has_nvidia_hardware=true
        # Hardware present via lspci. nvidia-smi could exist but fail to
        # talk to the driver (module not loaded, version mismatch). Only
        # trust the driver if nvidia-smi -L succeeds, not mere presence.
    elif [ -e /dev/nvidia0 ] || [ -d /proc/driver/nvidia ]; then
        has_nvidia_hardware=true
        has_nvidia_driver=true
    fi

    if [ "$has_nvidia_hardware" = true ]; then
        if [ "$has_nvidia_driver" = false ]; then
            log_warn "NVIDIA GPU hardware detected but drivers are not installed"
            log_warn "Install NVIDIA drivers first: https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/"
            return
        fi

        log_info "NVIDIA GPU detected (driver installed)"
        if check_command nvidia-ctk || check_command nvidia-container-toolkit; then
            log_info "NVIDIA container toolkit detected"
        else
            log_warn "NVIDIA GPU detected but NVIDIA container toolkit is missing (optional)"
            log_warn "GPU containers won't work without it. Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        fi
    fi
}

warn_wsl_slow_filesystem() {
    # /mnt/c, /mnt/d, etc. are Windows NTFS filesystems mounted via drvfs/9p.
    # IO on these paths is 5-10x slower than the native ext4 filesystem.
    # Harbor and Docker perform poorly when installed on these paths.
    local home_mount
    home_mount=$(df -P "$HOME" 2>/dev/null | awk 'NR==2 {print $6}')
    if [ -n "$home_mount" ] && echo "$home_mount" | grep -q "^/mnt/[a-zA-Z]"; then
        log_warn "Your HOME ($HOME) is on a Windows filesystem ($home_mount)."
        log_warn "File operations on Windows-mounted paths (/mnt/c, /mnt/d, ...) are significantly slower."
        log_warn "Harbor will install to $HOME/.harbor which will have degraded performance."
        log_warn "For better performance, set your WSL default user's HOME to a Linux path"
        log_warn "or override the install path: HARBOR_INSTALL_PATH=~/.harbor"
    fi
}

install_requirements() {
    if [ "$IS_WSL" = true ]; then
        log_warn "WSL${WSL_VERSION} environment detected"
        if [ "$WSL_VERSION" = "1" ]; then
            log_error "WSL1 does not support Docker natively. Harbor requires Docker."
            log_error "Upgrade to WSL2: wsl --set-version <distro> 2"
            log_error "Or install Docker Desktop on Windows and enable WSL integration."
            return 1
        fi
        log_warn "Preferred setup is Docker Desktop on Windows with WSL integration enabled"
        warn_wsl_slow_filesystem
    fi

    # Immutable/OSTree distros (Fedora Silverblue/Kinoite, CoreOS, openSUSE
    # MicroOS, etc.) cannot use standard package installs. Detect and guide.
    if [ "$IS_IMMUTABLE" = true ]; then
        log_warn "Immutable OS detected (variant='${DISTRO_VARIANT:-unknown}', distro='${DISTRO_ID:-unknown}')"
        log_warn "Standard package installation is not supported on this system."
        log_warn "Install Docker and dependencies manually:"
        if check_command transactional-update; then
            log_warn "  Option 1: transactional-update pkg install docker docker-compose git curl"
            log_warn "            systemctl reboot  # transactional-update changes require a reboot"
            log_warn "  Option 2: Use a Toolbox/Distrobox container for Harbor:"
            log_warn "            toolbox create harbor && toolbox enter harbor"
            log_warn "            Then install normally inside the container."
        elif check_command rpm-ostree; then
            log_warn "  Option 1: rpm-ostree install docker-ce docker-compose-plugin git curl"
            log_warn "            systemctl reboot  # rpm-ostree changes require a reboot"
            log_warn "  Option 2: Use a Toolbox/Distrobox container for Harbor:"
            log_warn "            toolbox create harbor && toolbox enter harbor"
            log_warn "            Then install normally inside the container."
        fi
        log_warn "  Docker: https://docs.docker.com/engine/install/"
        # Check if requirements are already met despite being immutable
        if check_command docker && check_command git && check_command curl && docker compose version >/dev/null 2>&1; then
            log_info "All required tools are already installed. Continuing."
        else
            log_error "Missing dependencies on an immutable OS. Install them manually (see above) and retry with --skip-requirements."
            return 1
        fi
        return 0
    fi

    case "$PLATFORM:$PKG_MANAGER" in
        macos:)
            brew_install || return 1
            ;;
        linux:apt)
            apt_install || return 1
            ;;
        linux:dnf)
            dnf_install || return 1
            ;;
        linux:pacman)
            pacman_install || return 1
            ;;
        linux:apk)
            apk_install || return 1
            ;;
        linux:zypper)
            zypper_install || return 1
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
        local platform_info="Platform: Linux (distro='${DISTRO_ID:-unknown}', pkg='${PKG_MANAGER:-unknown}'"
        if [ -n "$DISTRO_VARIANT" ]; then
            platform_info="${platform_info}, variant='${DISTRO_VARIANT}'"
        fi
        if [ "$IS_IMMUTABLE" = true ]; then
            platform_info="${platform_info}, immutable=true"
        fi
        platform_info="${platform_info})"
        log_info "$platform_info"
    elif [ "$PLATFORM" = "macos" ]; then
        log_info "Platform: macOS"
    fi

    require_supported_platform || exit 1

    # On macOS, brew doesn't need sudo; on Linux, verify sudo works before
    # attempting any package installs (catches no-TTY / no-sudo early).
    if [ "$PLATFORM" = "linux" ] && [ "$IS_IMMUTABLE" = false ]; then
        preflight_privilege_check || exit 1
    fi
    install_requirements || exit 1
    if ! ensure_linux_docker_service; then
        log_warn "Docker service setup encountered issues (will verify below)"
    fi

    verify_required_tools || exit 1
    check_optional_gpu_support

    if [ "$PLATFORM" = "linux" ] && [ "${HARBOR_APP:-}" != "1" ]; then
        log_info "If you were added to the docker group, re-login before running Harbor commands."
    fi

    if [ "${HARBOR_APP:-}" = "1" ]; then
        log_info "Dependency setup complete."
    else
        log_info "Dependency setup complete. Run 'harbor doctor' to validate full Harbor readiness."
    fi
}

main
