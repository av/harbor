#!/bin/sh
# Executes cache-init.sh under stubs (no root, no container) against a fixture
# hub cache and asserts the exact set of paths it chowns: /data itself
# (non-recursively), every entry under models--* and .locks, and nothing else.
# CACHE_ROOT points the script at the fixture; chown is logged, mkdir is a no-op.
set -u
cd "$(dirname "$0")/../.." || exit 1
T=$(mktemp -d -t harbor.XXXXXX)
trap 'rm -rf "$T"' EXIT

mkdir -p "$T/bin" "$T/data/models--BAAI--bge/blobs" "$T/data/models--BAAI--bge/snapshots/abc" \
  "$T/data/.locks/models--BAAI--bge" "$T/data/datasets--x/blobs" "$T/data/spaces--y" "$T/data/other-dir" "$T/data/version.txt.d"
touch "$T/data/models--BAAI--bge/blobs/b1" "$T/data/models--BAAI--bge/snapshots/abc/config.json" \
  "$T/data/.locks/models--BAAI--bge/b1.lock" "$T/data/datasets--x/blobs/d1" "$T/data/spaces--y/s" \
  "$T/data/other-dir/f" "$T/data/version.txt.d/v" "$T/data/version.txt"

printf '#!/bin/sh\nshift 2; for p in "$@"; do echo "${p#%s}"; done >> "%s/log"\n' "$T" "$T" > "$T/bin/chown"
printf '#!/bin/sh\nexit 0\n' > "$T/bin/mkdir"
chmod +x "$T/bin/"*
: > "$T/log"

# TARGET_UID 4242 owns nothing in the fixture, so `! -user` selects everything
# the script chooses to visit; the log is therefore exactly its reach.
PATH="$T/bin:$PATH" CACHE_ROOT="$T/data" TARGET_UID=4242 TARGET_GID=4343 sh services/tei/cache-init.sh || { echo "cache-init.sh exited non-zero"; exit 1; }

expected="/data
/data/.locks
/data/.locks/models--BAAI--bge
/data/.locks/models--BAAI--bge/b1.lock
/data/models--BAAI--bge
/data/models--BAAI--bge/blobs
/data/models--BAAI--bge/blobs/b1
/data/models--BAAI--bge/snapshots
/data/models--BAAI--bge/snapshots/abc
/data/models--BAAI--bge/snapshots/abc/config.json"
actual=$(sort -u "$T/log")
[ "$actual" = "$expected" ] && exit 0
printf 'chowned path set differs from expected:\n--- expected\n%s\n--- actual\n%s\n' "$expected" "$actual"
exit 1
