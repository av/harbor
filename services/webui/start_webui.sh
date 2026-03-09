#!/bin/bash

echo "Harbor: Custom Open WebUI Entrypoint"
python --version

echo "JSON Merger is starting..."
python /app/json_config_merger.py --pattern ".json" --output "/app/backend/data/config.json" --directory "/app/configs"

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