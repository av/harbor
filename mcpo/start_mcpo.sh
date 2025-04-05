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
uvx mcpo --config /app/config.json &
# Wait for the process to finish or for a signal to be caught
wait $!