#!/bin/bash

# Detect non-bash shells early. When piped (curl | sh), the shebang is
# ignored and /bin/sh interprets the script instead. Bash-specific
# features like `set -o pipefail` then fail with a confusing error.
# shellcheck disable=SC2128
if [ -z "${BASH_VERSION:-}" ]; then
  # When run as a file (not piped), $0 is a real path -- re-exec under bash.
  if [ -f "$0" ] && [ "$(dd if="$0" bs=1 count=2 2>/dev/null)" = "#!" ] && command -v bash >/dev/null 2>&1; then
    exec bash "$0" "$@"
  fi
  _current_shell=$(ps -p $$ -o comm= 2>/dev/null || echo "unknown shell")
  echo "Error: Harbor install requires bash, but is running under ${_current_shell}." >&2
  echo "Please run:  curl -fsSL <url> | bash" >&2
  echo "         or: bash install.sh" >&2
  exit 1
fi

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

_LAST_SETUP_STAGE=""
setup_stage() {
  _LAST_SETUP_STAGE="$1"
  echo "HARBOR_SETUP_STAGE=$1"
}

resolve_harbor_version() {
  local response version attempt
  for attempt in 1 2; do
    response=$(curl -fsSL "$HARBOR_RELEASE_URL" 2>/dev/null) || {
      if [ "$attempt" -eq 1 ]; then
        sleep 2
        continue
      fi
      echo "Warning: Failed to fetch latest release from $HARBOR_RELEASE_URL" >&2
      return 1
    }
    if command -v jq >/dev/null 2>&1; then
      version=$(printf '%s\n' "$response" | jq -r '.tag_name // empty' 2>/dev/null)
    else
      version=$(printf '%s\n' "$response" | sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n1)
    fi
    if [ -n "$version" ]; then
      printf '%s\n' "$version"
      return 0
    fi
    if [ "$attempt" -eq 1 ]; then
      sleep 2
    fi
  done
  echo "Warning: Could not parse version from GitHub API response" >&2
  return 1
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
          echo "Error: --source-path requires a path argument." >&2
          echo "Usage: $0 --source-path /path/to/harbor/source" >&2
          exit 1
        fi
        HARBOR_INSTALL_SOURCE_PATH="$1"
        ;;
      --requirements-path)
        shift
        if [ -z "${1:-}" ]; then
          echo "Error: --requirements-path requires a path argument." >&2
          echo "Usage: $0 --requirements-path /path/to/requirements.sh" >&2
          exit 1
        fi
        HARBOR_REQUIREMENTS_PATH="$1"
        ;;
      --version)
        shift
        if [ -z "${1:-}" ]; then
          echo "Error: --version requires a version tag (e.g., v0.4.19)." >&2
          echo "Usage: $0 --version v0.4.19" >&2
          exit 1
        fi
        HARBOR_VERSION="$1"
        ;;
      -h|--help)
        print_help
        exit 0
        ;;
      *)
        echo "Error: Unknown option: $1" >&2
        echo >&2
        print_help >&2
        exit 1
        ;;
    esac
    shift
  done
}

backup_user_configs() {
  local backup_dir="$1"
  mkdir -p "$backup_dir"
  if [ -f "$HARBOR_INSTALL_PATH/.env" ]; then
    cp "$HARBOR_INSTALL_PATH/.env" "$backup_dir/.env"
  fi
  # Preserve per-service override.env files (user customizations via harbor env)
  if [ -d "$HARBOR_INSTALL_PATH/services" ]; then
    local svc_env
    while IFS= read -r svc_env; do
      # Only back up files that differ from the default (have user content)
      local rel="${svc_env#"$HARBOR_INSTALL_PATH/"}"
      local dir
      dir=$(dirname "$rel")
      mkdir -p "$backup_dir/$dir"
      cp "$svc_env" "$backup_dir/$rel"
    done < <(find "$HARBOR_INSTALL_PATH/services" -maxdepth 2 -name 'override.env' -type f 2>/dev/null)
  fi
}

restore_user_configs() {
  local backup_dir="$1"
  if [ ! -d "$backup_dir" ]; then
    return 0
  fi
  if [ -f "$backup_dir/.env" ]; then
    cp "$backup_dir/.env" "$HARBOR_INSTALL_PATH/.env"
  fi
  if [ -d "$backup_dir/services" ]; then
    local svc_env
    while IFS= read -r svc_env; do
      local rel="${svc_env#"$backup_dir/"}"
      local target="$HARBOR_INSTALL_PATH/$rel"
      local dir
      dir=$(dirname "$target")
      mkdir -p "$dir"
      cp "$svc_env" "$target"
    done < <(find "$backup_dir/services" -maxdepth 2 -name 'override.env' -type f 2>/dev/null)
  fi
  rm -rf "$backup_dir"
}

