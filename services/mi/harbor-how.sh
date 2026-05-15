#!/bin/sh
if [ -f /harbor/how.prompt ]; then
    export SYSTEM_PROMPT
    SYSTEM_PROMPT=$(cat /harbor/how.prompt)
fi
exec node /home/mi/app/index.mjs "$@"
