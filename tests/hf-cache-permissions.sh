#!/usr/bin/env bash
set -euo pipefail

# Offline regression against the real HF image and its privilege-drop tools.
# All writable state is inside disposable containers, never the host HF cache.
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
for cache_owner in 0 12345; do
  docker run --rm --network none --user 0 \
    -e TARGET_UID=12345 -e TARGET_GID=12346 -e CACHE_OWNER="$cache_owner" \
    -e SSL_CERT_FILE= -e REQUESTS_CA_BUNDLE= \
    -v "$repo_dir/services/hf/entrypoint.sh:/entrypoint.sh:ro" \
    -v "$repo_dir/tests/fixtures/hf-cache-probe.py:/usr/local/bin/hf:ro" \
    --entrypoint sh "${HF_TEST_IMAGE:-harbor-hf:latest}" -ec '
      mkdir -p /root/.cache/huggingface/existing
      chown "$CACHE_OWNER:12346" /root/.cache/huggingface
      touch /root/.cache/huggingface/existing/keep
      chown 23456:23456 /root/.cache/huggingface/existing/keep
      exec sh /entrypoint.sh
    '
done
