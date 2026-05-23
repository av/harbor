#!/usr/bin/env bash
# expect-hits: 2
# HARBOR009 fail fixture.
# shellcheck disable=all
if [ "$(wc -l < file)" -gt 100 ]; then echo "big"; fi
[ "$(wc -l <"$f")" -ge "$max" ] && echo "over"
