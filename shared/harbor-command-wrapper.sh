#!/usr/bin/env bash
set -euo pipefail

command_name=${0##*/}
wrapper_path=${BASH_SOURCE[0]}
while [[ -L "$wrapper_path" ]]; do
    link_target=$(readlink "$wrapper_path")
    case "$link_target" in
        /*) wrapper_path=$link_target ;;
        *) wrapper_path=$(dirname "$wrapper_path")/$link_target ;;
    esac
done
wrapper_dir=$(cd -P "$(dirname "$wrapper_path")" && pwd)

exec "$wrapper_dir/../harbor.sh" "$command_name" "$@"
