#!/usr/bin/with-contenv bash

# Start Harbor Agent
cd /config/agent/src || exit 1
uvicorn main:app --host 0.0.0.0 --port 8000 --reload