#!/bin/bash

echo "Harbor: Custom Tabby API Entrypoint"
python --version

python /app/yaml_config_merger.py --pattern ".yml" --output "/config.yml" --directory "/app/configs"
python /app/yaml_config_merger.py --pattern ".yml" --output "/api_tokens.yml" --directory "/app/tokens"

echo "Merged Configs:"
cat /config.yml

echo "Merged Tokens:"
cat /api_tokens.yml

# Original entrypoint
python3 /app/main.py $@