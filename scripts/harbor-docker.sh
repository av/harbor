#!/usr/bin/env bash
set -euo pipefail

script_root=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
harbor_root=${HARBOR_HOME:-$script_root}
if [[ ! -f "$harbor_root/harbor.sh" ]]; then
    echo "Harbor workspace not found: $harbor_root" >&2
    exit 1
fi
harbor_root=$(cd -P "$harbor_root" && pwd)
host_home=$(cd -P "$HOME" && pwd)

docker_endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{ .Endpoints.docker.Host }}')}
case "$docker_endpoint" in
    unix://*) socket_path=${docker_endpoint#unix://} ;;
    *)
        echo "A local Unix Docker socket is required (found: $docker_endpoint)" >&2
        exit 1
        ;;
esac
if [[ ! -S "$socket_path" ]]; then
    echo "The local Docker socket is unavailable: $socket_path" >&2
    exit 1
fi

image=${HARBOR_CLI_IMAGE:-harbor-cli:local}
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build -t "$image" -f "$script_root/docker/harbor-cli/Dockerfile" "$script_root/docker/harbor-cli"
fi

docker_args=(
    --rm -i
    --user "$(id -u):$(id -g)"
    --mount "type=bind,source=$host_home,target=$host_home"
    --mount "type=bind,source=$socket_path,target=/var/run/docker.sock"
    --workdir "$harbor_root"
    --env "HOME=$host_home"
    --env "HARBOR_HOME=$harbor_root"
    --env "DENO_DIR=$host_home/.cache/harbor-cli-deno"
    --env 'DOCKER_HOST=unix:///var/run/docker.sock'
)

case "$harbor_root/" in
    "$host_home/"*) ;;
    *) docker_args+=(--mount "type=bind,source=$harbor_root,target=$harbor_root") ;;
esac

if [[ -t 0 && -t 1 ]]; then
    docker_args+=(-t)
fi

if socket_gid=$(stat -Lc %g "$socket_path" 2>/dev/null) ||
    socket_gid=$(stat -Lf %g "$socket_path" 2>/dev/null); then
    docker_args+=(--group-add "$socket_gid")
fi

if [[ "$(uname)" == Linux ]]; then
    docker_args+=(--network host)
    if command -v getenforce >/dev/null && [[ "$(getenforce)" == Enforcing ]]; then
        docker_args+=(--security-opt label=disable)
    fi
fi

exec docker run "${docker_args[@]}" --entrypoint /bin/bash "$image" "$harbor_root/harbor.sh" "$@"
