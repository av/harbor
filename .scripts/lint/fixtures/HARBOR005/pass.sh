#!/usr/bin/env bash
# HARBOR005 pass fixture.
# shellcheck disable=all
find . -name '*.tmp' -exec rm -f {} +
find /var/cache -type f -exec rm -f {} +
