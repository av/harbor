import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from huggingface_hub import hf_hub_download

app = FastAPI(title="Harbor Needle", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.Lock()
_model = None
_params = None
_tokenizer = None
_checkpoint_path = None
_startup_error = None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 4096) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def _clamp_int(value: Any, default: int, minimum: int = 1, maximum: int = 4096) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _model_id() -> str:
    return os.getenv("NEEDLE_MODEL", "needle") or "needle"


def _download_checkpoint() -> str:
    checkpoint_dir = Path(os.getenv("NEEDLE_CHECKPOINT_DIR", "/data/checkpoints"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return hf_hub_download(
        repo_id=os.getenv("NEEDLE_MODEL_REPO", "Cactus-Compute/needle"),
        filename=os.getenv("NEEDLE_MODEL_FILE", "needle.pkl"),
        repo_type="model",
        local_dir=str(checkpoint_dir),
        force_download=_env_bool("NEEDLE_FORCE_DOWNLOAD", False),
    )


def _load_model() -> None:
    global _model, _params, _tokenizer, _checkpoint_path, _startup_error
    if _model is not None:
        return

    with _lock:
        if _model is not None:
            return
        try:
            from needle.dataset.dataset import get_tokenizer
            from needle.model.architecture import SimpleAttentionNetwork
            from needle.model.run import load_checkpoint

            _checkpoint_path = _download_checkpoint()
            _params, config = load_checkpoint(_checkpoint_path)
            _model = SimpleAttentionNetwork(config)
            _tokenizer = get_tokenizer()
            _startup_error = None
        except Exception as exc:
            _startup_error = str(exc)
            raise


@app.on_event("startup")
def startup() -> None:
    _load_model()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    status = "loaded" if _model is not None else "not loaded"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Needle API</title>
  <style>
    body {{ margin: 0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #101418; color: #edf2f7; }}
    main {{ min-height: 100vh; display: grid; place-items: center; padding: 48px; box-sizing: border-box; }}
    section {{ width: min(860px, 100%); }}
    h1 {{ font-size: 58px; line-height: 1; margin: 0 0 18px; letter-spacing: 0; }}
    p {{ font-size: 18px; line-height: 1.6; color: #b7c5d3; max-width: 720px; }}
    code {{ color: #7dd3fc; background: #18212b; padding: 2px 6px; border-radius: 5px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin-top: 32px; }}
    .tile {{ border: 1px solid #2a3642; border-radius: 8px; padding: 18px; background: #151c24; }}
    .label {{ color: #91a4b7; font-size: 13px; text-transform: uppercase; }}
    .value {{ margin-top: 8px; font-size: 17px; }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>Needle</h1>
      <p>Harbor is serving Needle as an OpenAI-compatible tool-calling API. Use this endpoint with clients that send function definitions through the <code>tools</code> field.</p>
      <div class="grid">
        <div class="tile"><div class="label">Model</div><div class="value">{_model_id()}</div></div>
        <div class="tile"><div class="label">Status</div><div class="value">{status}</div></div>
        <div class="tile"><div class="label">API Base</div><div class="value"><code>/v1</code></div></div>
      </div>
    </section>
  </main>
</body>
</html>"""


@app.get("/health")
def health() -> dict[str, Any]:
    if _startup_error:
        raise HTTPException(status_code=503, detail=_startup_error)
    return {
        "status": "ok" if _model is not None else "loading",
        "model": _model_id(),
        "checkpoint": _checkpoint_path,
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": _model_id(),
                "object": "model",
                "created": 0,
                "owned_by": "cactus-compute",
            }
        ],
    }


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _last_user_query(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            text = _content_to_text(message.get("content"))
            if text.strip():
                return text.strip()
    raise ValueError("messages must include a user message with text content")


def _schema_type_name(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "string"
    if isinstance(schema.get("type"), str):
        return schema["type"]
    if isinstance(schema.get("enum"), list):
        return "string"
    return "string"


def _needle_parameters(parameters: Any) -> dict[str, str]:
    """Convert OpenAI JSON Schema parameters into Needle's compact schema.

    Upstream Needle examples use {"location": "string"} rather than full JSON
    Schema. Passing the full schema makes the model treat "properties" as an
    argument name, so normalize here while preserving direct compact schemas.
    """
    if not isinstance(parameters, dict):
        return {}

    properties = parameters.get("properties")
    if isinstance(properties, dict):
        return {
            str(name): _schema_type_name(schema)
            for name, schema in properties.items()
        }

    compact = {}
    for name, value in parameters.items():
        if name in {"type", "required", "additionalProperties", "$schema"}:
            continue
        compact[str(name)] = _schema_type_name(value)
    return compact


def _needle_tools(tools: Any) -> list[dict[str, Any]]:
    if tools in (None, ""):
        return []
    if not isinstance(tools, list):
        raise ValueError("tools must be an array")

    converted = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise ValueError(f"tools[{index}] must be an object")

        fn = tool.get("function") if tool.get("type") == "function" else tool
        if not isinstance(fn, dict):
            raise ValueError(f"tools[{index}].function must be an object")

        name = fn.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"tools[{index}] is missing function.name")

        converted.append(
            {
                "name": name,
                "description": fn.get("description", ""),
                "parameters": _needle_parameters(fn.get("parameters", {})),
            }
        )
    return converted


def _parse_tool_calls(result: str) -> list[dict[str, Any]]:
    text = result.strip()
    if not text:
        return []
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    calls = []
    for call in parsed:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        arguments = call.get("arguments", call.get("args", {}))
        if not isinstance(name, str) or not name:
            continue
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"value": arguments}
        calls.append(
            {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, separators=(",", ":")),
                },
            }
        )
    return calls


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _run_generation(body: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    if _model is None or _params is None or _tokenizer is None:
        _load_model()

    messages = body.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages must be an array")

    query = _last_user_query(messages)
    tools = _needle_tools(body.get("tools", []))
    max_gen_len = _env_int("NEEDLE_MAX_GEN_LEN", 512)
    if body.get("max_tokens") is not None:
        max_gen_len = _clamp_int(body.get("max_tokens"), max_gen_len)
    constrained = _env_bool("NEEDLE_CONSTRAINED", True)
    if isinstance(body.get("extra_body"), dict) and "constrained" in body["extra_body"]:
        constrained = bool(body["extra_body"]["constrained"])
    seed = int(body.get("seed", 0) or 0)

    from needle.model.run import generate

    with _lock:
        result = generate(
            _model,
            _params,
            _tokenizer,
            query,
            tools=json.dumps(tools, separators=(",", ":")),
            max_gen_len=max_gen_len,
            seed=seed,
            stream=False,
            constrained=constrained,
        )

    try:
        tool_calls = _parse_tool_calls(result)
    except json.JSONDecodeError:
        tool_calls = []
    return query, tool_calls, result


def _chat_response(body: dict[str, Any]) -> dict[str, Any]:
    query, tool_calls, raw_result = _run_generation(body)
    created = int(time.time())
    model = _model_id()

    message: dict[str, Any] = {"role": "assistant"}
    finish_reason = "stop"
    if tool_calls:
        message["content"] = None
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    else:
        message["content"] = raw_result

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": _estimate_tokens(query),
            "completion_tokens": _estimate_tokens(raw_result),
            "total_tokens": _estimate_tokens(query) + _estimate_tokens(raw_result),
        },
    }


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, separators=(',', ':'))}\n\n"


def _stream_response(body: dict[str, Any]):
    response = _chat_response(body)
    base = {
        "id": response["id"],
        "object": "chat.completion.chunk",
        "created": response["created"],
        "model": response["model"],
    }
    yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
    message = response["choices"][0]["message"]
    if message.get("tool_calls"):
        for index, call in enumerate(message["tool_calls"]):
            yield _sse(
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"tool_calls": [{**call, "index": index}]},
                            "finish_reason": None,
                        }
                    ],
                }
            )
    elif message.get("content"):
        yield _sse({**base, "choices": [{"index": 0, "delta": {"content": message["content"]}, "finish_reason": None}]})
    yield _sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": response["choices"][0]["finish_reason"]}]})
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(body: dict[str, Any]):
    try:
        if body.get("stream"):
            return StreamingResponse(_stream_response(body), media_type="text/event-stream")
        return _chat_response(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Needle generation failed: {exc}") from exc
