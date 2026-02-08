#!/bin/sh
set -e

export ONYX_BACKEND_API_HOST="${ONYX_BACKEND_API_HOST:-onyx-api}"
export ONYX_WEB_SERVER_HOST="${ONYX_WEB_SERVER_HOST:-onyx-web}"

echo "Using API server host: $ONYX_BACKEND_API_HOST"
echo "Using web server host: $ONYX_WEB_SERVER_HOST"

envsubst '$ONYX_BACKEND_API_HOST $ONYX_WEB_SERVER_HOST' < /etc/nginx/conf.d/app.conf.template > /etc/nginx/conf.d/default.conf

echo "Waiting for API server to be ready..."
max_attempts=120
attempt=1
while [ $attempt -le $max_attempts ]; do
    if wget -q --spider "http://${ONYX_BACKEND_API_HOST}:8080/health" 2>/dev/null; then
        echo "API server is ready!"
        break
    fi
    echo "Attempt $attempt/$max_attempts: API server not ready yet..."
    sleep 5
    attempt=$((attempt + 1))
done

if [ $attempt -gt $max_attempts ]; then
    echo "Warning: API server did not become ready in time, starting nginx anyway..."
fi

echo "Starting nginx..."
exec nginx -g "daemon off;"
