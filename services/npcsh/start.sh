#!/usr/bin/env bash
set -euo pipefail

mkdir -p /root/.npcsh /data /workspace

cat > /root/.npcshrc <<EOF
export NPCSH_INITIALIZED="${NPCSH_INITIALIZED:-1}"
export NPCSH_DEFAULT_MODE="${NPCSH_DEFAULT_MODE:-agent}"
export NPCSH_BUILD_KG="${NPCSH_BUILD_KG:-0}"
export NPCSH_CHAT_PROVIDER="${NPCSH_CHAT_PROVIDER:-ollama}"
export NPCSH_CHAT_MODEL="${NPCSH_CHAT_MODEL:-qwen3.5:4b}"
export NPCSH_REASONING_PROVIDER="${NPCSH_REASONING_PROVIDER:-ollama}"
export NPCSH_REASONING_MODEL="${NPCSH_REASONING_MODEL:-qwen3.5:4b}"
export NPCSH_EMBEDDING_PROVIDER="${NPCSH_EMBEDDING_PROVIDER:-ollama}"
export NPCSH_EMBEDDING_MODEL="${NPCSH_EMBEDDING_MODEL:-nomic-embed-text}"
export NPCSH_VISION_PROVIDER="${NPCSH_VISION_PROVIDER:-ollama}"
export NPCSH_VISION_MODEL="${NPCSH_VISION_MODEL:-qwen3.5:4b}"
export NPCSH_IMAGE_GEN_PROVIDER="${NPCSH_IMAGE_GEN_PROVIDER:-ollama}"
export NPCSH_IMAGE_GEN_MODEL="${NPCSH_IMAGE_GEN_MODEL:-x/z-image-turbo}"
export NPCSH_VIDEO_GEN_PROVIDER="${NPCSH_VIDEO_GEN_PROVIDER:-diffusers}"
export NPCSH_VIDEO_GEN_MODEL="${NPCSH_VIDEO_GEN_MODEL:-damo-vilab/text-to-video-ms-1.7b}"
export NPCSH_API_URL="${NPCSH_API_URL:-}"
export NPCSH_DB_PATH="${NPCSH_DB_PATH:-/data/npcsh_history.db}"
export NPCSH_VECTOR_DB_PATH="${NPCSH_VECTOR_DB_PATH:-/data/npcsh_chroma.db}"
export NPCSH_STREAM_OUTPUT="${NPCSH_STREAM_OUTPUT:-0}"
export NPCSH_ENGINE="${NPCSH_ENGINE:-python}"
EOF

if [ -n "${NPCSH_API_URL:-}" ]; then
  export OPENAI_BASE_URL="${OPENAI_BASE_URL:-${NPCSH_API_URL}}"
  export OPENAI_API_BASE="${OPENAI_API_BASE:-${NPCSH_API_URL}}"
fi

exec python /opt/harbor/npcsh/server.py
