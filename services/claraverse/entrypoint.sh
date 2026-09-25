#!/bin/sh
set -eu

mysql_password="$(cat /app/data/.mysql_password)"
export DATABASE_URL="mysql://claraverse:${mysql_password}@claraverse-mysql:3306/claraverse?parseTime=true"
exec /app/docker-entrypoint.sh "$@"
