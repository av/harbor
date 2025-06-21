#!/usr/bin/env bash
# ollama/ollama_native.sh
#
# Native Service Entrypoint for Ollama in Harbor
#
# This script serves as the entrypoint for running Ollama natively via Harbor's
# hybrid orchestration system. It follows the Docker-style ENTRYPOINT + CMD
# pattern where Harbor passes the complete command to execute.
#
# DESIGN PATTERN:
# This script uses the simple "exec "$@"" pattern, which works well for services
# like Ollama that have straightforward execution requirements. Other services
# may need customized scripts for setup, validation, or special handling.
#
# USAGE PATTERNS:
# Harbor calls this script with the full command to execute:
#
# Daemon Startup:
#   ollama_native.sh "ollama" "serve"
#
# User Commands (via `harbor run ollama`):
#   ollama_native.sh "ollama" "list"
#   ollama_native.sh "ollama" "pull" "llama2"
#
# WHEN TO CUSTOMIZE THIS SCRIPT:
# The simple "exec "$@"" pattern works for Ollama, but other services may need:
# - Pre-execution setup (environment variables, config files)
# - Binary validation and error handling
# - Post-execution cleanup
# - Service-specific argument processing
# - Health checks or initialization steps
#
# Examples of services that might need custom scripts:
# - Services requiring specific environment setup
# - Services with complex initialization sequences
# - Services needing configuration file generation
# - Services with multiple binaries or wrapper scripts
#
# EXECUTABLE NAME SCENARIOS:
# 1. Same as service handle: "ollama" service uses "ollama" executable
# 2. Different name: Service uses different executable name
# 3. Custom path: Service uses executable at specific path
# 4. Complex args: Executable with multiple flags and parameters
#
# ERROR HANDLING:
# This script provides helpful validation and error messages:
# - Validates executable exists (in PATH or as full path)
# - Checks file permissions for full paths
# - Provides clear, actionable error messages
# - Falls back to shell error handling for other issues
# This gives much better user experience than raw "command not found" errors.
#
# LOGGING:
# This script's stdout/stderr are redirected to Harbor's log directory:
# $HARBOR_HOME/app/backend/data/logs/harbor-ollama-native.log

set -euo pipefail # Strict mode for robustness.

# Validate that we have arguments to execute
if [[ $# -eq 0 ]]; then
    echo "ERROR: No command provided to execute." >&2
    echo "Usage: $0 <executable> [args...]" >&2
    exit 1
fi

# Extract the executable name (first argument) for validation
EXECUTABLE="$1"

# Attempt to find the executable in the system's PATH or validate if it's a full path
if [[ "$EXECUTABLE" == /* ]]; then
    # Full path provided - check if file exists and is executable
    if [[ ! -f "$EXECUTABLE" ]]; then
        echo "ERROR: Executable '$EXECUTABLE' not found." >&2
        exit 1
    elif [[ ! -x "$EXECUTABLE" ]]; then
        echo "ERROR: File '$EXECUTABLE' is not executable." >&2
        echo "Try: chmod +x '$EXECUTABLE'" >&2
        exit 1
    fi
else
    # Binary name provided - check if it's in PATH
    if ! command -v "$EXECUTABLE" &>/dev/null; then
        echo "ERROR: Executable '$EXECUTABLE' not found in system's PATH." >&2
        echo "Please ensure $EXECUTABLE is installed and accessible." >&2
        echo "You can check with: command -v $EXECUTABLE" >&2
        exit 1
    fi
fi

# Execute whatever command Harbor passed to us.
# This follows the standard Docker entrypoint pattern of "exec "$@""
# which means "execute all the arguments as a command".
#
# Harbor calls this script like: ollama_native.sh "ollama" "serve"
# So "$@" becomes: "ollama" "serve"
# And this executes: exec ollama serve
exec "$@"
