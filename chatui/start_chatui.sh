#!/bin/bash

echo "Harbor: Custom ChatUI Entrypoint"
node --version

echo "YAML Merger is starting..."
node /app/yaml_config_merger.js --pattern ".yml" --output "/app/final.yaml" --directory "/app/configs"

echo "Merged Configs:"
cat /app/final.yaml

echo "Transforming to .env.local..."
node /app/envify.js

echo "Final .env.local:"
cat /app/.env.local

echo
echo "Starting ChatUI..."

# Function to handle shutdown
shutdown() {
    echo "Shutting down..."
    exit 0
}

# Trap SIGTERM and SIGINT signals and call shutdown()
trap shutdown SIGTERM SIGINT

# Original entrypoint
bash entrypoint.sh &
# Wait for the process to finish or for a signal to be caught
wait $!