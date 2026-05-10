#!/bin/bash

echo "Harbor: Custom Tabby API Entrypoint"
python3 --version

python3 /app/yaml_config_merger.py --pattern ".yml" --output "/app/config.yml" --directory "/app/configs"
python3 /app/yaml_config_merger.py --pattern ".yml" --output "/app/api_tokens.yml" --directory "/app/tokens"

echo "Merged Configs:"
cat /app/config.yml

echo "Merged Tokens:"
cat /app/api_tokens.yml

# Original entrypoint
python3 /app/main.py "$@"