#!/usr/bin/env bash
# HARBOR003 pass fixture.
# shellcheck disable=all
here=$(realpath "$0")
dir=$(cd "$(dirname "$0")" && pwd)
# Context mentioning the flag in a string is not a call:
msg="readlink does not support -f on macOS"
