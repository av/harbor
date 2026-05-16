#!/bin/sh
set -eu

default_model_size="${HARBOR_VOICEBOX_DEFAULT_MODEL_SIZE:-0.6B}"

case "${default_model_size}" in
  0.6B|1.7B) ;;
  *)
    echo "Unsupported HARBOR_VOICEBOX_DEFAULT_MODEL_SIZE: ${default_model_size}" >&2
    exit 1
    ;;
esac

for asset in /app/frontend/assets/index-*.js; do
  [ -f "${asset}" ] || continue
  if grep -q 'modelSize:"1.7B"' "${asset}"; then
    tmp_asset="${asset}.harbor.tmp"
    sed "s/modelSize:\"1.7B\"/modelSize:\"${default_model_size}\"/g" "${asset}" > "${tmp_asset}"
    mv "${tmp_asset}" "${asset}"
  fi
done

exec "$@"
