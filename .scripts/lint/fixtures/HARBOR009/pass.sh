#!/usr/bin/env bash
# HARBOR009 pass fixture.
# shellcheck disable=all
count=$(wc -l < file | tr -d ' ')
if [ "$count" -gt 100 ]; then echo "big"; fi
lines=$(wc -l <"$f" | tr -d ' ')
[ "$lines" -ge "$max" ] && echo "over"
