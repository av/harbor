#!/bin/bash

echo "Harbor: Custom Open WebUI Entrypoint"
python --version

echo "JSON Merger is starting..."
python /app/json_config_merger.py --pattern ".json" --output "/app/backend/data/config.json" --directory "/app/configs"

echo "Merged Configs:"
cat /app/backend/data/config.json

echo
echo "Starting Open WebUI..."

# Original entrypoint
bash start.sh