import httpx
import json

from fastapi import FastAPI, Request, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import JSONResponse, StreamingResponse

from config import AGENT_AUTH
from log import setup_logger

from llm import LLM
from agent import Agent
from tasks.direct import is_direct_task

logger = setup_logger(__name__)
app = FastAPI()
auth_header = APIKeyHeader(name="Authorization", auto_error=False)

# ------------------------------

async def get_api_key(api_key_header: str = Security(auth_header)):
  if len(AGENT_AUTH) == 0:
    return

  if api_key_header is not None:
    # Bearer/plain versions
    value = api_key_header.replace("Bearer ", "").replace("bearer ", "")
    if value in AGENT_AUTH:
      return value

  raise HTTPException(status_code=403, detail="Unauthorized")

@app.get("/")
async def root():
  return JSONResponse(
    content={
      "status": "ok",
      "message": "Harbor Agent is running"
    },
    status_code=200
  )

@app.get("/health")
async def health():
  return JSONResponse(content={"status": "ok"}, status_code=200)

@app.get("/v1/models")
async def get_agent_models(api_key: str = Depends(get_api_key)):
  final = [{
    "id": "harbor-agent",
    # Open WebUI supports this
    "name": "Harbor Agent",
  }]

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

  # Get our proxy model configuration
  proxy = LLM.from_config(**json_body)
  agent = Agent(llm=proxy)

  # We don't want to trigger potentially
  # expensive workflows for title generation
  if is_direct_task(proxy.chat):
    logger.debug("Detected title generation task, skipping boost")
    return JSONResponse(content=await proxy.chat_completion(), status_code=200)

  completion = await agent.serve()

  if completion is None:
    return JSONResponse(
      content={"error": "No completion returned"}, status_code=500
    )

  if stream:
    return StreamingResponse(completion, media_type="text/event-stream")
  else:
    content = await proxy.consume_stream(completion)
    return JSONResponse(content=content, status_code=200)