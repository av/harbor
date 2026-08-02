#!/bin/sh
set -eu

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
