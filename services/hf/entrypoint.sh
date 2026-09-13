#!/bin/sh
# Compose defines SSL_CERT_FILE/REQUESTS_CA_BUNDLE as empty strings when
# HARBOR_HF_SSL_CERT_FILE is unset (empty ${VAR:+} expansion still sets the
# var). hf_xet's reqwest client fails with "builder error" on a set-but-empty
# SSL_CERT_FILE, so drop the vars when they carry no value.
set -e

[ -n "${SSL_CERT_FILE}" ] || unset SSL_CERT_FILE
[ -n "${REQUESTS_CA_BUNDLE}" ] || unset REQUESTS_CA_BUNDLE

exec hf "$@"