install_or_update_project() {
  if [ -n "$HARBOR_INSTALL_SOURCE_PATH" ]; then
    if [ ! -d "$HARBOR_INSTALL_SOURCE_PATH" ]; then
      echo "Error: Local source path does not exist: $HARBOR_INSTALL_SOURCE_PATH" >&2
      echo "Verify the path is correct and the directory exists." >&2
      exit 1
    fi

    # Resolve both paths to catch overlaps like --source-path ~/.harbor with
    # HARBOR_INSTALL_PATH=~/.harbor, or --source-path . when CWD is the
    # install dir.  Without this check, rm -rf wipes the source before tar
    # can read it, destroying the installation with no way to recover.
    local resolved_source resolved_install
    resolved_source=$(cd -P "$HARBOR_INSTALL_SOURCE_PATH" && pwd)
    resolved_install="$HARBOR_INSTALL_PATH"
    if [ -d "$HARBOR_INSTALL_PATH" ]; then
      resolved_install=$(cd -P "$HARBOR_INSTALL_PATH" && pwd)
    fi
    if [ "$resolved_source" = "$resolved_install" ]; then
      echo "Error: --source-path and install path resolve to the same directory:" >&2
      echo "  source:  $resolved_source" >&2
      echo "  install: $resolved_install" >&2
      echo "Use a different --source-path or set HARBOR_INSTALL_PATH to a separate location." >&2
      exit 1
    fi
    # Also reject source inside install path or vice versa — rm -rf of either
    # would destroy the other.
    case "$resolved_source/" in
      "$resolved_install/"*)
        echo "Error: --source-path ($resolved_source) is inside the install path ($resolved_install)." >&2
        echo "Use a different --source-path or set HARBOR_INSTALL_PATH to a separate location." >&2
        exit 1
        ;;
    esac
    case "$resolved_install/" in
      "$resolved_source/"*)
        echo "Error: Install path ($resolved_install) is inside --source-path ($resolved_source)." >&2
        echo "Use a different HARBOR_INSTALL_PATH or --source-path." >&2
        exit 1
        ;;
    esac

    echo "Installing from local source path: $HARBOR_INSTALL_SOURCE_PATH"
    local backup_dir=""
    if [ -d "$HARBOR_INSTALL_PATH" ]; then
      backup_dir=$(mktemp -d)
      backup_user_configs "$backup_dir"
    fi
    rm -rf "$HARBOR_INSTALL_PATH"
    mkdir -p "$HARBOR_INSTALL_PATH"
    if ! (set -o pipefail; (
      cd "$HARBOR_INSTALL_SOURCE_PATH"
      tar \
        --exclude='./.git' \
        --exclude='./.env' \
        --exclude='./tests/artifacts' \
        -cf - .
    ) | tar -C "$HARBOR_INSTALL_PATH" -xf -); then
      echo "Error: Failed to copy from source path: $HARBOR_INSTALL_SOURCE_PATH" >&2
      if [ -n "$backup_dir" ]; then
        echo "Attempting to restore your config backup..." >&2
        if mkdir -p "$HARBOR_INSTALL_PATH" && cp -a "$backup_dir/." "$HARBOR_INSTALL_PATH/"; then
          rm -rf "$backup_dir"
          echo "Config backup restored to $HARBOR_INSTALL_PATH" >&2
        else
          echo "Restore failed. Your config backup is at: $backup_dir" >&2
        fi
      fi
      exit 1
    fi
    if [ -n "$backup_dir" ]; then
      restore_user_configs "$backup_dir"
    fi
    cd "$HARBOR_INSTALL_PATH"
    return 0
  fi

  if [ -d "$HARBOR_INSTALL_PATH" ] && [ -d "$HARBOR_INSTALL_PATH/.git" ]; then
    cd "$HARBOR_INSTALL_PATH"
    # Check if already on the target version — skip fetch+checkout if so
    local current_tag
    current_tag=$(git describe --tags --exact-match HEAD 2>/dev/null || true)
    if [ "$current_tag" = "$HARBOR_VERSION" ]; then
      echo "Already on version $HARBOR_VERSION"
    else
      echo "Existing installation found. Updating to $HARBOR_VERSION..."
      # Stash user-modified tracked files (override.env) so checkout succeeds
      local had_stash=false
      if ! git diff --quiet -- 'services/*/override.env' 2>/dev/null; then
        git stash push --quiet -- 'services/*/override.env' 2>/dev/null && had_stash=true
      fi
      if ! git fetch --depth 1 origin "+refs/tags/$HARBOR_VERSION:refs/tags/$HARBOR_VERSION" || \
         ! git checkout "tags/$HARBOR_VERSION"; then
        if [ "$had_stash" = true ]; then
          git stash pop --quiet 2>/dev/null || true
        fi
        echo "Error: Failed to update to version $HARBOR_VERSION." >&2
        echo "Your override.env customizations have been restored." >&2
        exit 1
      fi
      if [ "$had_stash" = true ]; then
        git stash pop --quiet 2>/dev/null || {
          echo "Warning: Could not auto-restore override.env changes (merge conflict)."
          echo "Your overrides are saved in 'git stash'. Run 'cd $HARBOR_INSTALL_PATH && git stash pop' to recover."
        }
      fi
    fi
  else
    local backup_dir=""
    if [ -d "$HARBOR_INSTALL_PATH" ]; then
      echo "Existing non-git installation found. Re-cloning..."
      backup_dir=$(mktemp -d)
      backup_user_configs "$backup_dir"
      rm -rf "$HARBOR_INSTALL_PATH"
    fi
    echo "Cloning project repository..."
    local clone_ok=false
    for attempt in 1 2; do
      if git clone --depth 1 --branch "$HARBOR_VERSION" "$HARBOR_REPO_URL" "$HARBOR_INSTALL_PATH"; then
        clone_ok=true
        break
      fi
      rm -rf "$HARBOR_INSTALL_PATH"
      if [ "$attempt" -eq 1 ]; then
        echo "Clone failed, retrying in 3 seconds..."
        sleep 3
      fi
    done
    if [ "$clone_ok" = false ]; then
      if [ -n "$backup_dir" ]; then
        echo "Error: git clone failed after 2 attempts. Attempting to restore your config backup..." >&2
        if mkdir -p "$HARBOR_INSTALL_PATH" && cp -a "$backup_dir/." "$HARBOR_INSTALL_PATH/"; then
          rm -rf "$backup_dir"
          echo "Config backup restored to $HARBOR_INSTALL_PATH" >&2
        else
          echo "Restore failed. Your config backup is at: $backup_dir" >&2
        fi
      else
        echo "Error: git clone failed after 2 attempts." >&2
      fi
      echo "Possible causes:" >&2
      echo "  - No internet connection or DNS resolution failure" >&2
      echo "  - GitHub is unreachable (check https://www.githubstatus.com)" >&2
      echo "  - A firewall or proxy is blocking git:// or https:// connections" >&2
      echo "  - Version '$HARBOR_VERSION' does not exist" >&2
      echo "Try: git clone $HARBOR_REPO_URL (to diagnose the issue manually)" >&2
      exit 1
    fi
    if [ -n "$backup_dir" ]; then
      restore_user_configs "$backup_dir"
    fi
    cd "$HARBOR_INSTALL_PATH"
  fi
}

