#!/bin/sh
set -e

CONFIG_DIR="/root/.nanobot"
CONFIG_FILE="$CONFIG_DIR/config.json"

mkdir -p "$CONFIG_DIR"

# Initialize config on first run
if [ ! -f "$CONFIG_FILE" ]; then
    nanobot onboard 2>/dev/null || true
fi

# Patch config with Harbor environment if variables are set
python3 -c "
import json, os, sys

config_path = '$CONFIG_FILE'
try:
    with open(config_path) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    config = {}

changed = False

# Configure backend URL if provided (e.g. Ollama, llamacpp integration)
backend_url = os.environ.get('HARBOR_BACKEND_URL', '')
backend_name = os.environ.get('HARBOR_BACKEND_NAME', '')
if backend_url:
    # nanobot uses 'vllm' provider for any OpenAI-compatible local backend
    # LiteLLM routes via hosted_vllm prefix and strips it for the API call
    config.setdefault('providers', {})['vllm'] = {
        'apiKey': 'harbor',
        'apiBase': backend_url + '/v1',
    }
    print(f'Configured {backend_name} backend at {backend_url}', file=sys.stderr)
    changed = True

# Configure model if provided
model = os.environ.get('HARBOR_NANOBOT_MODEL', '')
if model:
    config.setdefault('agents', {}).setdefault('defaults', {})
    # For local backends, strip any routing prefixes - the model name
    # must match what the backend server reports (e.g. 'noctrex/GLM-...')
    if backend_url:
        for p in ['openai/', 'ollama/', 'hosted_vllm/', 'anthropic/', 'openrouter/']:
            if model.startswith(p):
                model = model[len(p):]
                break
    config['agents']['defaults']['model'] = model
    changed = True

if changed:
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
"

exec nanobot "$@"
