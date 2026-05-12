#!/bin/bash
set -euo pipefail

resolve_llamacpp_model() {
  local base="${LLAMACPP_BASE_URL:-${LOCAL_LLM_BASE_URL:-}}"
  local catalog_url

  if [ -z "$base" ]; then
    echo "ML_INTERN_MODEL is '$ML_INTERN_MODEL' but LLAMACPP_BASE_URL is empty" >&2
    return 1
  fi

  base="${base%/}"
  catalog_url="${base%/v1}/v1/models"

  python - "$catalog_url" <<'PY'
import json
import sys
import time
import urllib.request
import urllib.error

url = sys.argv[1]
last_error = None

for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)

        models = payload.get("data") or []
        for model in models:
            model_id = model.get("id")
            if model_id:
                print(model_id)
                raise SystemExit(0)

        last_error = f"No models returned by {url}"
    except (OSError, urllib.error.URLError) as exc:
        last_error = str(exc)

    time.sleep(1)

raise SystemExit(f"Could not resolve llama.cpp model from {url}: {last_error}")
PY
}

if [ "${ML_INTERN_MODEL:-}" = "llamacpp/auto" ]; then
  resolved="$(resolve_llamacpp_model)"
  export ML_INTERN_MODEL="llamacpp/${resolved}"
  echo "Resolved ML_INTERN_MODEL=${ML_INTERN_MODEL}"
fi

cd /app/backend
exec bash start.sh
