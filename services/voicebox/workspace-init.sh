#!/bin/sh
set -eu

mkdir -p /workspace/data/home /workspace/data/generations /workspace/generations /workspace/huggingface
chown -R "${TARGET_UID}:${TARGET_GID}" /workspace/data /workspace/generations /workspace/huggingface
