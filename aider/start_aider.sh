#!/bin/bash

# These configs will be added by
# respective parts of Harbor stack, we want to merge
# everything into one file and launch the server
echo "Harbor: custom aider entrypoint"
python --version

echo "YAML Merger is starting..."
python /home/appuser/.aider/yaml_config_merger.py --pattern ".yml" --output "/home/appuser/.aider.conf.yml" --directory "/home/appuser/.aider"

echo "Merged Configs:"
cat /home/appuser/.aider.conf.yml

git config --global --add safe.directory /root/workspace

echo "Starting aider with args: '$*'"
aider $@
