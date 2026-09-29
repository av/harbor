#!/bin/sh
set -eu

for name in HARBOR_RAGFLOW_MYSQL_PASSWORD HARBOR_RAGFLOW_ES_PASSWORD HARBOR_RAGFLOW_S3_PASSWORD HARBOR_RAGFLOW_REDIS_PASSWORD HARBOR_RAGFLOW_ADMIN_PASSWORD HARBOR_RAGFLOW_SECRET_KEY; do
    value="$(printenv "$name" || true)"
    if [ "${#value}" -lt 32 ]; then
        echo "Set $name to a unique random value of at least 32 characters before starting RAGFlow." >&2
        exit 1
    fi
    case "$value" in
        *[!a-zA-Z0-9]*)
            echo "$name must contain only letters and digits." >&2
            exit 1
            ;;
    esac
done
