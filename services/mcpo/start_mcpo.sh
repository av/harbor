#!/bin/bash

echo "Harbor: MCPO Entrypoint"
uv run python --version

echo "JSON Merger is starting..."
uv run python /app/json_config_merger.py --pattern ".json" --output "/app/config.json" --directory "/app/configs"

echo "Merged Configs:"
cat /app/config.json

echo
echo "Starting MCPO..."

# Function to handle shutdown
shutdown() {
    echo "Shutting down..."
    exit 0
}

# Trap SIGTERM and SIGINT signals and call shutdown()
trap shutdown SIGTERM SIGINT

# Original entrypoint
# mcp<2 pin: mcpo 0.0.20 declares mcp>=1.17.0 but breaks on mcp 2.0.0
# (streamablehttp_client import removed upstream)
# fastapi<0.145 pin: mcpo passes ssl_certfile/ssl_keyfile to FastAPI(), which
# fastapi 0.145+ rejects with a TypeError (open-webui/mcpo#303)
uvx --with 'fastapi<0.145' --with 'mcp<2' mcpo --config /app/config.json &
# Wait for the process to finish or for a signal to be caught
wait $!