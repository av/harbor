#!/usr/bin/env bash

set -eo pipefail

echo "Harbor: ollama init"

main() {
  pull_default_models
  # Marker is read by the healthcheck; tail keeps the sidecar in running|healthy
  # so `compose --wait` doesn't flag a clean exit as premature failure.
  mkdir -p /run/harbor && touch /run/harbor/ollama-init-done
  exec tail -f /dev/null
}

pull_default_models() {
  echo "Pulling default models:"
  echo "$HARBOR_OLLAMA_DEFAULT_MODELS"

  # We're in "ollama-init", but actual ollama runs
  # in the "ollama" container, so we need to point the CLI
  export OLLAMA_HOST=http://ollama:11434

  if [ -z "$HARBOR_OLLAMA_DEFAULT_MODELS" ]; then
    echo "No default models to pull"
    return
  fi

  echo "Pulling default models"
  local failed=0
  IFS=',' read -ra models <<< "$HARBOR_OLLAMA_DEFAULT_MODELS"
  for model in "${models[@]}"; do
    # Trim whitespace from model name
    model=$(echo "$model" | tr -d '[:space:]')
    if [ -z "$model" ]; then
      continue
    fi
    echo "Pulling model $model"
    if ! ollama pull "$model"; then
      echo "ERROR: Failed to pull model '$model'. Continuing with remaining models..."
      failed=1
    fi
  done

  if [ "$failed" -eq 1 ]; then
    echo "WARNING: Some models failed to pull. Check the errors above."
    echo "You can retry by restarting: harbor restart ollama"
  fi
}

main
