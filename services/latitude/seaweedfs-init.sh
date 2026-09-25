#!/bin/sh
set -e

bucket="${LAT_STORAGE_S3_BUCKET:-latitude}"
(
  until echo "s3.bucket.list" | weed shell 2>/dev/null | awk '{print $1}' | grep -qx "$bucket"; do
    echo "s3.bucket.create -name $bucket" | weed shell >/dev/null 2>&1 || true
    sleep 2
  done
  echo "Bucket '$bucket' is ready."
) &

exec /entrypoint.sh "$@"
