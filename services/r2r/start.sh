#!/bin/sh
set -eu
umask 077

sed \
    -e "s|__ADMIN_PASSWORD__|$HARBOR_R2R_ADMIN_PASSWORD|g" \
    -e "s|__CHAT_MODEL__|$HARBOR_R2R_CHAT_MODEL|g" \
    -e "s|__EMBEDDING_MODEL__|$HARBOR_R2R_EMBEDDING_MODEL|g" \
    "$HARBOR_R2R_CONFIG_TEMPLATE" > "$R2R_CONFIG_PATH"

exec uvicorn core.main.app_entry:app --host "$R2R_HOST" --port "$R2R_PORT"
