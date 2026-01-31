#!/bin/bash

# These configs will be added by
# respective parts of Harbor stack, we want to merge
# everything into one file and launch the server
echo "Harbor: Custom LiteLLM Entrypoint"
python --version

echo "YAML Merger is starting..."
python /app/yaml_config_merger.py --pattern ".yaml" --output "/app/proxy.yaml" --directory "/app/litellm"

echo "Merged Configs:"
cat /app/proxy.yaml

echo "Litellm is starting..."
litellm $@