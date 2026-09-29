#!/bin/sh
set -eu

rc alias set lobehub http://lobehub-s3:9000 "$HARBOR_LOBEHUB_S3_ACCESS_KEY" "$HARBOR_LOBEHUB_S3_SECRET_KEY"
rc mb lobehub/lobe --ignore-existing
rc anonymous set-json /bucket.config.json lobehub/lobe
printf '%s' '<CORSConfiguration><CORSRule><AllowedOrigin>*</AllowedOrigin><AllowedMethod>GET</AllowedMethod><AllowedMethod>PUT</AllowedMethod><AllowedMethod>HEAD</AllowedMethod><AllowedHeader>*</AllowedHeader><ExposeHeader>ETag</ExposeHeader><MaxAgeSeconds>3600</MaxAgeSeconds></CORSRule></CORSConfiguration>' |
    rc bucket cors set lobehub/lobe -
