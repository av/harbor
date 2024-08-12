#!/bin/bash

# These configs will be added by
# respective parts of Harbor stack, we want to merge
# everything into one file and launch the server
echo "Harbor: custom aider entrypoint"
python --version

echo "YAML Merger is starting..."
python /root/.aider/yaml_config_merger.py --pattern ".yml" --output "/root/.aider.conf.yml" --directory "/root/.aider"

echo "Merged Configs:"
cat /root/.aider.conf.yml

git config --global --add safe.directory /root/workspace

echo "Starting aider with args: '$*'"
aider $@
