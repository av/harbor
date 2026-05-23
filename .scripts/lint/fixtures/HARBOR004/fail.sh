#!/usr/bin/env bash
# expect-hits: 5
# HARBOR004 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
grep -P '\d+' file
grep -nP '\w+' file
grep --perl-regexp 'foo' file
grep -Pn 'foo' file
grep -i --perl-regexp 'foo' file
