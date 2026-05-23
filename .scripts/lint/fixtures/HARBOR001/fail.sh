#!/usr/bin/env bash
# expect-hits: 3
# HARBOR001 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
key="HELLO"
x=$(echo "$key" | tr '[:lower:]' '[:upper:]')
y=$(echo "$key" | tr '[:upper:]' '[:lower:]')
z=$(printf '%s' "$key" | tr   "[:upper:]"   "[:lower:]")
