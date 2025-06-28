from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from state import request as request_state

class RequestStateMiddleware(BaseHTTPMiddleware):
  """
  Tracks current request in the context state.
  """

  async def dispatch(self, request: Request, call_next):
    request_state.set(request)
    response = await call_next(request)
    request_state.set(None)
    return response