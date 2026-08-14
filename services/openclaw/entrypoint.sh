#!/bin/sh
set -e

GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-${HARBOR_OPENCLAW_HOST_PORT:-34721}}"
GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-${HARBOR_OPENCLAW_GATEWAY_BIND:-lan}}"
GATEWAY_MODE="${HARBOR_OPENCLAW_GATEWAY_MODE:-local}"
GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-${HARBOR_OPENCLAW_GATEWAY_TOKEN:-}}"
AUTO_APPROVE_UI="${HARBOR_OPENCLAW_AUTO_APPROVE_UI:-true}"
DEFAULT_MODEL="${HARBOR_OPENCLAW_MODEL:-}"
BACKEND_NAME="${HARBOR_BACKEND_NAME:-ollama}"
BACKEND_URL="${HARBOR_BACKEND_URL:-http://ollama:11434}"
BACKEND_API_KEY="${HARBOR_BACKEND_API_KEY:-}"
# Allow cross-integration files to drop a sidecar key file (e.g.
# unsloth-studio) instead of substituting at compose-create time. Read
# at runtime so the very first `harbor up <backend> openclaw` picks up
# the freshly minted key without a second pass.
BACKEND_API_KEY_FILE="${HARBOR_BACKEND_API_KEY_FILE:-}"
if [ -n "$BACKEND_API_KEY_FILE" ] && [ -r "$BACKEND_API_KEY_FILE" ]; then
  k=$(tr -d '\n' < "$BACKEND_API_KEY_FILE")
  if [ -n "$k" ]; then
    BACKEND_API_KEY="$k"
  fi
fi
# Fall back to the backend service name as a placeholder for backends
# that don't validate auth (ollama, llamacpp). Preserves existing
# behavior.
if [ -z "$BACKEND_API_KEY" ]; then
  BACKEND_API_KEY="$BACKEND_NAME"
fi
CONTEXT_LENGTH="${HARBOR_OPENCLAW_CONTEXT_WINDOW:-16384}"
CONFIG_PATH="/home/node/.openclaw/openclaw.json"

if [ "$#" -gt 0 ]; then
  exec node dist/index.js "$@"
fi

# Always regenerate config from env vars on container start
# This ensures backend/model changes are picked up on restart
if [ -z "$DEFAULT_MODEL" ]; then
  echo "HARBOR_OPENCLAW_MODEL is empty. Set it to a model ID (example: llama3.1:8b) and restart." >&2
  exit 1
fi

if [ -z "$GATEWAY_TOKEN" ]; then
  echo "HARBOR_OPENCLAW_GATEWAY_TOKEN is empty. Set it (harbor config set openclaw.gateway_token \"...\") and restart." >&2
  exit 1
fi

mkdir -p /home/node/.openclaw

# Ensure model ID includes provider prefix for OpenClaw's model resolution
# OpenClaw expects format in agents.defaults.model.primary: "provider/model-id"
# But models array should have model ID WITHOUT provider prefix
# Examples:
#   Primary: "llamacpp/unsloth/GLM-4.7-Flash-GGUF:Q8_0"
#   Models array: "unsloth/GLM-4.7-Flash-GGUF:Q8_0"
if echo "${DEFAULT_MODEL}" | grep -q "^${BACKEND_NAME}/"; then
  # Model already has correct provider prefix - use as-is for primary
  MODEL_PRIMARY="${DEFAULT_MODEL}"
  # Strip provider prefix for models array
  MODEL_BARE="${DEFAULT_MODEL#${BACKEND_NAME}/}"
else
  # Model lacks provider prefix - add it for primary
  MODEL_PRIMARY="${BACKEND_NAME}/${DEFAULT_MODEL}"
  # Use as-is for models array (already without provider)
  MODEL_BARE="${DEFAULT_MODEL}"
fi

