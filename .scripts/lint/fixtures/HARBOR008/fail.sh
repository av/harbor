#!/usr/bin/env bash
# expect-hits: 4
# HARBOR008 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
now=$(date +%s%N)
stamp=$(date +%Y%m%d-%H%M%S-%N)
q1=$(date "+%s%N")
q2=$(date '+%Y%m%d-%H%M%S-%N')
