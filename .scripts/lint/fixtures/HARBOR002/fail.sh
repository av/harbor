#!/usr/bin/env bash
# expect-hits: 4
# HARBOR002 fail fixture — every non-comment line here must trigger the rule.
# shellcheck disable=all
sed -i 's/foo/bar/' file
sed -i "s|foo|bar|" file
sed -i -e 's/foo/bar/' file
sed --in-place 's/foo/bar/' file
