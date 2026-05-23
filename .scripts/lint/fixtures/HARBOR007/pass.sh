#!/usr/bin/env bash
# HARBOR007 pass fixture.
# shellcheck disable=all
tmp=$(mktemp -t harbor.XXXXXX)
tmp_dir=$(mktemp -d -t harbor.XXXXXX)
# Positional template is also portable:
tmp2=$(mktemp /tmp/harbor.XXXXXX)
