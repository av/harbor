#!/usr/bin/env bash
# HARBOR001 pass fixture — nothing here should trigger the rule.
# shellcheck disable=all
key="HELLO"
x="${key,,}"
y="${key^^}"
z=$(echo "$key" | tr 'a-z' 'A-Z')
w=$(echo "$key" | tr 'A-Z' 'a-z')
# The word "tr" appearing in comments and identifiers is fine:
# Referencing POSIX [:class:] in a comment is also fine.
attr_one="not_a_tr_call"
