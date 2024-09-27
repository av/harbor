#!/bin/ash

log() {
  if [ "$HARBOR_LOG_LEVEL" == "DEBUG" ]; then
    echo "$1"
  fi
}

log "Harbor: custom librechat entrypoint"

log YAML Merger is starting...
node /app/yaml_config_merger.mjs --pattern ".yml" --output "/app/librechat.yaml" --directory "/app/configs"
cat /app/librechat.yaml

log echo "Starting librechat with args: '$*'"

# Function to handle shutdown
shutdown() {
    echo "Shutting down..."
    exit 0
}

# Trap SIGTERM and SIGINT signals and call shutdown()
trap shutdown TERM INT
# Original entrypoint
npm run backend -- $@
# Wait for the process to finish or for a signal to be caught
wait $!