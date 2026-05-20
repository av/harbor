from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

import config
import log

logger = log.setup_logger(__name__)

auth_header = APIKeyHeader(name="Authorization", auto_error=False)
x_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


async def get_api_key(
  api_key_header: str = Security(auth_header),
  x_api_key: str = Security(x_api_key_header),
):
  if len(config.BOOST_AUTH) == 0:
    return

  # Try Authorization header first (standard OpenAI-style)
  candidate = None
  source = None
  if api_key_header is not None:
    # Case-insensitive stripping of the "Bearer " scheme prefix
    raw = api_key_header
    if raw[:7].lower() == "bearer ":
      raw = raw[7:]
    candidate = raw
    source = "Authorization"

  # Fall back to x-api-key header (standard Anthropic-style)
  if not candidate and x_api_key is not None:
    candidate = x_api_key
    source = "x-api-key"

  if candidate and candidate in config.BOOST_AUTH:
    logger.debug("Auth succeeded via %s header", source)
    return candidate

  if candidate:
    logger.warning("Auth failed: invalid key via %s header", source)
  else:
    logger.warning("Auth failed: no API key provided")
  raise HTTPException(status_code=401, detail="Unauthorized")
