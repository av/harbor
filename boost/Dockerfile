FROM ghcr.io/av/tools

WORKDIR /boost
COPY /src /boost

RUN uv venv
RUN uv pip install -r requirements.txt

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
