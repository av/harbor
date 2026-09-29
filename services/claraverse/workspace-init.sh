#!/bin/sh
set -eu

mkdir -p /workspace/data /workspace/uploads
umask 077
if [ ! -s /workspace/data/.mysql_root_password ]; then
    dd if=/dev/urandom bs=1 count=32 2>/dev/null | od -An -tx1 | tr -d ' \n' > /workspace/data/.mysql_root_password
fi
if [ ! -s /workspace/data/.mysql_password ]; then
    dd if=/dev/urandom bs=1 count=32 2>/dev/null | od -An -tx1 | tr -d ' \n' > /workspace/data/.mysql_password
fi
chown -R "${TARGET_UID}:${TARGET_GID}" /workspace/data /workspace/uploads
