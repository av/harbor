#!/usr/bin/env bash
# HARBOR006 pass fixture.
# shellcheck disable=all
dd if=/dev/urandom bs=1 count=16 2>/dev/null
head -n 1 file
