from contextvars import ContextVar
from fastapi import Request

request = ContextVar[Request](
  'request',
  default=None,
)
