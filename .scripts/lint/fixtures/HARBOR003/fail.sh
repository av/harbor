#!/usr/bin/env bash
# expect-hits: 2
# HARBOR003 fail fixture.
# shellcheck disable=all
here=$(readlink -f "$0")
dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
