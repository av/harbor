import httpx
import json

from fastapi import FastAPI, Request, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import JSONResponse, StreamingResponse

from config import MODEL_FILTER, SERVE_BASE_MODELS, BOOST_AUTH
from log import setup_logger

import selection
import mapper
import config
import mods
import llm

logger = setup_logger(__name__)
app = FastAPI()
auth_header = APIKeyHeader(name="Authorization", auto_error=False)

# ------------------------------
async def get_api_key(api_key_header: str = Security(auth_header)):
  if len(BOOST_AUTH) == 0:
    return

  if api_key_header is not None:
    # Bearer/plain versions
    value = api_key_header.replace("Bearer ", "").replace("bearer ", "")
    if value in BOOST_AUTH:
      return value

  raise HTTPException(status_code=403, detail="Unauthorized")


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


@app.get("/v1/models")
async def get_boost_models(api_key: str = Depends(get_api_key)):
  downstream = await mapper.list_downstream()
  enabled_modules = config.BOOST_MODS.value
  should_filter = len(MODEL_FILTER.value) > 0
  serve_base_models = SERVE_BASE_MODELS.value
  candidates = []
  final = []

  for model in downstream:
    if serve_base_models:
      candidates.append(model)

    for module in enabled_modules:
      mod = mods.registry.get(module)
      candidates.append(mapper.get_proxy_model(mod, model))

  for model in candidates:
    should_serve = True

    if should_filter:
      should_serve = selection.matches_filter(model, MODEL_FILTER.value)
      print(model['id'], MODEL_FILTER.value['id.regex'], should_serve)

    if should_serve:
      final.append(model)

  logger.debug(f"Serving {len(final)} models in the API")

  return JSONResponse(content=final, status_code=200)


@app.post("/v1/chat/completions")
async def post_boost_chat_completion(request: Request, api_key: str = Depends(get_api_key)):
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

  # We don't want to trigger potentially
  # expensive workflows for title generation
  if mapper.is_title_generation_task(proxy):
    logger.debug("Detected title generation task, skipping boost")
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

# ------------ Startup ----------------

logger.info(f"Boosting: {config.BOOST_APIS}")
if len(BOOST_AUTH) == 0:
  logger.warn("No API keys specified - boost will accept all requests")

if __name__ == "__main__":
  import uvicorn
  uvicorn.run(app, host="0.0.0.0", port=8000)
