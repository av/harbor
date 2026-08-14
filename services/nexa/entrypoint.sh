#!/bin/sh
set -eu

# Drop to the host user so model downloads land host-owned in the
# HARBOR_NEXA_CACHE bind mount (/root/.cache/nexa.ai). The cache is
# per-service and small, so a recursive chown repairs any files a
# previous root-run container left behind. The script then re-execs
# itself unprivileged so both pull and serve run as the host user.
UID_T="${TARGET_UID:-1000}"
GID_T="${TARGET_GID:-1000}"

if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then
  chown "$UID_T:$GID_T" /root /root/.cache 2>/dev/null || true
  chown -R "$UID_T:$GID_T" /root/.cache/nexa.ai 2>/dev/null || true
  chmod 755 /root
  exec setpriv --reuid "$UID_T" --regid "$GID_T" --clear-groups \
    env HOME=/root "$0" "$@"
fi

# "serve" starts the OpenAI-compatible server: pre-pull the
# configured model, then bind to all interfaces for the
# Harbor network. Any other invocation is passed to the
# nexa CLI as-is (harbor nexa <cmd>).
if [ "${1:-}" = "serve" ]; then
  shift

  if [ -n "${HARBOR_NEXA_MODEL:-}" ]; then
    # --model-type skips the CLI's interactive "Choose Model Type"
    # prompt, which hard-requires a TTY and would hang the container
    nexa pull --model-type llm "$HARBOR_NEXA_MODEL" < /dev/null \
      || echo "nexa: failed to pull '$HARBOR_NEXA_MODEL', starting server anyway"
  fi

  exec nexa serve --host "${NEXA_HOST:-0.0.0.0:8000}" "$@"
fi

exec nexa "$@"
