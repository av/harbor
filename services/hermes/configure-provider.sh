#!/bin/sh
# Harbor: point Hermes at a Harbor-managed OpenAI-compatible backend.
#
# Hermes resolves its inference provider from ~/.hermes/config.yaml
# (HERMES_HOME=/opt/data in Harbor), not from OPENAI_BASE_URL alone —
# with only env vars set it falls back to OpenRouter and the config's
# default model. When a Harbor cross-service file provides
# HERMES_PROVIDER_BASE_URL (and optionally HERMES_PROVIDER_MODEL),
# persist them into the config's model section before starting.
set -e

if [ -n "${HERMES_PROVIDER_BASE_URL:-}" ]; then
    python3 - <<'EOF'
import os
import yaml

path = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "config.yaml")
cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

model = cfg.setdefault("model", {})
model["provider"] = "custom"
model["base_url"] = os.environ["HERMES_PROVIDER_BASE_URL"]
if os.environ.get("HERMES_PROVIDER_MODEL"):
    model["default"] = os.environ["HERMES_PROVIDER_MODEL"]

tmp = f"{path}.harbor-tmp"
with open(tmp, "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
os.replace(tmp, path)
print(f"[harbor] hermes provider -> custom {model['base_url']} "
      f"model={model.get('default', '(unchanged)')}")
EOF
fi

exec /opt/hermes/docker/entrypoint.sh "$@"
