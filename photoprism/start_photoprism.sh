#!/bin/bash

CONFIG_DIR="/photoprism/storage/config"
mkdir -p "$CONFIG_DIR"

sed "s|\${HARBOR_PHOTOPRISM_VISION_MODEL}|${HARBOR_PHOTOPRISM_VISION_MODEL}|g; \
     s|\${HARBOR_OLLAMA_INTERNAL_URL}|${HARBOR_OLLAMA_INTERNAL_URL}|g" \
    /photoprism/vision.yml.template > "$CONFIG_DIR/vision.yml"

exec /init "$@"
