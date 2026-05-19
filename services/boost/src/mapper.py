from asyncache import cached
from cachetools import TTLCache
from fastapi import HTTPException

import httpx

from typing import Dict

import config
import mods
import workflows
import log

logger = log.setup_logger(__name__)

MODEL_TO_BACKEND: Dict[str, str] = {}

@cached(TTLCache(1024, 60))
async def list_downstream():
  logger.debug("Listing downstream models")

  all_models = []

  for url, key in zip(
    config.BOOST_APIS,
    config.BOOST_KEYS,
  ):
    try:
      endpoint = f"{url}/models"
      headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
      }

      logger.debug(f"Fetching models from '{endpoint}'")

      async with httpx.AsyncClient() as client:
        response = await client.get(endpoint, headers=headers)
        response.raise_for_status()
        json = response.json()
        models = json.get("data", [])

        logger.debug(f"Found {len(models)} models at '{endpoint}'")
        all_models.extend(models)

        for model in models:
          MODEL_TO_BACKEND[model["id"]] = url

    except Exception as e:
      logger.error(f"Failed to fetch models from {endpoint}: {e}")

  # Register static models for providers without /models endpoint
  for model in config.MINIMAX_MODELS:
    if model["id"] not in MODEL_TO_BACKEND:
      MODEL_TO_BACKEND[model["id"]] = config.MINIMAX_BASE_URL
      all_models.append(model)
      logger.debug(f"Registered static model: {model['id']}")

  return all_models


def get_proxy_model(module, model: dict) -> Dict:
  return {
    **model,
    "id": f"{module.ID_PREFIX}-{model['id']}",
    "name": f"{module.ID_PREFIX} {model['id']}",
  }


def workflow_models(models: list[dict]) -> list[dict]:
  return workflows.workflow_models(models)


def resolve_proxy_model(model_id: str) -> Dict:
  prefix, sep, rest = model_id.partition("-")
  if sep and prefix in mods.registry:
    return rest

  workflow, base_model = workflows.split_workflow_model(model_id)
  if workflow is not None:
    return base_model

  return model_id


def resolve_proxy_module(model_id: str) -> Dict:
  prefix, sep, _ = model_id.partition("-")
  if sep and prefix in mods.registry:
    return prefix
  return None


def resolve_proxy_workflow(model_id: str) -> Dict:
  if resolve_proxy_module(model_id):
    return None

  workflow, _ = workflows.split_workflow_model(model_id)
  return workflow


def resolve_request_config(body: Dict) -> Dict:
  model = body.get("model")
  messages = body.get("messages")
  params = {k: v for k, v in body.items() if k not in ["model", "messages"]}

  if not model:
    raise ValueError("Unable to proxy request without a model specifier")

  proxy_model = resolve_proxy_model(model)
  proxy_module = resolve_proxy_module(model)
  proxy_workflow = resolve_proxy_workflow(model)
  proxy_backend = MODEL_TO_BACKEND.get(proxy_model)

  logger.debug(
    f"Resolved proxy model: {proxy_model}, proxy module: {proxy_module}, proxy workflow: {proxy_workflow}, proxy backend: {proxy_backend}"
  )

  if not proxy_backend:
    raise HTTPException(
      status_code=404,
      detail=f"Unknown model: '{model}'",
    )

  proxy_key = config.BOOST_KEYS[
    config.BOOST_APIS.index(proxy_backend)]

  proxy_config = {
    "url": proxy_backend,
    "headers":
      {
        "Authorization": f"Bearer {proxy_key}",
        "Content-Type": "application/json",
      },
    "model": proxy_model,
    "params": params,
    "messages": messages,
    "module": proxy_module,
    "workflow": proxy_workflow,
  }

  return proxy_config

def is_title_generation_task(llm: 'LLM'):
  # TODO: Better way to identify?
  return llm.chat.has_substring("3-5 word title")

DIRECT_TASK_PROMPTS = [
    # Open WebUI prompts related to system tasks
  'Generate a concise, 3-5 word title',
  'Based on the chat history, determine whether a search is necessary',
  'Generate 1-3 broad tags categorizing',
  'You are an autocompletion system. Continue the text in `<text>` based on the **completion type**',
  'determine the necessity of generating search queries',
  # Custom for the test
  '[{DIRECT}]'
]

def is_direct_task(llm: 'LLM'):
  return any(llm.chat.has_substring(prompt) for prompt in DIRECT_TASK_PROMPTS)
