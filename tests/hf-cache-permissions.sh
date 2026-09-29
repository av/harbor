#!/usr/bin/env bash
set -euo pipefail

# Exercise the production Compose dependency and mounted scripts with an
# existing HF image. All cache mutations are confined to a temporary fixture.
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d -t harbor-hf.XXXXXX)
export HARBOR_CONTAINER_PREFIX="hf-test-$$"
export HARBOR_USER_ID=12345 HARBOR_GROUP_ID=12346
export HARBOR_HF_CACHE="$test_dir/cache" HARBOR_HF_TOKEN='' HARBOR_HF_SSL_CERT_FILE=''
compose=(docker compose --project-directory "$repo_dir" -p "$HARBOR_CONTAINER_PREFIX"
  -f "$repo_dir/compose.yml" -f "$repo_dir/services/compose.hf.yml"
  -f "$repo_dir/tests/fixtures/hf-cache-compose.yml")
cleanup() {
  "${compose[@]}" down --volumes >/dev/null 2>&1 || true
  docker run --rm -v "$test_dir:/fixture" alpine:3.20 \
    chown -R "$(id -u):$(id -g)" /fixture
  rm -rf "$test_dir"
}
trap cleanup EXIT

for scenario in fresh legacy warm; do
  if [ "$scenario" = legacy ]; then
    docker run --rm -v "$HARBOR_HF_CACHE:/cache" alpine:3.20 sh -ec '
      mkdir -p /cache/hub/models--test/blobs /cache/hub/.locks /cache/xet /cache/assets /cache/unrelated
      touch /cache/hub/models--test/blobs/root-owned /cache/token /cache/stored_tokens
      touch /cache/hub/models--test/blobs/keep /cache/unrelated/keep
      chown 23456:23456 /cache/hub/models--test/blobs/keep
      ln -s /cache/unrelated/keep /cache/hub/external-link
      ln -s /cache/unrelated /cache/hub/external-dir
      chmod 700 /cache/hub/models--test /cache/xet
    '
  fi
  "${compose[@]}" run --rm --pull never hf env >/dev/null
  "${compose[@]}" run --rm --pull never --entrypoint python hf /probe.py "$scenario"
done

if [ "${HF_TEST_DOWNLOAD:-0}" = 1 ]; then
  "${compose[@]}" run --rm --pull never hf download hf-internal-testing/tiny-random-gpt2 config.json
fi
