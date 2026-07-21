#!/usr/bin/env bash
# HARBOR013 pass fixture.
# shellcheck disable=all
echo "$services" | grep -qw 'dmr'
grep -v '^[[:space:]]*#' .env
grep -qiE "permission denied|access denied" out.log
grep -E '(^| )dmr( |$)' <<< "$services"
sed 's/[[:space:]][[:space:]]*/ /g' file.txt
grep -q '\bdmr\b' file  # harbor-lint disable=HARBOR013
