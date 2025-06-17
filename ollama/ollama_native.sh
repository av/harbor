#!/usr/bin/env bash
# ollama/native.sh
#
# This script is the entrypoint for running Ollama natively via Harbor.
# It's called by harbor.sh when the 'ollama' service is started in native mode.
# It should primarily execute the native `ollama serve` command.
#
# Note: This script is executed directly by harbor.sh. Its stdout/stderr
# are redirected to logs/harbor-ollama-native.log.

set -euo pipefail # Strict mode for robustness.

# Attempt to find the `ollama` binary in the system's PATH.
# This assumes 'ollama' is already installed on the host machine.
OLLAMA_BIN=$(command -v ollama)

if [[ -z "$OLLAMA_BIN" ]]; then
    # Print to stderr which will be redirected to the log file.
    echo "ERROR: Ollama binary 'ollama' not found in system's PATH." >&2
    echo "Please ensure Ollama is installed and its executable is accessible (e.g., /usr/local/bin/ollama)." >&2
    exit 1
fi

# Execute the native Ollama server command.
# The 'serve' command typically starts the API server on its default port (11434)
# or respects environment variables/configuration.
# Any custom arguments or ports should be handled by Ollama's own configuration
# or passed here if `native_command` in `harbor-native.yml` specifies them.
exec "$OLLAMA_BIN" serve "$@"
