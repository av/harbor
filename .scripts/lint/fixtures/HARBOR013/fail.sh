#!/usr/bin/env bash
# expect-hits: 5
# HARBOR013 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
echo "$services" | grep -q '\bdmr\b'
grep -v '^\s*#' .env
grep -qi "permission denied\|access denied" out.log
grep -oP '(?<=key=)\w+' file.txt
sed 's/\s\+/ /g' file.txt
