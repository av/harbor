FROM ghcr.io/av/tools

WORKDIR /boost
COPY pyproject.toml uv.lock /boost
RUN uv sync --frozen

COPY /src /boost

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--timeout-graceful-shutdown", "0"]
