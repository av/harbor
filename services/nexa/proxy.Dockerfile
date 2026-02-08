FROM python:3.12

WORKDIR /app
RUN pip install fastapi uvicorn httpx
COPY ./proxy_server.py /app/proxy_server.py

CMD ["uvicorn", "proxy_server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]