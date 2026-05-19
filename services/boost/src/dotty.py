import re
from typing import Any, List, Union

DottyPath = Union[str, List, tuple]


def is_int(value: Any) -> bool:
  """Check if the value is an integer or can be converted to an integer."""
  if isinstance(value, int):
    return True
  if isinstance(value, str):
    return value.isdigit() or (value.startswith('-') and value[1:].isdigit())
  return False


def parse_path(path: DottyPath) -> List:
  """Parse a path string or list/tuple into a list of path segments."""
  if isinstance(path, (list, tuple)):
    return list(path)

  if not path:
    return []

  if '[' in path:
    parts = re.findall(r'([^\.\[\]]+|\[\d+\]|\[[^\[\]]+\])', path)
    result = []
    for part in parts:
      if part.startswith('[') and part.endswith(']'):
        content = part[1:-1]
        if is_int(content):
          result.append(int(content))
        else:
          result.append(content)
      else:
        result.append(part)
    return result

  result = []
  for part in path.split('.'):
    if is_int(part):
      result.append(int(part))
    else:
      result.append(part)
  return result


def get(obj: Any, path: DottyPath, default: Any = None) -> Any:
  """
  Gets the value at path of object. If the resolved value is undefined,
  the default value is returned. Works with nested dictionaries, lists,
  class attributes, and properties.
  """
  if obj is None:
    return default

  parts = parse_path(path)

  try:
    result = obj
    for part in parts:
      if result is None:
        return default

      if isinstance(result, dict) and part in result:
        result = result[part]
      elif isinstance(result, (list, tuple)) and isinstance(
        part, int
      ) and -len(result) <= part < len(result):
        result = result[part]
      elif hasattr(result, part):
        result = getattr(result, part)
      else:
        try:
          result = result[part]
        except (KeyError, TypeError, IndexError):
          return default

    if result is None:
      return default

    return result
  except (KeyError, AttributeError, IndexError, TypeError):
    return default


def set(obj: Any, path: DottyPath, value: Any) -> Any:
  """
  Sets the value at path of object. If a portion of path doesn't exist,
  it's created. Works with nested dictionaries, lists, and class attributes.
  """
  if obj is None:
    obj = {}

  parts = parse_path(path)
  if not parts:
    return value

  root = obj
  for i, part in enumerate(parts[:-1]):
    last_part = i == len(parts) - 2
    next_part = parts[i + 1]

    if isinstance(root, dict):
      if part not in root:
        root[part] = [] if isinstance(next_part, int) else {}
      root = root[part]
    elif isinstance(root, list) and isinstance(part, int):
      while len(root) <= part:
        root.append(None)
      if root[part] is None:
        root[part] = [] if isinstance(next_part, int) else {}
      root = root[part]
    elif hasattr(root, part):
      current = getattr(root, part)
      if current is None and last_part:
        setattr(root, part, [] if isinstance(next_part, int) else {})
      root = getattr(root, part)
    else:
      try:
        setattr(root, part, [] if isinstance(next_part, int) else {})
        root = getattr(root, part)
      except (AttributeError, TypeError):
        try:
          root[part] = [] if isinstance(next_part, int) else {}
          root = root[part]
        except (TypeError, KeyError):
          return obj

  last_part = parts[-1]
  if isinstance(root, dict):
    root[last_part] = value
  elif isinstance(root, list) and isinstance(last_part, int):
    while len(root) <= last_part:
      root.append(None)
    root[last_part] = value
  elif hasattr(root, last_part):
    setattr(root, last_part, value)
  else:
    try:
      setattr(root, last_part, value)
    except (AttributeError, TypeError):
      try:
        root[last_part] = value
      except (TypeError, IndexError):
        pass

  return obj


def has(obj: Any, path: DottyPath) -> bool:
  """
  Checks if path is a direct property of object.
  Works with nested dictionaries, lists, and class attributes.
  """
  if obj is None:
    return False

  parts = parse_path(path)
  if not parts:
    return False

  try:
    result = obj
    for part in parts:
      if result is None:
        return False

      if isinstance(result, dict):
        if part not in result:
          return False
        result = result[part]
      elif isinstance(result, (list, tuple)):
        if not isinstance(part,
                          int) or part < -len(result) or part >= len(result):
          return False
        result = result[part]
      elif hasattr(result, part):
        result = getattr(result, part)
      else:
        try:
          result = result[part]
        except (KeyError, TypeError, IndexError):
          return False
    return True
  except (KeyError, AttributeError, IndexError, TypeError):
    return False
