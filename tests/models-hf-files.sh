#!/usr/bin/env bash
set -euo pipefail

harbor_sh="${1:-$(dirname "$(dirname "${BASH_SOURCE[0]}")")/harbor.sh}"

# Load only model command routing, without starting Harbor's CLI entrypoint.
# shellcheck disable=SC1090
source <(sed -n '/^run_models_pull() {/,/^run_dmr_command() {/p' "$harbor_sh" | sed '$d')

run_hf_docker_cli() { printf 'hf'; printf '|%s' "$@"; }
run_llamacpp_pull() { printf 'llamacpp|%s' "$1"; }
run_ollama_command() { printf 'ollama|%s|%s' "$1" "$2"; }
log_error() { printf '%s\n' "$*" >&2; }

assert_pull() {
    local expected="$1"
    shift
    local actual
    actual=$(run_models_command "$@")
    if [ "$actual" != "$expected" ]; then
        printf 'Expected: %s\nActual:   %s\n' "$expected" "$actual" >&2
        exit 1
    fi
}

assert_pull 'hf|download|org/repo|file.gguf' pull --source hf org/repo file.gguf
assert_pull 'hf|download|org/repo|file-a.gguf|file-b.gguf' pull --source hf org/repo file-a.gguf file-b.gguf
assert_pull 'hf|download|org/repo' pull --source hf org/repo
assert_pull 'hf|download|org/repo|file.gguf' hf pull org/repo file.gguf
assert_pull 'hf|download|org/repo|file.gguf' pull org/repo file.gguf

echo 'Hugging Face file routing passed'
