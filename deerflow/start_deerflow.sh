#!/bin/bash

log() {
  if [ "$HARBOR_LOG_LEVEL" == "DEBUG" ]; then
    echo "$1"
  fi
}

log "Harbor: custom deerflow entrypoint"

log "Merging config files..."
# Simple config merger - concatenate all .yaml files alphabetically
cat /app/configs/*.yaml > /app/conf.yaml 2>/dev/null || echo "# No config files found" > /app/conf.yaml

# Replace environment variables in the generated config
log "Rendering environment variables..."
# Use sed to replace ${VAR_NAME} patterns with actual values
sed -i "s|\${HARBOR_OLLAMA_INTERNAL_URL}|${HARBOR_OLLAMA_INTERNAL_URL}|g" /app/conf.yaml
sed -i "s|\${HARBOR_DEERFLOW_MODEL}|${HARBOR_DEERFLOW_MODEL}|g" /app/conf.yaml

log "Merged Configs:"
if [ "$HARBOR_LOG_LEVEL" == "DEBUG" ]; then
  cat /app/conf.yaml
fi

log "Starting DeerFlow backend..."
exec uv run python server.py --host 0.0.0.0 --port 8000
