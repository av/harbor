#!/usr/bin/env bash
# expect-hits: 3
# HARBOR006 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
head -c 16 /dev/urandom
cat file | head -c 100
head --bytes=16 /dev/urandom
