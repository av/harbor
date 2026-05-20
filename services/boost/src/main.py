import json
import asyncio

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from middleware.request_id import RequestIDMiddleware
from middleware.request_state import RequestStateMiddleware

from config import MODEL_FILTER, SERVE_BASE_MODELS
from auth import get_api_key
from compat_utils import (
    ANTHROPIC_VERSION,
    ANTHROPIC_VERSION_HEADER,
)
from log import setup_logger

import selection
import mapper
import config
import mods
import llm
from llm_registry import llm_registry

logger = setup_logger(__name__)
app = FastAPI()

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],    # Allows all origins
  allow_credentials=True,
  allow_methods=["*"],    # Allows all methods
  allow_headers=["*"],    # Allows all headers
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RequestStateMiddleware)


# Format HTTPExceptions raised by dependencies (e.g. auth) to match the
# error schema each SDK expects.  Without this handler, FastAPI returns
# ``{"detail": "..."}`` which no SDK can parse into a typed error.

_ANTHROPIC_ERROR_TYPE_MAP = {
  400: "invalid_request_error",
  401: "authentication_error",
  403: "permission_error",
  404: "not_found_error",
  429: "rate_limit_error",
  500: "api_error",
  529: "overloaded_error",
}

_OPENAI_ERROR_TYPE_MAP = {
  400: "invalid_request_error",
  401: "authentication_error",
  403: "permission_error",
  404: "not_found_error",
  409: "conflict_error",
  422: "invalid_request_error",
  429: "rate_limit_error",
  500: "server_error",
}


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
  path = request.url.path

  if path.startswith("/v1/messages"):
    error_type = _ANTHROPIC_ERROR_TYPE_MAP.get(exc.status_code, "api_error")
    return JSONResponse(
      status_code=exc.status_code,
      content={
        "type": "error",
        "error": {"type": error_type, "message": str(exc.detail)},
      },
      headers={ANTHROPIC_VERSION_HEADER: ANTHROPIC_VERSION},
    )

  if path.startswith("/v1/responses"):
    error_type = _OPENAI_ERROR_TYPE_MAP.get(exc.status_code, "server_error")
    return JSONResponse(
      status_code=exc.status_code,
      content={
        "error": {
          "message": str(exc.detail),
          "type": error_type,
          "param": None,
          "code": None,
        },
      },
    )

  # Anthropic SDK hitting /v1/models with bad auth — detect via headers
  if _is_anthropic_client(request):
    error_type = _ANTHROPIC_ERROR_TYPE_MAP.get(exc.status_code, "api_error")
    return JSONResponse(
      status_code=exc.status_code,
      content={
        "type": "error",
        "error": {"type": error_type, "message": str(exc.detail)},
      },
      headers={ANTHROPIC_VERSION_HEADER: ANTHROPIC_VERSION},
    )

  # Default FastAPI behavior for other paths
  return JSONResponse(
    status_code=exc.status_code,
    content={"detail": exc.detail},
  )


@app.get("/")
async def root():
  return JSONResponse(
    content={
      "status": "ok",
      "message": "Harbor Boost is running"
    },
    status_code=200
  )


@app.get("/health")
async def health():
  return JSONResponse(content={"status": "ok"}, status_code=200)


@app.get("/events/{stream_id}")
async def get_event(stream_id: str, api_key: str = Depends(get_api_key)):
  llm = llm_registry.get(stream_id)

  if llm is None:
    raise HTTPException(status_code=404, detail="Event not found")

  return StreamingResponse(llm.listen(), status_code=200)


@app.websocket("/events/{stream_id}/ws")
async def websocket_event(stream_id: str, websocket: WebSocket):
  llm = llm_registry.get(stream_id)

  if llm is None:
    await websocket.close(code=404, reason="Event not found")
    return

  await websocket.accept()

  async def sender():
    async for chunk in llm.listen():
      await websocket.send_json(llm.parse_chunk(chunk))
    await websocket.close()

  async def receiver():
    while True:
      try:
        data = await websocket.receive_json()
        await llm.emit('websocket.message', data)

      except WebSocketDisconnect:
        break

  sender_task = asyncio.create_task(sender())
  receiver_task = asyncio.create_task(receiver())

  done, pending = await asyncio.wait(
    {sender_task, receiver_task},
    return_when=asyncio.FIRST_COMPLETED,
  )

  for task in pending:
    task.cancel()


# --- OpenAI Compatible ---------------------


def _is_anthropic_client(request: Request) -> bool:
  """Detect whether the request originates from an Anthropic SDK client.

  The Anthropic SDK sends ``anthropic-version`` on every request.
  ``x-api-key`` without ``Authorization`` is a weaker signal but still
  indicates an Anthropic-style caller.
  """
  if request.headers.get("anthropic-version"):
    return True
  if request.headers.get("x-api-key") and not request.headers.get("authorization"):
    return True
  return False


def _to_anthropic_model(model: dict) -> dict:
  """Convert an OpenAI-format model dict to Anthropic ModelInfo format."""
  return {
    "id": model.get("id", ""),
    "type": "model",
    "display_name": model.get("name") or model.get("id", ""),
    "created_at": "1970-01-01T00:00:00Z",
  }


