#!/usr/bin/env bash
# expect-hits: 4
# HARBOR012 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
mapfile -t lines <<< "$input"
readarray -t rows < file.txt
declare -A seen
local -A cache
