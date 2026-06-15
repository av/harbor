from contextvars import ContextVar
from fastapi import Request

request = ContextVar[Request](
  'request',
  default=None,
)


def request_store(name: str, default):
  """Get or initialize a named attribute on the current request.state."""
  current = request.get()
  if current is None:
    return default

  if not hasattr(current.state, name):
    setattr(current.state, name, default)

  return getattr(current.state, name)


def request_set(name: str, value) -> bool:
  """Overwrite a named attribute on the current request.state."""
  current = request.get()
  if current is None:
    return False

  setattr(current.state, name, value)
  return True