async def _list_models():
  """Resolve the full list of serveable models (shared by both formats)."""
  downstream = await mapper.list_downstream()
  enabled_modules = mods.registry.keys() if config.BOOST_MODS.value == [
    'all'
  ] else config.BOOST_MODS.value
  should_filter = len(MODEL_FILTER.value) > 0
  serve_base_models = SERVE_BASE_MODELS.value
  candidates = []
  final = []

  for model in downstream:
    if serve_base_models:
      candidates.append(model)

    for module in enabled_modules:
      mod = mods.registry.get(module)
      if mod is not None:
        candidates.append(mapper.get_proxy_model(mod, model))

    candidates.extend(mapper.workflow_models([model]))

  for model in candidates:
    should_serve = True

    if should_filter:
      should_serve = selection.matches_filter(model, MODEL_FILTER.value)

    if should_serve:
      final.append(model)

  logger.debug(f"Serving {len(final)} models in the API")
  return final


def _anthropic_model_headers():
  """Standard headers for Anthropic-format model responses."""
  return {ANTHROPIC_VERSION_HEADER: ANTHROPIC_VERSION}


@app.get("/v1/models/{model_id:path}")
async def get_boost_model_by_id(
  model_id: str, request: Request, api_key: str = Depends(get_api_key)
):
  try:
    models = await _list_models()
  except Exception as e:
    logger.error(f"Failed to list models: {e}", exc_info=True)
    if _is_anthropic_client(request):
      return JSONResponse(
        status_code=500,
        content={
          "type": "error",
          "error": {"type": "api_error", "message": "Failed to list models"},
        },
        headers=_anthropic_model_headers(),
      )
    raise HTTPException(status_code=500, detail="Failed to list models")

  match = next((m for m in models if m.get("id") == model_id), None)

  if match is None:
    if _is_anthropic_client(request):
      return JSONResponse(
        status_code=404,
        content={
          "type": "error",
          "error": {
            "type": "not_found_error",
            "message": f"Model not found: {model_id}",
          },
        },
        headers=_anthropic_model_headers(),
      )
    raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

  if _is_anthropic_client(request):
    return JSONResponse(
      content=_to_anthropic_model(match),
      status_code=200,
      headers=_anthropic_model_headers(),
    )

  return JSONResponse(content=match, status_code=200)


@app.get("/v1/models")
async def get_boost_models(request: Request, api_key: str = Depends(get_api_key)):
  try:
    final = await _list_models()
  except Exception as e:
    logger.error(f"Failed to list models: {e}", exc_info=True)
    if _is_anthropic_client(request):
      return JSONResponse(
        status_code=500,
        content={
          "type": "error",
          "error": {"type": "api_error", "message": "Failed to list models"},
        },
        headers=_anthropic_model_headers(),
      )
    raise HTTPException(status_code=500, detail="Failed to list models")

  if _is_anthropic_client(request):
    anthropic_data = [_to_anthropic_model(m) for m in final]
    first_id = anthropic_data[0]["id"] if anthropic_data else None
    last_id = anthropic_data[-1]["id"] if anthropic_data else None
    return JSONResponse(
      content={
        'data': anthropic_data,
        'has_more': False,
        'first_id': first_id,
        'last_id': last_id,
      },
      status_code=200,
      headers=_anthropic_model_headers(),
    )

  return JSONResponse(
    content={
      'object': 'list',
      'data': final,
    }, status_code=200
  )


@app.post("/v1/chat/completions")
async def post_boost_chat_completion(
  request: Request, api_key: str = Depends(get_api_key)
):
  body = await request.body()

  logger.debug(f"Request body: {body[:256]}...")

  try:
    decoded = body.decode("utf-8")
    json_body = json.loads(decoded)
    stream = json_body.get("stream", False)
  except json.JSONDecodeError:
    logger.debug(f"Invalid JSON in request body: {body[:100]}")
    raise HTTPException(status_code=400, detail="Invalid JSON in request body")

  # Refresh downstream models to ensure
  # that we know where to route the requests
  await mapper.list_downstream()

  # Get our proxy model configuration
  proxy_config = mapper.resolve_request_config(json_body)
  proxy = llm.LLM(**proxy_config)

  # WebUI will send a few additional workflows
  # that we simply want to delegate to the underlying model as is, without boosting
  if (
    mapper.is_direct_task(proxy)
    and proxy.workflow is None
    and proxy.boost_params.get("workflow") is None
  ):
    logger.debug("Detected direct task, skipping boost")
    return JSONResponse(content=await proxy.chat_completion(), status_code=200)

  # This is where the "boost" happens
  completion = await proxy.serve()

  if completion is None:
    return JSONResponse(
      content={"error": "No completion returned"}, status_code=500
    )

  if stream:
    return StreamingResponse(completion, media_type="text/event-stream")
  else:
    content = await proxy.consume_stream(completion)
    return JSONResponse(content=content, status_code=200)


# --- OpenAI Responses API Compatible ---------

if config.ENABLE_RESPONSES_API.value:
  from responses_compat import responses_compatible_routes
  app.include_router(responses_compatible_routes)
  logger.info("OpenAI Responses API enabled at /v1/responses")


# --- Anthropic Compatible ------------------

if config.ENABLE_ANTHROPIC_COMPAT.value:
  from anthropic_compat import anthropic_compatible_routes
  app.include_router(anthropic_compatible_routes)
  logger.info("Anthropic-compatible Messages API enabled at /v1/messages")


# ------------ Startup ----------------

logger.info(f"Boosting: {config.BOOST_APIS}")
if len(config.BOOST_AUTH) == 0:
  logger.warning("No API keys specified - boost will accept all requests")

if __name__ == "__main__":
  import uvicorn
  uvicorn.run(
    app,
    host="0.0.0.0",
    port=8000,
    timeout_graceful_shutdown=5,
    timeout_keep_alive=5,
    reload_delay=0.0
  )
