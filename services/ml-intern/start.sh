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

def score_llamacpp_model(model_id: str, status: str) -> tuple[int, str]:
    normalized = model_id.lower()
    score = 0

    if status.lower() in {"loaded", "ready", "running"}:
        score += 25

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
    if any(term in normalized for term in unsuitable_terms):
        score -= 1000

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
            ranked = sorted(
                models,
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

if [ "${ML_INTERN_MODEL:-}" = "llamacpp/auto" ]; then
  resolved="$(resolve_llamacpp_model)"
  export ML_INTERN_MODEL="llamacpp/${resolved}"
  echo "Resolved ML_INTERN_MODEL=${ML_INTERN_MODEL}"
fi

cd /app/backend
exec bash start.sh
