#!/usr/bin/env bash
# HARBOR004 pass fixture.
# shellcheck disable=all
grep -E '[0-9]+' file
grep -En '[[:alnum:]]+' file
grep 'foo' file
# -P inside a regex pattern is fine: it's part of the search string, not a flag.
grep "-P" file
