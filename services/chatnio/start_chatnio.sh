#!/bin/ash

log() {
  if [ "$HARBOR_LOG_LEVEL" == "DEBUG" ]; then
    echo "$1"
  fi
}

log "Harbor: custom chatnio entrypoint"

log YAML Merger is starting...
python /app/yaml_config_merger.py --pattern ".yml" --output "/config/config.yaml" --directory "/configs"

log "Merged Configs:"
cat /config/config.yaml

log
log "Starting Chat Nio..."

# Function to handle shutdown
shutdown() {
    log "Shutting down..."
    exit 0
}

# Trap SIGTERM and SIGINT signals and call shutdown()
trap shutdown SIGTERM SIGINT

# Original entrypoint
./chat &
# Wait for the process to finish or for a signal to be caught
wait $!