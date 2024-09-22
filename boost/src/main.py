from typing import List, Dict, Any
import httpx
import json

from pydantic import BaseModel
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import HARBOR_BOOST_OPENAI_URLS, HARBOR_BOOST_OPENAI_KEYS
from log import setup_logger

import mapper
import config
import llm

logger = setup_logger(__name__)
app = FastAPI()

# ------------------------------


class ChatMessage(BaseModel):
  role: str
  content: str


class ChatCompletionRequest(BaseModel):
  model: str
  messages: List[ChatMessage]
  temperature: float = 1.0
  top_p: float = 1.0
  n: int = 1
  stream: bool = False
  stop: List[str] = []
  max_tokens: int = None
  presence_penalty: float = 0
  frequency_penalty: float = 0
  logit_bias: Dict[str, float] = {}
  user: str = ""


# ------------------------------

@app.get("/")
async def root():
  return JSONResponse(content={"status": "ok", "message": "Harbor Boost is running"}, status_code=200)


@app.get("/health")
async def health():
  return JSONResponse(content={"status": "ok"}, status_code=200)


@app.get("/v1/models")
async def get_boost_models():
  downstream = await mapper.list_downstream()
  enabled_modules = config.HARBOR_BOOST_MODULES.value

  proxy_models = []

  for model in downstream:
    proxy_models.append(model)
    for module in enabled_modules:
      mod = llm.mods.get(module)
      proxy_models.append(mapper.get_proxy_model(mod, model))

  return JSONResponse(content=proxy_models, status_code=200)


async def fetch_stream(url: str, headers: dict, json_data: dict):
  async with httpx.AsyncClient() as client:
    async with client.stream(
      "POST", url, headers=headers, json=json_data
    ) as response:
      async for chunk in response.aiter_bytes():
        yield chunk


@app.post("/v1/chat/completions")
async def post_boost_chat_completion(request: Request):
  body = await request.body()

  try:
    decoded = body.decode("utf-8")
    json_body = json.loads(decoded)
    stream = json_body.get("stream", False)
  except json.JSONDecodeError:
    logger.debug(f"Invalid JSON in request body: {body[:100]}")
    raise HTTPException(status_code=400, detail="Invalid JSON in request body")

  await mapper.list_downstream()

  proxy_config = mapper.resolve_request_config(json_body)
  proxy_llm = llm.LLM(**proxy_config)

  # This is where the boost happens
  completion = await proxy_llm.apply()

  logger.debug('Completion: %s', completion)

  if stream:
    return StreamingResponse(
      completion,
      media_type="text/event-stream"
    )
  else:
    content = await proxy_llm.consume_stream(completion)
    return JSONResponse(
      content=content,
      status_code=200
    )


logger.info(f"Boosting: {config.HARBOR_BOOST_EXTRA_OPENAI_URLS.value}")

if __name__ == "__main__":

  import uvicorn
  uvicorn.run(app, host="0.0.0.0", port=8000)
