#!/bin/bash
set -euo pipefail

resolve_github_token() {
  if [ -z "${GITHUB_TOKEN:-}" ] && [ -n "${HARBOR_ML_INTERN_GITHUB_TOKEN:-}" ]; then
    export GITHUB_TOKEN="$HARBOR_ML_INTERN_GITHUB_TOKEN"
  fi
}

patch_llm_health_status() {
  python - <<'PY'
import os
from pathlib import Path

app_root = Path(os.environ.get("ML_INTERN_APP_ROOT", "/app"))
route_path = app_root / "backend/routes/agent.py"
if not route_path.exists():
    print(f"ML Intern health route not found at {route_path}; skipping patch")
    raise SystemExit(0)

source = route_path.read_text(encoding="utf-8")
patched = source

patched = patched.replace(
    "from fastapi.responses import StreamingResponse",
    "from fastapi.responses import JSONResponse, StreamingResponse",
)

old = """        return LLMHealthResponse(
            status=\"error\",
            model=model,
            error=str(e)[:500],
            error_type=error_type,
        )
"""
new = """        return JSONResponse(
            status_code=503,
            content=LLMHealthResponse(
                status=\"error\",
                model=model,
                error=str(e)[:500],
                error_type=error_type,
            ).model_dump(),
        )
"""

if old not in patched:
    print("ML Intern health route pattern not found; skipping status-code patch")
    raise SystemExit(0)

patched = patched.replace(old, new, 1)

if patched != source:
    route_path.write_text(patched, encoding="utf-8")
    print("Patched ML Intern LLM health endpoint to return status_code=503 on errors")
PY
}

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

def is_suitable_llamacpp_model(model_id: str) -> bool:
    normalized = model_id.lower()
    unsuitable_terms = [
        "image",
        "vision",
        "vl",
        "clip",
        "embed",
        "embedding",
        "bge",
        "rerank",
        "whisper",
        "stt",
        "tts",
        "audio",
    ]
    return not any(term in normalized for term in unsuitable_terms)

def score_llamacpp_model(model_id: str, status: str) -> tuple[int, str]:
    normalized = model_id.lower()
    score = 0

    if status.lower() in {"loaded", "ready", "running"}:
        score += 25

    quality_hints = [
        ("coder", 300),
        ("code", 220),
        ("instruct", 220),
        ("chat", 180),
        ("qwen", 120),
        ("llama", 100),
        ("gemma", 100),
        ("mistral", 100),
        ("deepseek", 100),
        ("phi", 80),
    ]
    for term, value in quality_hints:
        if term in normalized:
            score += value
            break

    quant_bonus = [
        ("q8", 35),
        ("q6", 30),
        ("q5", 25),
        ("q4", 20),
        ("iq4", 20),
        ("q3", 5),
        ("iq3", 5),
        ("q2", -20),
        ("q1", -60),
    ]
    for term, value in quant_bonus:
        if term in normalized:
            score += value
            break

    import re

    sizes = [float(match.group(1)) for match in re.finditer(r"(\d+(?:\.\d+)?)b", normalized)]
    if sizes:
        size = max(sizes)
        if 4 <= size <= 14:
            score += 80
        elif 2 <= size < 4:
            score += 40
        elif 14 < size <= 35:
            score += 25
        elif size < 2:
            score -= 20
    else:
        score -= 360

    return score, model_id


for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)

        models = [model for model in payload.get("data") or [] if model.get("id")]
        if models:
            suitable_models = [
                model for model in models if is_suitable_llamacpp_model(model.get("id", ""))
            ]
            if not suitable_models:
                raise SystemExit(
                    f"No suitable llama.cpp text/code model returned by {url}; "
                    f"advertised ids: {', '.join(model['id'] for model in models)}"
                )

            ranked = sorted(
                suitable_models,
                key=lambda model: score_llamacpp_model(
                    model.get("id", ""),
                    ((model.get("status") or {}).get("value") or ""),
                ),
                reverse=True,
            )
            print(ranked[0]["id"])
            print(
                "Selected llama.cpp model "
                f"{ranked[0]['id']} from {len(models)} advertised models",
                file=sys.stderr,
            )
            raise SystemExit(0)

        last_error = f"No models returned by {url}"
    except (OSError, urllib.error.URLError) as exc:
        last_error = str(exc)

    time.sleep(1)

raise SystemExit(f"Could not resolve llama.cpp model from {url}: {last_error}")
PY
}

resolve_github_token

if [ "${ML_INTERN_MODEL:-}" = "llamacpp/auto" ]; then
  resolved="$(resolve_llamacpp_model)"
  export ML_INTERN_MODEL="llamacpp/${resolved}"
  echo "Resolved ML_INTERN_MODEL=${ML_INTERN_MODEL}"
fi

patch_llm_health_status

cd /app/backend
exec bash start.sh