doctor_requires_refresh() {
  printf '%s\n' "$1" | grep -qi \
    "Docker requires sudo\|docker group\|newgrp docker\|re-login\|permission denied"
}

doctor_requires_blocked() {
  printf '%s\n' "$1" | grep -qi \
    "Docker daemon is not running\|Docker daemon is not.*reachable\|Docker daemon is not responding\|Please start Docker\|Cannot connect to the Docker daemon\|Start Docker Desktop"
}

acquire_install_lock() {
  HARBOR_LOCK_FILE="${HARBOR_INSTALL_PATH}.lock"
  if command -v flock >/dev/null 2>&1; then
    # Open the lock file on fd 9
    exec 9>"$HARBOR_LOCK_FILE"
    if ! flock -n 9 2>/dev/null; then
      echo "Error: Another Harbor install is already running."
      echo "If this is incorrect, remove $HARBOR_LOCK_FILE and retry."
      exit 1
    fi
  else
    # macOS fallback: mkdir is atomic
    if ! mkdir "$HARBOR_LOCK_FILE.d" 2>/dev/null; then
      echo "Error: Another Harbor install is already running."
      echo "If this is incorrect, remove $HARBOR_LOCK_FILE.d and retry."
      exit 1
    fi
    HARBOR_LOCK_FILE="$HARBOR_LOCK_FILE.d"
  fi
  trap 'rm -rf "$HARBOR_LOCK_FILE" 2>/dev/null' EXIT
}

