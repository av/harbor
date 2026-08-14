#!/bin/sh
# Compose defines SSL_CERT_FILE/REQUESTS_CA_BUNDLE as empty strings when
# HARBOR_HF_SSL_CERT_FILE is unset (empty ${VAR:+} expansion still sets the
# var). hf_xet's reqwest client fails with "builder error" on a set-but-empty
# SSL_CERT_FILE, so drop the vars when they carry no value.
set -e

[ -n "${SSL_CERT_FILE}" ] || unset SSL_CERT_FILE
[ -n "${REQUESTS_CA_BUNDLE}" ] || unset REQUESTS_CA_BUNDLE

# Drop to the host user so downloads land host-owned in the shared HF cache.
# Only the top-level dirs are chowned — the cache bind mount itself is already
# host-owned and can be huge, so no recursive chown.
UID_T="${TARGET_UID:-1000}"
GID_T="${TARGET_GID:-1000}"

if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then
  chown "$UID_T:$GID_T" /root /root/.cache 2>/dev/null || true
  chmod 755 /root
  exec setpriv --reuid "$UID_T" --regid "$GID_T" --clear-groups \
    env HOME=/root hf "$@"
fi

exec hf "$@"
