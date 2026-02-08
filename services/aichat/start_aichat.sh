#!/bin/bash

log() {
  if [ "$HARBOR_LOG_LEVEL" == "DEBUG" ]; then
    echo "$1"
  fi
}

log "Harbor: custom aichat entrypoint"

log "YAML Merger is starting..."
mkdir -p /root/.config/aichat
python /app/yaml_config_merger.py --pattern ".yml" --output "/root/.config/aichat/config.yaml" --directory "/app/configs"

log "Merged Configs:"
log $(cat /root/.config/aichat/config.yaml)

log echo "Starting aichat with args: '$*'"
/app/aichat $@