# Check if config exists - if not, create initial template
if [ ! -f "$CONFIG_PATH" ]; then
  echo "Creating initial openclaw configuration..."
  cat > "$CONFIG_PATH" <<EOF
{
  "gateway": {
    "mode": "${GATEWAY_MODE}",
    "auth": {
      "mode": "token",
      "token": "${GATEWAY_TOKEN}"
    },
    "remote": {
      "token": "${GATEWAY_TOKEN}"
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "${MODEL_PRIMARY}"
      }
    }
  },
  "models": {
    "providers": {
      "${BACKEND_NAME}": {
        "baseUrl": "${BACKEND_URL}/v1",
        "apiKey": "${BACKEND_API_KEY}",
        "api": "openai-completions",
        "models": [
          {
            "id": "${MODEL_BARE}",
            "name": "${MODEL_BARE}",
            "reasoning": false,
            "input": ["text"],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "contextWindow": ${CONTEXT_LENGTH},
            "maxTokens": ${CONTEXT_LENGTH}
          }
        ]
      }
    }
  }
}
EOF
else
  # Config exists - update only dynamic fields to preserve user customizations
  echo "Updating openclaw configuration with current backend settings..."
  node -e "
    const fs = require('fs');
    const config = JSON.parse(fs.readFileSync('$CONFIG_PATH', 'utf8'));

    // Update gateway tokens (guard nested objects — user configs may
    // not carry gateway.auth / gateway.remote / controlUi at all)
    if (!config.gateway) config.gateway = {};
    // Upstream blocks gateway start when gateway.mode is absent; backfill it
    if (!config.gateway.mode) config.gateway.mode = '${GATEWAY_MODE}';
    if (!config.gateway.auth) config.gateway.auth = { mode: 'token' };
    if (!config.gateway.remote) config.gateway.remote = {};
    config.gateway.auth.token = '$GATEWAY_TOKEN';
    config.gateway.remote.token = '$GATEWAY_TOKEN';
    // Upstream removed controlUi.allowInsecureAuth; scrub it from older configs
    if (config.gateway.controlUi) delete config.gateway.controlUi.allowInsecureAuth;
    // Upstream also dropped meta.lastTouchedAt from the schema
    if (config.meta) delete config.meta.lastTouchedAt;

    // Update default model (with provider prefix)
    if (!config.agents) config.agents = {};
    if (!config.agents.defaults) config.agents.defaults = {};
    if (!config.agents.defaults.model) config.agents.defaults.model = {};
    config.agents.defaults.model.primary = '${MODEL_PRIMARY}';

    // Update backend provider configuration
    if (!config.models) config.models = {};
    if (!config.models.providers) config.models.providers = {};
    if (!config.models.providers['${BACKEND_NAME}']) {
      config.models.providers['${BACKEND_NAME}'] = {
        apiKey: '${BACKEND_API_KEY}',
        api: 'openai-completions',
        models: []
      };
    }
    config.models.providers['${BACKEND_NAME}'].baseUrl = '${BACKEND_URL}/v1';
    config.models.providers['${BACKEND_NAME}'].apiKey = '${BACKEND_API_KEY}';

    // Update or add the model in the provider's models array (without provider prefix)
    const models = config.models.providers['${BACKEND_NAME}'].models || [];

    let modelEntry = models.find(m => m.id === '${MODEL_BARE}');
    if (!modelEntry) {
      modelEntry = {
        id: '${MODEL_BARE}',
        name: '${MODEL_BARE}',
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }
      };
      models.push(modelEntry);
    }
    modelEntry.contextWindow = ${CONTEXT_LENGTH};
    modelEntry.maxTokens = ${CONTEXT_LENGTH};
    config.models.providers['${BACKEND_NAME}'].models = models;

    fs.writeFileSync('$CONFIG_PATH', JSON.stringify(config, null, 2));
  "
fi

# Migrate legacy state (device identity, schema drift) that upstream
# refuses to auto-repair at gateway start
node dist/index.js doctor --fix --non-interactive >/dev/null 2>&1 || true

rm -f /home/node/.openclaw/gateway*.loc /home/node/.openclaw/gateway*.lock /home/node/.openclaw/gateway*.pid

node dist/index.js gateway --bind "$GATEWAY_BIND" --port "$GATEWAY_PORT" &
GATEWAY_PID=$!

if [ "$AUTO_APPROVE_UI" = "true" ]; then
  (
    while kill -0 "$GATEWAY_PID" 2>/dev/null; do
      sleep 2
      pending_ids=$(node dist/index.js devices list --json --url "ws://127.0.0.1:$GATEWAY_PORT" --token "$GATEWAY_TOKEN" 2>/dev/null | node -e 'let d="";process.stdin.on("data",c=>d+=c);process.stdin.on("end",()=>{try{const j=JSON.parse(d);const ids=(j.pending||[]).filter(p=>p.role==="operator").map(p=>p.requestId);process.stdout.write(ids.join(" "));}catch(e){}});')
      for req in $pending_ids; do
        node dist/index.js devices approve "$req" --url "ws://127.0.0.1:$GATEWAY_PORT" --token "$GATEWAY_TOKEN" >/dev/null 2>&1 || true
      done
    done
  ) &
fi

wait "$GATEWAY_PID"
