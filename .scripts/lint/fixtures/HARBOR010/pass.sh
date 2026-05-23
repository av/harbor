#!/usr/bin/env bash
# HARBOR010 pass fixture.
# shellcheck disable=all
if [[ "$(uname)" == "Darwin" ]]; then
  size=$(stat -f %z file)
else
  size=$(stat -c %s file)  # harbor-lint disable=HARBOR010
fi
