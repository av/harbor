#!/usr/bin/env bash
# expect-hits: 4
# HARBOR010 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
size=$(stat -c %s file)
owner=$(stat -c '%U:%G' file)
mode=$(stat --format=%a file)
perm=$(stat --printf='%a\n' file)
