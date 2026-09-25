#!/bin/sh
set -eu

for name in HARBOR_LOBEHUB_AUTH_SECRET HARBOR_LOBEHUB_KEY_VAULTS_SECRET HARBOR_LOBEHUB_JWKS_KEY_B64 HARBOR_LOBEHUB_DB_PASSWORD HARBOR_LOBEHUB_S3_SECRET_KEY; do
    value="$(printenv "$name" || true)"
    if [ "${#value}" -lt 32 ]; then
        echo "Set $name to a unique random value of at least 32 characters before starting LobeHub." >&2
        exit 1
    fi
done

if ! jwks_key="$(printf '%s' "$HARBOR_LOBEHUB_JWKS_KEY_B64" | base64 -d 2>/dev/null)"; then
    echo 'HARBOR_LOBEHUB_JWKS_KEY_B64 must contain base64-encoded JWKS JSON.' >&2
    exit 1
fi

case "$jwks_key" in
    '{"keys":'*'"kty":"RSA"'*) ;;
    *)
        echo 'HARBOR_LOBEHUB_JWKS_KEY_B64 must decode to an RSA JWKS JSON object.' >&2
        exit 1
        ;;
esac

case "$HARBOR_LOBEHUB_DB_PASSWORD" in
    *[!a-zA-Z0-9]*)
        echo 'HARBOR_LOBEHUB_DB_PASSWORD must be URL-safe alphanumeric text.' >&2
        exit 1
        ;;
esac
