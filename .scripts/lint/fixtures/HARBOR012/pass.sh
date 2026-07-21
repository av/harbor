#!/usr/bin/env bash
# HARBOR012 pass fixture.
# shellcheck disable=all
lines=()
while IFS= read -r line; do
  [ -n "$line" ] && lines+=("$line")
done <<< "$input"
declare -a indexed=()
mapfile -t ok <<< "$input"  # harbor-lint disable=HARBOR012
