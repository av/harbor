#!/bin/bash

echo "Harbor: Custom Open WebUI Entrypoint"
python --version

# Cross-integration runtime overrides: pick up secrets minted by sidecars
# AFTER Compose's create-time env substitution. Each block is a no-op if
# the sidecar mount isn't present (i.e. the integration isn't enabled).
#
# unsloth-studio: the unsloth-studio-bootstrap sidecar writes the freshly
# minted API key to ./services/unsloth-studio/.studio-auth/api_key.txt,
# which compose.x.webui.unsloth-studio.yml mounts read-only. Read it
# BEFORE the JSON merger renders config.unsloth-studio.json so the
# rendered config.json carries the real key, not the placeholder.
if [ -r /run/unsloth-studio-auth/api_key.txt ]; then
    k=$(tr -d '\n' < /run/unsloth-studio-auth/api_key.txt)
    if [ -n "$k" ]; then
        export HARBOR_UNSLOTH_STUDIO_API_KEY="$k"
    fi
fi

echo "JSON Merger is starting..."
python /app/json_config_merger.py --pattern ".json" --output "/app/backend/data/config.json" --directory "/app/configs" --flatten

echo "Merged Configs:"
cat /app/backend/data/config.json

echo
echo "Starting Open WebUI..."

# Function to handle shutdown
shutdown() {
    echo "Shutting down..."
    exit 0
}

# Trap SIGTERM and SIGINT signals and call shutdown()
trap shutdown SIGTERM SIGINT

# Original entrypoint
bash start.sh &
# Wait for the process to finish or for a signal to be caught
wait $!