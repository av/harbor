import inspect
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import config
import log
import mods
import yaml

logger = log.setup_logger(__name__)

WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_WORKFLOW_FILES = [
  "/boost/workflows.yaml",
  "/boost/workflows.yml",
  "/boost/workflows.json",
]


def _as_list(value: Any) -> list:
  if value is None:
    return []
  if isinstance(value, list):
    return value
  return [value]


def _parse_json_or_shorthand(raw: str) -> Any:
  raw = (raw or "").strip()
  if not raw:
    return []

  if raw[0] in "[{":
    return json.loads(raw)

  workflows = {}
  for item in raw.split(";"):
    if not item.strip():
      continue
    workflow_id, sep, modules = item.partition("=")
    if not sep:
      raise ValueError(f"Invalid workflow shorthand item: {item}")
    workflows[workflow_id.strip()] = {
      "modules": [module.strip() for module in modules.split(",") if module.strip()]
    }

  return workflows


def _workflow_file_candidates() -> list[str]:
  path = config.WORKFLOWS_FILE.value
  if not path:
    return []

  if path in DEFAULT_WORKFLOW_FILES:
    return [path, *[candidate for candidate in DEFAULT_WORKFLOW_FILES if candidate != path]]

  return [path]


def _parse_workflow_file(path: str) -> Any:
  content = Path(path).read_text(encoding="utf-8")
  if not content.strip():
    return []

  suffix = Path(path).suffix.lower()
  if suffix in {".yaml", ".yml"}:
    return yaml.safe_load(content) or []

  if suffix == ".json":
    return json.loads(content)

  try:
    return json.loads(content)
  except json.JSONDecodeError:
    return yaml.safe_load(content) or []


def _load_file_definitions() -> Any:
  for path in _workflow_file_candidates():
    if os.path.exists(path):
      return _parse_workflow_file(path)

  return []


def _unwrap_definitions(raw: Any) -> Any:
  if not isinstance(raw, dict):
    return raw

  if "id" in raw or "modules" in raw:
    return raw

  for key in ("workflows", "agents"):
    definitions = raw.get(key)
    if isinstance(definitions, (dict, list)):
      return definitions

  return raw


def _definition_items(raw: Any):
  raw = _unwrap_definitions(raw)

  if isinstance(raw, dict):
    for workflow_id, definition in raw.items():
      if isinstance(definition, list):
        definition = {"modules": definition}
      elif isinstance(definition, str):
        definition = {"modules": [m.strip() for m in definition.split(",") if m.strip()]}
      elif definition is None:
        definition = {"modules": []}
      elif not isinstance(definition, dict):
        logger.warning(f"Skipping invalid workflow definition for {workflow_id}")
        continue

      yield {"id": workflow_id, **definition}
    return

  for definition in _as_list(raw):
    if isinstance(definition, str):
      workflow_id, sep, modules = definition.partition("=")
      if not sep:
        logger.warning(f"Skipping invalid workflow shorthand: {definition}")
        continue
      yield {
        "id": workflow_id.strip(),
        "modules": [module.strip() for module in modules.split(",") if module.strip()],
      }
    elif isinstance(definition, dict):
      yield definition
    else:
      logger.warning(f"Skipping invalid workflow definition: {definition}")


def normalize_workflow(definition: Any, default_id: str | None = None) -> dict | None:
  if isinstance(definition, str):
    if definition.strip().startswith(("{", "[")):
      definition = _parse_json_or_shorthand(definition)
      if isinstance(definition, dict) and "modules" not in definition and "id" not in definition:
        first_item = next(_definition_items(definition), None)
        return normalize_workflow(first_item, default_id=default_id)
    else:
      workflow_id, sep, modules = definition.partition("=")
      if not sep:
        logger.warning(f"Skipping invalid workflow shorthand: {definition}")
        return None
      definition = {
        "id": workflow_id.strip(),
        "modules": [module.strip() for module in modules.split(",") if module.strip()],
      }

  if isinstance(definition, list):
    definition = {"modules": definition}

  if not isinstance(definition, dict):
    logger.warning(f"Skipping invalid workflow definition: {definition}")
    return None

  workflow_id = definition.get("id") or definition.get("handle") or default_id
  if not workflow_id or not isinstance(workflow_id, str):
    logger.warning(f"Skipping workflow without id: {definition}")
    return None

  if not WORKFLOW_ID_RE.match(workflow_id):
    logger.warning(
      f"Skipping workflow '{workflow_id}': IDs may contain letters, numbers, underscores, dots, and dashes only"
    )
    return None

  modules = definition.get("modules", [])
  if isinstance(modules, str):
    modules = [module.strip() for module in modules.split(",") if module.strip()]

  return {
    "id": workflow_id,
    "name": definition.get("name") or workflow_id,
    "description": definition.get("description", ""),
    "modules": _as_list(modules),
  }