main() {
  parse_args "$@"
  acquire_install_lock
  # Override the lock-cleanup trap with one that also handles setup stage
  trap 'ec=$?; rm -rf "$HARBOR_LOCK_FILE" 2>/dev/null; if [ $ec -ne 0 ]; then case "$_LAST_SETUP_STAGE" in failed|blocked|refresh-required|ready) ;; *) echo "HARBOR_SETUP_STAGE=failed" ;; esac; fi' EXIT

  setup_stage "checking-platform"
  echo "Installing Harbor."

  # Early WSL checks that apply regardless of --skip-requirements
  if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null || [ -n "${WSL_INTEROP:-}" ]; then
    # Warn if HARBOR_INSTALL_PATH is on a Windows-mounted filesystem
    local install_mount
    install_mount=$(df -P "$(dirname "$HARBOR_INSTALL_PATH")" 2>/dev/null | awk 'NR==2 {print $6}')
    if [ -n "$install_mount" ] && echo "$install_mount" | grep -q "^/mnt/[a-zA-Z]"; then
      echo "Warning: Install path ($HARBOR_INSTALL_PATH) is on a Windows filesystem ($install_mount)."
      echo "Warning: File operations on /mnt/ paths are significantly slower than the Linux filesystem."
      echo "Warning: Consider: HARBOR_INSTALL_PATH=~/.harbor (on ext4) for better performance."
    fi
  fi

  if [ "$INSTALL_REQUIREMENTS" = true ]; then
    setup_stage "installing-prerequisites"
    echo "Installing requirements..."
    if [ -n "$HARBOR_REQUIREMENTS_PATH" ]; then
      if ! bash "$HARBOR_REQUIREMENTS_PATH"; then
        echo "Error: Requirements installer failed (script: $HARBOR_REQUIREMENTS_PATH)." >&2
        echo "Review the error messages above for details." >&2
        echo "You can also install dependencies manually (Docker, git, curl) and retry with --skip-requirements." >&2
        exit 1
      fi
    else
      if ! (set -o pipefail; curl -fsSL "$HARBOR_REQUIREMENTS_URL" | bash); then
        echo "Error: Requirements installer failed." >&2
        echo "Review the error messages above for details." >&2
        echo "If the download failed, check your internet connection." >&2
        echo "You can also install dependencies manually (Docker, git, curl) and retry with --skip-requirements." >&2
        exit 1
      fi
    fi

    # Homebrew on Apple Silicon installs to /opt/homebrew which may not be in
    # PATH. The requirements script may have installed tools via brew in a
    # piped subprocess whose PATH changes were lost.
    for _brew_path in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [ -x "$_brew_path" ]; then
        eval "$("$_brew_path" shellenv 2>/dev/null)" || true
        break
      fi
    done
    unset _brew_path
  fi

  setup_stage "installing-cli"
  echo "Resolving version..."
  if [ -z "$HARBOR_VERSION" ]; then
    if [ -n "$HARBOR_INSTALL_SOURCE_PATH" ]; then
      HARBOR_VERSION="source"
    else
      HARBOR_VERSION=$(resolve_harbor_version) || true
    fi
  fi

  if [ -z "$HARBOR_VERSION" ]; then
    echo "Error: Unable to resolve Harbor version. Check your network connection and retry."
    exit 1
  else
    echo "Resolved Harbor version: $HARBOR_VERSION"
  fi

  echo "Starting installation..."
  install_or_update_project

  # Merge new config keys from default.env into existing .env
  # (harbor update does this, but install.sh didn't — new keys were missing after upgrade)
  if [ -f "$HARBOR_INSTALL_PATH/.env" ] && [ -f "$HARBOR_INSTALL_PATH/profiles/default.env" ]; then
    echo "Merging configuration..."
    ./harbor.sh config update
  fi

  ./harbor.sh -v
  ./harbor.sh ln

  echo ""
  setup_stage "verifying-cli"
  if doctor_output=$(./harbor.sh doctor 2>&1); then
    printf '%s\n' "$doctor_output"
  else
    printf '%s\n' "$doctor_output"
    if doctor_requires_blocked "$doctor_output"; then
      setup_stage "blocked"
      echo "Harbor CLI is installed, but Docker is not reachable."
      echo "Start Docker Desktop or the Docker daemon, then retry Harbor App setup."
      exit 1
    fi
    if doctor_requires_refresh "$doctor_output"; then
      setup_stage "refresh-required"
      echo "Harbor CLI is installed, but Docker access needs a refreshed shell session."
      echo "Re-login or run 'newgrp docker', then retry Harbor App setup."
      exit 1
    fi
    setup_stage "failed"
    echo "Error: Harbor verification failed. Resolve the doctor errors above, then retry setup."
    exit 1
  fi
  setup_stage "ready"
  echo "Installation complete."
  if [ "${HARBOR_APP:-}" != "1" ]; then
    echo "Restart your shell, then run 'harbor doctor' to verify your setup."
  fi
}

main "$@"
