#!/usr/bin/env bash
# HARBOR002 pass fixture.
# shellcheck disable=all
sed -i '' 's/foo/bar/' file
sed -i "" 's/foo/bar/' file
# Darwin/Linux branch pattern is explicitly allowed via inline disable.
if [[ "$(uname)" == "Darwin" ]]; then
  sed -i '' 's/foo/bar/' file
else
  sed -i 's/foo/bar/' file  # harbor-lint disable=HARBOR002
fi
