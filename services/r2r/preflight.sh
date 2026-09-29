#!/bin/sh
set -eu

for name in HARBOR_R2R_DB_PASSWORD HARBOR_R2R_SECRET_KEY HARBOR_R2R_ADMIN_PASSWORD; do
    value="$(printenv "$name" || true)"
    if [ "${#value}" -lt 32 ]; then
        echo "Set $name to a unique random value of at least 32 characters before starting R2R." >&2
        exit 1
    fi
    case "$value" in
        *[!a-zA-Z0-9]*)
            echo "$name must contain only letters and digits." >&2
            exit 1
            ;;
    esac
done

for name in HARBOR_R2R_CHAT_MODEL HARBOR_R2R_EMBEDDING_MODEL; do
    value="$(printenv "$name" || true)"
    case "$value" in
        ''|*[!a-zA-Z0-9._:/-]*)
            echo "$name has an invalid model name." >&2
            exit 1
            ;;
    esac
done
