#!/usr/bin/env bash

set -eo pipefail

echo "Harbor: ollama init"

main() {
  pull_default_models
  # Wait a little bit for the docker to detach to avoid
  # printing "container exited (0)" message (which is not an error, but could look like one)
  sleep 15
}

pull_default_models() {
  echo "Pulling default models:"
  echo $HARBOR_OLLAMA_DEFAULT_MODELS

  # We're in "ollama-init", but actual ollama runs
  # in the "ollama" container, so we need to point the CLI
  export OLLAMA_HOST=http://ollama:11434

  if [ -z "$HARBOR_OLLAMA_DEFAULT_MODELS" ]; then
    echo "No default models to pull"
    return
  fi

  echo "Pulling default models"
  IFS=',' read -ra models <<< "$HARBOR_OLLAMA_DEFAULT_MODELS"
  for model in "${models[@]}"; do
    echo "Pulling model $model"
    ollama pull $model
  done
}

main