def load_workflows() -> dict[str, dict]:
  loaded = {}

  sources = []
  try:
    sources.append(_load_file_definitions())
  except Exception as e:
    logger.warning(f"Failed to load workflows file: {e}")

  try:
    sources.append(_parse_json_or_shorthand(config.WORKFLOWS.value))
  except Exception as e:
    logger.warning(f"Failed to parse HARBOR_BOOST_WORKFLOWS: {e}")

  for source in sources:
    for definition in _definition_items(source):
      workflow = normalize_workflow(definition)
      if workflow is None:
        continue
      if workflow["id"] in mods.registry:
        logger.warning(
          f"Workflow '{workflow['id']}' collides with a module prefix and will not be reachable as a model prefix"
        )
      loaded[workflow["id"]] = workflow

  return loaded


_registry_cache: dict[str, dict] | None = None


def registry() -> dict[str, dict]:
  global _registry_cache
  if _registry_cache is None:
    _registry_cache = load_workflows()
  return _registry_cache


def invalidate_registry():
  global _registry_cache
  _registry_cache = None


def get(workflow_id: str) -> dict | None:
  return registry().get(workflow_id)


def split_workflow_model(model_id: str) -> tuple[dict | None, str]:
  for workflow_id, workflow in sorted(registry().items(), key=lambda item: len(item[0]), reverse=True):
    prefix = f"{workflow_id}-"
    if model_id.startswith(prefix):
      return workflow, model_id[len(prefix):]

  return None, model_id


def model_for(workflow: dict, base_model: dict) -> dict:
  return {
    **base_model,
    "id": f"{workflow['id']}-{base_model['id']}",
    "name": f"{workflow.get('name') or workflow['id']} {base_model['id']}",
    "owned_by": "harbor-boost-workflow",
    "boost_workflow": {
      "id": workflow["id"],
      "name": workflow.get("name"),
      "description": workflow.get("description", ""),
    },
  }


def workflow_models(base_models: list[dict]) -> list[dict]:
  return [
    model_for(workflow, base_model)
    for workflow in registry().values()
    for base_model in base_models
  ]


def _module_name(module_config: Any) -> str | None:
  if isinstance(module_config, str):
    return module_config
  if isinstance(module_config, dict):
    return module_config.get("module") or module_config.get("handle")
  return None


def _module_config(module_config: Any) -> dict:
  if not isinstance(module_config, dict):
    return {}
  value = module_config.get("config", module_config.get("values", {}))
  return deepcopy(value) if isinstance(value, dict) else {}


def _placement_config(module_config: Any, module_name: str, module_cfg: dict) -> dict:
  if module_name == "system" and isinstance(module_config, str):
    return {"placement": "system", "prompt": ""}

  if isinstance(module_config, dict) and "prompt" in module_config and "prompt" not in module_cfg:
    module_cfg["prompt"] = module_config["prompt"]
  return module_cfg


async def _apply_system(chat, module_cfg: dict):
  prompt = module_cfg.get("prompt", "")
  if not prompt:
    return

  placement = module_cfg.get("placement", "system")
  if placement == "user":
    chat.user(prompt)
  elif placement == "assistant":
    chat.assistant(prompt)
  else:
    chat.system(prompt)


async def _apply_module(module_name: str, module_cfg: dict, chat, llm):
  mod = mods.registry.get(module_name)
  if mod is None:
    raise ValueError(f"Workflow module '{module_name}' not found")

  signature = inspect.signature(mod.apply)
  kwargs = {"chat": chat, "llm": llm}
  if "config" in signature.parameters:
    kwargs["config"] = module_cfg

  await mod.apply(**kwargs)


async def apply_workflow(workflow_definition: Any, chat, llm):
  workflow = normalize_workflow(workflow_definition, default_id="request")
  if workflow is None:
    raise ValueError("Invalid workflow definition")

  modules = workflow.get("modules", [])
  if not modules:
    await llm.stream_final_completion()
    return

  final_streamed = False

  for index, module_config in enumerate(modules):
    module_name = _module_name(module_config)
    if not module_name:
      logger.warning(f"Skipping workflow item without module: {module_config}")
      continue

    module_cfg = _placement_config(module_config, module_name, _module_config(module_config))
    is_last = index == len(modules) - 1

    if module_name in {"system", "add-system"}:
      await _apply_system(chat, module_cfg)
      continue

    if module_name in {"final", "completion", "chat-completion"}:
      await llm.stream_final_completion()
      final_streamed = True
      break

    if module_name == "tools" and "final" not in module_cfg and not is_last:
      module_cfg["final"] = False

    was_final = llm.is_final_stream
    await _apply_module(module_name, module_cfg, chat, llm)

    if llm.is_final_stream and not was_final:
      final_streamed = True
      if not (isinstance(module_config, dict) and module_config.get("continue")):
        break

  if not final_streamed:
    await llm.stream_final_completion()
