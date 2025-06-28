from fastapi import Request
from contextvars import ContextVar
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIDMiddleware(BaseHTTPMiddleware):

  async def dispatch(self, request: Request, call_next):
    default_request_id = str(uuid.uuid4())[:8]
    request_id = request.headers.get("X-Request-ID", default_request_id)
    request_id_var.set(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    return response
