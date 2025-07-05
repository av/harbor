"""
This module is responsible for loading all the modules
from the configured folders and registering them in
the registry.
"""

import os
import importlib

from config import BOOST_FOLDERS

# To avoid circular imports
import selection
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

if __name__ == "__main__":
  # Render module docs to the stdout
  docs = """
# Harbor Boost Modules

Documentation for built-in modules in Harbor Boost.
"""

  for module_name, module in sorted(registry.items()):
    docs += f"\n## {module_name}\n\n"
    mod_doc = module.DOCS if hasattr(
      module, "DOCS"
    ) else module.apply.__doc__ if module.apply.__doc__ else "No documentation available."
    docs += f"{mod_doc.strip()}\n\n"

  print(docs)
