from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
import asyncio
from datetime import datetime

app = FastAPI()

TARGET_URL = "http://nexa:8000"

@app.api_route("/health", methods=["GET"])
def health():
  return JSONResponse(content={"status": "ok"})


@app.api_route("/v1/models", methods=["GET"])
def get_models():
  return JSONResponse(
    content={
      "object": "list",
      "data":
        [{
          "id": "nexa",
          "created": int(datetime.now().timestamp()),
          "object": "model",
          "owned_by": "nexa"
        }]
    }
  )


@app.api_route(
  "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
)
async def proxy(request: Request, path: str):
  client = httpx.AsyncClient()

  # Construct the target URL
  url = f"{TARGET_URL}/{path}"

  # Forward the request headers
  headers = dict(request.headers)
  headers.pop("host", None)

  try:
    # Stream the request body
    async def request_stream():
      async for chunk in request.stream():
        yield chunk

    # Make the request to the target server
    response = await client.request(
      method=request.method,
      url=url,
      headers=headers,
      params=request.query_params,
      content=request_stream(),
      timeout=httpx.Timeout(300.0)
    )

    # Stream the response back to the client
    async def response_stream():
      try:
          async for chunk in response.aiter_bytes():
              yield chunk
      except (RequestError, ReadTimeout, ConnectTimeout) as e:
          logger.error(f"Error during streaming: {str(e)}")
          # Handle the error appropriately

    return StreamingResponse(
      response_stream(),
      status_code=response.status_code,
      headers=dict(response.headers)
    )

  except httpx.RequestError as exc:
    raise HTTPException(
      status_code=500,
      detail=f"Error communicating with target server: {str(exc)}"
    )

  finally:
    await client.aclose()


if __name__ == "__main__":
  import uvicorn
  uvicorn.run(app, host="0.0.0.0", port=8000)
