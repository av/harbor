"""
This module is responsible for loading all the modules
from the configured folders and registering them in
the registry.
"""

import os
import importlib

from config import INTERMEDIATE_OUTPUT, BOOST_FOLDERS

import log

logger = log.setup_logger(__name__)

registry = {}


def load_folder(folder):
  logger.debug(f"Loading modules from '{folder}'")
  for filename in os.listdir(folder):
    is_target_mod = filename.endswith(".py") and filename != "__init__.py"

    if is_target_mod:
      module_name = filename[:-3]
      module = importlib.import_module(f"{folder}.{module_name}")

      if hasattr(module, "ID_PREFIX"):
        logger.debug(f"Registering '{module.ID_PREFIX}'...")
        registry[module_name] = module


for folder in BOOST_FOLDERS.value:
  load_folder(folder)

if len(registry) == 0:
  logger.warning("No modules loaded. Is boost configured correctly?")
else:
  logger.info(f"Loaded {len(registry)} modules: {', '.join(registry.keys())}")
