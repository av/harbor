#!/usr/bin/env bash
# expect-hits: 2
# HARBOR005 fail fixture.
# shellcheck disable=all
find . -name '*.tmp' -delete
find /var/cache -type f -delete
