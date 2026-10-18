#!/bin/sh
set -eu
mkdir -p /logs/verifier
if printf 'hello harbor-evals\n' | cmp -s - /app/hello.txt; then
    printf '1\n' > /logs/verifier/reward.txt
else
    printf '0\n' > /logs/verifier/reward.txt
fi
