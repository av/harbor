#!/bin/ash
# shellcheck shell=dash

log() {
  if [ "$HARBOR_LOG_LEVEL" = "DEBUG" ]; then
    echo "$1"
  fi
}

log "Harbor: custom chatnio entrypoint"

log YAML Merger is starting...
python /app/yaml_config_merger.py --pattern ".yml" --output "/config/config.yaml" --directory "/configs"

# Upstream warns (and may panic in future versions) when the secret is <32 bytes
if [ -n "$HARBOR_CHATNIO_SECRET" ]; then
  sed "s|^secret:.*|secret: $HARBOR_CHATNIO_SECRET|" /config/config.yaml > /tmp/config.yaml && mv /tmp/config.yaml /config/config.yaml
fi

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
trap shutdown TERM INT

# Original entrypoint
./chat &
# Wait for the process to finish or for a signal to be caught
wait $!