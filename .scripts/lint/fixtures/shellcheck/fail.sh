#!/usr/bin/env bash
# Shellcheck self-test fixture: classic SC2086 (unquoted variable expansion).
# $1 is an external value that may contain spaces/globs, so shellcheck flags
# the unquoted expansion below.
rm -rf $1
