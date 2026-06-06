#!/usr/bin/env bash

set -eo pipefail

# ========================================================================
# == Functions
# ========================================================================

# Portable timeout: run a command with a time limit.
# Uses GNU timeout if available, falls back to perl (always on macOS).
# Returns 124 on timeout (matching GNU timeout convention).
# Usage: _with_timeout 10 docker info
_with_timeout() {
    local secs="$1"; shift
    if command -v timeout &>/dev/null; then
        timeout "$secs" "$@"
        return $?
    elif command -v perl &>/dev/null; then
        perl -e '
            my $t=shift @ARGV;
            my $pid=fork;
            if(!$pid){exec @ARGV;die "exec: $!"}
            $SIG{ALRM}=sub{kill 15,$pid;exit 124};
            alarm $t;
            waitpid $pid,0;
            exit($?>>8)
        ' "$secs" "$@"
        return $?
    else
        # No timeout mechanism available; run without time limit
        "$@"
        return $?
    fi
}

# Check that Docker is installed, Compose v2 is available, and the daemon
# is reachable.  Provides clear, actionable error messages for first-run
# users who may not yet have Docker set up.
# Caches the result so repeated calls in the same invocation are free.
_docker_ok=""
_check_docker() {
    # Return cached result when available
    if [ -n "$_docker_ok" ]; then
        [ "$_docker_ok" = "1" ] && return 0 || return 1
    fi

    if ! command -v docker &>/dev/null; then
        _docker_ok=0
        log_error "Docker is not installed."
        log_error "Harbor requires Docker to run services."
        if [[ "$(uname)" == "Darwin" ]]; then
            log_error "Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/"
        else
            log_error "Install Docker Engine: https://docs.docker.com/engine/install/"
        fi
        log_error "After installing, run 'harbor doctor' to verify your setup."
        return 1
    fi

    # docker compose version is fast (no daemon contact) and confirms
    # both the Docker CLI and the Compose plugin are installed.
    if ! docker compose version &>/dev/null; then
        _docker_ok=0
        log_error "Docker Compose (v2) is not available."
        log_error "Harbor requires the Docker Compose plugin (v2)."
        log_error "If Docker is installed, ensure the Compose plugin is included."
        log_error "Check: https://docs.docker.com/compose/install/"
        log_error "Run 'harbor doctor' for full diagnostics."
        return 1
    fi

    # Verify the daemon is actually running.  Use docker version which is
    # faster than docker info (no system enumeration) but still contacts
    # the daemon.  Guard with timeout to avoid hanging when daemon is
    # unresponsive (e.g. Docker Desktop still loading).
    # Capture exit code before the if-test consumes it ($? is always 0
    # inside a then-block).
    local docker_exit=0
    _with_timeout 5 docker version &>/dev/null || docker_exit=$?
    if [ "$docker_exit" -ne 0 ]; then
        _docker_ok=0
        if [ "$docker_exit" -eq 124 ]; then
            log_error "Docker daemon is not responding (timed out after 5s)."
            log_error "It may still be starting up. Wait a moment and try again."
        else
            log_error "Docker daemon is not running or not reachable."
        fi
        if [[ "$(uname)" == "Darwin" ]]; then
            log_error "Start Docker Desktop and wait for it to finish loading."
        else
            log_error "Start the Docker daemon: sudo systemctl start docker"
        fi
        log_error "Run 'harbor doctor' for full diagnostics."
        return 1
    fi

    _docker_ok=1
    return 0
}

# Check if a specific TCP port is in use on the host.
# Uses ss (Linux), lsof (macOS/fallback), or /dev/tcp (bash builtin).
# Returns 0 if the port IS in use, 1 if free.
_is_port_in_use() {
    local port="$1"
    if command -v ss &>/dev/null; then
        ss -tln "sport = :$port" 2>/dev/null | grep -q "LISTEN"
        return $?
    elif command -v lsof &>/dev/null; then
        lsof -iTCP:"$port" -sTCP:LISTEN -P -n &>/dev/null
        return $?
    else
        # Bash builtin /dev/tcp — opening a connection succeeds if port is listening
        (echo >/dev/tcp/127.0.0.1/"$port") 2>/dev/null
        return $?
    fi
}

# Parse "docker compose config" output for host port mappings.
# Outputs lines of "service_name:host_port" for each published port.
_parse_compose_ports() {
    local config_output="$1"
    # Parse the YAML: find service names (top-level keys under "services:")
    # and their published ports.
    awk '
    /^services:/ { in_services=1; next }
    in_services && /^[^ ]/ { in_services=0 }
    in_services && /^  [a-zA-Z0-9_-]+:/ {
        gsub(/^  /, ""); gsub(/:.*/, "")
        current_service=$0
        next
    }
    in_services && /published:/ {
        gsub(/.*published: *"?/, ""); gsub(/"? *$/, "")
        if ($0 ~ /^[0-9]+$/) {
            print current_service ":" $0
        }
    }
    ' <<< "$config_output"
}

# Check for port conflicts before starting services.
# 1. Inter-service conflicts: two services mapping the same host port
# 2. Host conflicts: a host port already in use by another process
# Returns 0 (no conflicts) or 1 (conflicts found).
# Args: same as compose_with_options (service names and flags)
_check_port_conflicts() {
    local compose_cmd
    compose_cmd=$(compose_with_options "$@") || return 0  # If compose resolution fails, skip check

    local config_output
    config_output=$($compose_cmd config 2>/dev/null) || return 0  # If config fails, skip check

    local port_mappings
    port_mappings=$(_parse_compose_ports "$config_output")

    if [ -z "$port_mappings" ]; then
        return 0
    fi

    local has_conflict=false

    # 1. Check for inter-service duplicate ports.
    # Uses a flat string of "port=service" pairs instead of associative
    # arrays for bash 3.2 (macOS) compatibility.
    local seen_ports=""
    local conflict_ports=""
    while IFS= read -r entry; do
        local svc="${entry%%:*}"
        local port="${entry##*:}"

        # Look up which service already claimed this port
        local existing=""
        existing=$(printf '%s' "$seen_ports" | grep "^${port}=" | head -1 | sed 's/^[^=]*=//')

        if [ -n "$existing" ] && [ "$svc" != "$existing" ]; then
            has_conflict=true
            conflict_ports="$conflict_ports:$port:"
            local svc_upper other_upper
            svc_upper=$(printf '%s' "$svc" | tr 'a-z-' 'A-Z_')
            other_upper=$(printf '%s' "$existing" | tr 'a-z-' 'A-Z_')
            log_error "Port conflict: ${c_g}$existing${c_nc} and ${c_g}$svc${c_nc} both map host port $port."
            log_error "Change one with: harbor config set HARBOR_${svc_upper}_HOST_PORT <new_port>"
            log_error "             or: harbor config set HARBOR_${other_upper}_HOST_PORT <new_port>"
        elif [ -z "$existing" ]; then
            seen_ports="${seen_ports}${port}=${svc}"$'\n'
        fi
    done <<< "$port_mappings"

    # 2. Check for host port conflicts (ports already in use).
    # Skip ports that have inter-service conflicts (already reported).
    # Also skip ports owned by already-running Harbor containers (docker
    # compose will reuse them without conflict).
    local harbor_ports=""
    if [ -n "$default_container_prefix" ]; then
        harbor_ports=$(docker ps --format '{{.Ports}}' --filter "name=${default_container_prefix}" 2>/dev/null \
            | grep -oE '(0\.0\.0\.0|\[::\]):[0-9]+' | sed 's/.*://' | sort -u) || true
    fi

    local checked_ports=""
    while IFS= read -r entry; do
        local svc="${entry%%:*}"
        local port="${entry##*:}"

        # Skip inter-service conflict ports
        case "$conflict_ports" in
            *":$port:"*) continue ;;
        esac
        # Skip duplicate port checks (same port, multiple protocols)
        case "$checked_ports" in
            *":$port:"*) continue ;;
        esac
        checked_ports="$checked_ports:$port:"

        # Skip ports already bound by Harbor's own containers
        if printf '%s\n' "$harbor_ports" | grep -qx "$port" 2>/dev/null; then
            continue
        fi

        if _is_port_in_use "$port"; then
            has_conflict=true
            local svc_upper
            svc_upper=$(printf '%s' "$svc" | tr 'a-z-' 'A-Z_')
            log_warn "Port $port needed by ${c_g}$svc${c_nc} is already in use on the host."
            log_warn "Change it with: harbor config set HARBOR_${svc_upper}_HOST_PORT <new_port>"
            log_warn "Or stop the process using port $port."
        fi
    done <<< "$port_mappings"

    if $has_conflict; then
        log_info "Use 'harbor up --skip-port-check' to start anyway."
        return 1
    fi

    return 0
}

show_version() {
    echo "Harbor CLI version: $version"
}

show_help() {
    show_version
    echo "Usage: $0 <command> [options]"
    echo
    echo "Start here (for AI agents):"
    echo "  harbor skills get harbor"
    echo
    echo "  Skills ship with the CLI (always version-matched) and include"
    echo "  workflow patterns, service guides, and copy-paste examples."
    echo "  Prefer this over guessing commands from flag docs alone."
    echo
    echo "  skills [list]            List available skills"
    echo "  skills get harbor        Core CLI usage guide"
    echo "  skills get <name>        Load a specialized skill"
    echo "  skills path [name]       Print skill directory path"
    echo
    echo "Compose Setup Commands:"
    echo "  up|u|start|s [handle(s)] - Start the service(s)"
    echo "    up --tail             - Start and tail the logs"
    echo "    up --open             - Start and open in the browser"
    echo "    up --no-defaults      - Do not include default services"
    echo "    up --skip-port-check  - Skip port conflict pre-check"

    echo "  down|d                  - Stop and remove the containers"
    echo "  restart|r [handle]      - Down then up"
    echo "  ps                      - List the running containers"
    echo "  logs|l <handle>         - View the logs of the containers"
    echo "  exec <handle> [command] - Execute a command in a running service"
    echo "  pull <handle>           - Pull the latest images or models"
    echo "    pull <service>        - Pull Docker images for a service"
    echo "    pull <model>          - Pull Ollama model or llama.cpp HF model"
    echo "  dive <handle>           - Run the Dive CLI to inspect Docker images"
    echo "  run <alias>             - Run a command defined as an alias"
    echo "  run <handle> [command]  - Run a one-off command in a service container"
    echo "  shell <handle>          - Load shell in the given service main container"
    echo "  build <handle>          - Build the given service"
    echo "  stats                   - Show resource usage statistics"
    echo "  attach <handle>         - Attach to a running service container"
    echo "  cmd <handle>            - Print the docker compose command"
    echo "  launch <handle> [args]  - Launch a service CLI with currently running Harbor services"
    echo
    echo "Setup Management Commands:"
    echo "  webui     - Configure Open WebUI Service"
    echo "  llamacpp  - Configure llamacpp service"
    echo "  ikllamacpp - Configure ik_llama.cpp service"
    echo "  tgi       - Configure text-generation-inference service"
    echo "  litellm   - Configure LiteLLM service"
    echo "  langflow  - Configure Langflow UI Service"
    echo "  openai    - Configure OpenAI API keys and URLs"
    echo "  vllm      - Configure VLLM service"
    echo "  dmr       - Configure Docker Model Runner backend"
    echo "  mlx       - Configure host MLX backend"
    echo "  omlx      - Configure host oMLX backend"
    echo "  aphrodite - Configure Aphrodite service"
    echo "  tabbyapi  - Configure TabbyAPI service"
    echo "  mistralrs - Configure mistral.rs service"
    echo "  cfd       - Run cloudflared CLI"
    echo "  airllm    - Configure AirLLM service"
    echo "  txtai     - Configure txtai service"
    echo "  chatui    - Configure HuggingFace ChatUI service"
    echo "  comfyui   - Configure ComfyUI service"
    echo "  parler    - Configure Parler service"
    echo "  sglang    - Configure SGLang CLI"
    echo "  omnichain - Work with Omnichain service"
    echo "  jupyter   - Configure Jupyter service"
    echo "  ol1       - Configure ol1 service"
    echo "  ktransformers - Configure ktransformers service"
    echo "  kobold    - Configure Koboldcpp service"
    echo "  morphic   - Configure Morphic service"
    echo "  modularmax - Configure Modular MAX service"
    echo "  boost     - Configure Harbor Boost service"
    echo "  hermes    - Configure Hermes Agent service"
    echo "  stt       - Configure Speech-to-Text service"
    echo "  speaches  - Configure Speaches service"
    echo "  webtop    - Configure Webtop service"
    echo "  mcp       - Configure MCP service"
    echo "  oterm     - Configure oterm service"
    echo
    echo "Service CLIs:"
    echo "  ollama     - Run Ollama CLI (docker). Service should be running."
    echo "  aider             - Launch Aider CLI"
    echo "  aichat            - Run aichat CLI"
    echo "  interpreter|opint - Launch Open Interpreter CLI"
    echo "  fabric            - Run Fabric CLI"
    echo "  facts             - Run facts CLI against the current directory"
    echo "  mi                - Run mi agent CLI against the current directory"
    echo "  plandex           - Launch Plandex CLI"
    echo "  cmdh              - Run cmdh CLI"
    echo "  parllama          - Launch Parllama - TUI for chatting with Ollama models"
    echo "  bench             - Run and manage Harbor Bench"
    echo "  lmeval|lm_eval    - Run LM Evaluation Harness"
    echo "  openhands|oh      - Run OpenHands service"
    echo "  repopack          - Run the Repopack CLI"
    echo "  nexa              - Run the Nexa CLI, configure the service"
    echo "  gptme             - Run gptme CLI, configure the service"
    echo "  nanobot           - Run nanobot CLI"
    echo "  promptfoo|pf      - Run promptfoo CLI for LLM testing and evaluation"
    echo "  tokscale           - Run tokscale CLI to monitor AI token usage and costs"
    echo "  hf                - Run the Harbor's Hugging Face CLI. Expanded with a few additional commands."
    echo "    hf dl           - HuggingFaceModelDownloader CLI"
    echo "    hf parse-url    - Parse file URL from Hugging Face"
    echo "    hf token        - Get/set the Hugging Face Hub token"
    echo "    hf cache        - Get/set the path to Hugging Face cache"
    echo "    hf find <query> - Open HF Hub with a query (trending by default)"
    echo "    hf path <spec>  - Print a folder in HF cache for a given model spec"
    echo "    hf *            - Anything else is passed to the official Hugging Face CLI"
    echo "  models            - Manage models across Ollama, HuggingFace, llama.cpp, DMR, MLX, and oMLX"
    echo "  k6                - Run K6 CLI"
    echo
    echo "Harbor CLI Commands:"
    echo "  open <handle>                 - Open a service in the default browser"
    echo "  launch <handle> [args]        - Launch a service CLI with currently running Harbor services"
    echo
    echo "  url <handle>                  - Get the URL for a service"
    echo "    url <handle>                         - Url on the local host"
    echo "    url [-a|--addressable|--lan] <handle> - (supposed) LAN URL"
    echo "    url [-i|--internal] <handle>         - URL within Harbor's docker network"
    echo
    echo "  qr <handle>                   - Print a QR code for a service"
    echo
    echo "  t|tunnel <handle>             - Expose given service to the internet"
    echo "    tunnel down|stop|d|s        - Stop all running tunnels (including auto)"
    echo "  tunnels [ls|rm|add]           - Manage services that will be tunneled on 'up'"
    echo "    tunnels rm <handle|index>   - Remove, also accepts handle or index"
    echo "    tunnels add <handle>        - Add a service to the tunnel list"
    echo
    echo "  config [get|set|ls]           - Manage the Harbor environment configuration"
    echo "    config ls                   - All config values in ENV format"
    echo "    config get <field>          - Get a specific config value"
    echo "    config set <field> <value>  - Set a specific config value"
    echo "    config reset                - Reset Harbor configuration to default .env"
    echo "    config update               - Merge upstream config changes from default .env"
    echo "    config search <query>       - Search config keys and values"
    echo
    echo "  env <service> [key] [value]   - Manage override.env variables for a service"
    echo "    env <service>               - List all variables for a service"
    echo "    env <service> <key>         - Get a specific variable for a service"
    echo "    env <service> <key> <value> - Set a specific variable for a service"
    echo "    env <service> get <key>     - Get a specific variable (explicit form)"
    echo "    env <service> unset <key>   - Remove a specific variable for a service"
    echo
    echo "  profile|profiles|p [ls|rm|add] - Manage Harbor profiles"
    echo "    profile ls|list             - List all profiles"
    echo "    profile rm|remove <name>    - Remove a profile"
    echo "    profile add|save <name>     - Add current config as a profile"
    echo "    profile set|use|load <name> - Use a profile"
    echo
    echo "  alias|aliases|a [ls|get|set|rm] - Manage Harbor aliases"
    echo "    alias ls|list               - List all aliases"
    echo "    alias get <name>            - Get an alias"
    echo "    alias set <name> <command>  - Set an alias"
    echo "    alias rm|remove <name>      - Remove an alias"
    echo
    echo "  history|h [ls|rm|add]  - Harbor command history."
    echo "                           When run without arguments, launches interactive selector."
    echo "    history clear   - Clear the history"
    echo "    history size    - Get/set the history size"
    echo "    history list|ls - List recorded history"
    echo
    echo "  defaults [ls|rm|add]          - List default services"
    echo "    defaults rm <handle|index>  - Remove, also accepts handle or index"
    echo "    defaults add <handle>       - Add"
    echo
    echo "  volumes [ls|add|rm|clear]     - Manage custom volume mounts for services"
    echo "    volumes ls                  - Show all services with custom volumes"
    echo "    volumes ls <service>        - Show volumes for a specific service"
    echo "    volumes add <svc> <src>:<dest> - Add a volume mount (docker-style notation)"
    echo "    volumes rm <service> <index> - Remove by index"
    echo "    volumes clear <service>     - Remove all custom volumes for a service"
    echo
    echo "  find <file>           - Find a file in the caches visible to Harbor"
    echo "  ls|list [--active|-a] - List available/active Harbor services"
    echo "  ln|link [--short]     - Create a symlink to the CLI, --short for 'h' link"
    echo "  unlink|unln           - Remove CLI symlinks and PATH entries"
    echo "  eject                 - Eject resolved Compose configuration, accepts same options as 'up'"
    echo "  help|--help|-h        - Show this help message"
    echo "  version|--version|-v  - Show the CLI version"
    echo "  gum                   - Run the Gum terminal commands"
    echo "  update [-l|--latest]  - Update Harbor. --latest for the dev version"
    echo "  info                  - Show system information for debug/issues"
    echo "  doctor                - Tiny troubleshooting script"
    echo "  how                   - Ask questions about Harbor CLI, uses mi under the hood"
    echo "  smi                   - Show NVIDIA GPU information"
    echo "  top                   - Run nvtop to monitor GPU usage"
    echo "  size                  - Print the size of caches Harbor is aware of"
    echo "  eval                  - Run promptfoo evaluation"
    echo "  routine               - Run internal Harbor routines"
    echo "  skills [list|get|path]- Agent-readable skill docs shipped with the CLI"
    echo "  completion <shell>    - Generate shell completions (bash, zsh, fish)"
    echo "  dev <script>          - Run Harbor development scripts"
    echo "  tools                 - Run Harbor development tools"
    echo
    echo "Harbor Workspace Commands:"
    echo "  home    - Show path to the Harbor workspace"
    echo "  vscode  - Open Harbor Workspace in VS Code"
    echo "  fixfs   - Fix file ownership for service volumes and caches"
}

run_harbor_doctor() {
    log_info "Running Harbor Doctor..."
    has_errors=false
    local docker_ok=false

    # Check if Docker is installed
    if command -v docker &>/dev/null; then
        log_info "${ok} Docker is installed"

        # Check if Docker can be called without sudo (with timeout to
        # avoid hanging when daemon is starting up or unresponsive)
        local docker_access_output
        if docker_access_output=$(_with_timeout 10 docker info 2>&1); then
            log_info "${ok} Docker can be called without sudo"
            log_info "${ok} Docker daemon is running"
            docker_ok=true
        else
            local exit_code=$?
            if [ "$exit_code" -eq 124 ]; then
                log_error "${nok} Docker daemon is not responding (timed out after 10s). It may still be starting up - try again in a moment."
            elif echo "$docker_access_output" | grep -qi "permission denied\|got permission denied while trying to connect to the docker daemon socket"; then
                log_error "${nok} Docker requires sudo for this user. Add your user to the 'docker' group and re-login."
            else
                log_error "${nok} Docker daemon is not running or not reachable. Please start Docker."
            fi
            has_errors=true
        fi
    else
        log_error "${nok} Docker is not installed. Please install Docker."
        has_errors=true
    fi

    # Only check Compose if Docker itself is working
    if $docker_ok; then
        # Check if Docker Compose (v2) is installed
        if docker compose version &>/dev/null; then
            log_info "${ok} Docker Compose (v2) is installed"
        else
            log_error "${nok} Docker Compose (v2) is not installed. Please install Docker Compose (v2)."
            has_errors=true
        fi

        if ! has_modern_compose; then
            log_error "${nok} Docker Compose version is older than $desired_compose_major.$desired_compose_minor.$desired_compose_patch. Please update Docker Compose (v2)."
            has_errors=true
        else
            log_info "${ok} Docker Compose (v2) version is newer than $desired_compose_major.$desired_compose_minor.$desired_compose_patch"
        fi

        # Check Docker disk space (LLM models are large, disk exhaustion is common)
        local docker_root_dir data_space_gb
        docker_root_dir=$(echo "$docker_access_output" | grep "Docker Root Dir:" | sed 's/.*Docker Root Dir: *//')
        if [ -n "$docker_root_dir" ]; then
            # df -k is POSIX-portable (macOS lacks -BG); convert KB to GB
            data_space_gb=$(df -k "$docker_root_dir" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')
            if [ -n "$data_space_gb" ] && [ "$data_space_gb" -lt 10 ] 2>/dev/null; then
                log_warn "${nok} Low disk space on Docker storage (${data_space_gb}GB free at $docker_root_dir). LLM models are large - consider freeing space or running 'docker system prune'."
            elif [ -n "$data_space_gb" ]; then
                log_info "${ok} Docker storage has ${data_space_gb}GB free"
            fi
        fi
        # Check network/registry connectivity (non-destructive, fast, timeout-guarded)
        log_info "  Checking registry connectivity..."

        # Report proxy config if set (helps debug registry access issues)
        local has_proxy=false
        for proxy_var in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy; do
            if [ -n "${!proxy_var:-}" ]; then
                log_info "  Proxy: $proxy_var=${!proxy_var}"
                has_proxy=true
            fi
        done

        # Use docker manifest inspect on a tiny image to test registry access
        # without pulling or leaving images behind
        local registry_output
        if registry_output=$(_with_timeout 10 docker manifest inspect alpine:latest 2>&1); then
            log_info "${ok} Docker Hub registry is reachable"
        else
            local reg_exit=$?
            if [ "$reg_exit" -eq 124 ]; then
                log_warn "${nok} Registry connectivity check timed out (10s). Possible slow network or proxy issue."
                if $has_proxy; then
                    log_warn "  Proxy is configured - verify proxy settings allow access to registry-1.docker.io"
                fi
            elif echo "$registry_output" | grep -qi "no such host\|could not resolve\|name resolution\|DNS"; then
                log_error "${nok} Cannot resolve Docker Hub (DNS failure). Check your internet connection."
                has_errors=true
            elif echo "$registry_output" | grep -qi "connection refused\|connection timed out\|network is unreachable\|no route to host"; then
                log_error "${nok} Cannot reach Docker Hub (network error). Check your internet connection."
                if $has_proxy; then
                    log_warn "  Proxy is configured - verify proxy settings allow access to registry-1.docker.io"
                fi
                has_errors=true
            elif echo "$registry_output" | grep -qi "403\|forbidden\|denied\|unauthorized\|blocked"; then
                log_warn "${nok} Docker Hub registry access is blocked or denied. A firewall or registry mirror may be interfering."
                if $has_proxy; then
                    log_warn "  Proxy is configured - verify proxy allows access to registry-1.docker.io"
                fi
            else
                log_warn "${nok} Registry connectivity check failed: $(echo "$registry_output" | head -1)"
            fi
        fi
    else
        log_warn "  Skipping Compose, disk, and registry checks (Docker not reachable)"
    fi

    # Check if the Harbor workspace directory exists
    if [ -d "$harbor_home" ]; then
        log_info "${ok} Harbor home: $harbor_home"
    else
        log_error "${nok} Harbor home does not exist or is not reachable at: $harbor_home"
        log_error "  Reinstall Harbor or set HARBOR_HOME to the correct path."
        has_errors=true
    fi

    # WSL-specific diagnostics
    if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null || [ -n "${WSL_INTEROP:-}" ]; then
        local wsl_ver="unknown"
        if [ -n "${WSL_INTEROP:-}" ] || grep -qi "microsoft-standard\|microsoft-WSL2" /proc/version 2>/dev/null; then
            wsl_ver="2"
        else
            wsl_ver="1"
        fi
        log_info "${ok} WSL${wsl_ver} environment detected"

        if [ "$wsl_ver" = "1" ]; then
            log_error "${nok} WSL1 does not support Docker natively. Upgrade to WSL2: wsl --set-version <distro> 2"
            has_errors=true
        fi

        # Warn if harbor_home is on a Windows-mounted filesystem (slow IO)
        local home_mount
        home_mount=$(df -P "$harbor_home" 2>/dev/null | awk 'NR==2 {print $6}')
        if [ -n "$home_mount" ] && echo "$home_mount" | grep -q "^/mnt/[a-zA-Z]"; then
            log_warn "${nok} Harbor home is on a Windows filesystem ($home_mount). File operations will be slow. Consider moving to the Linux filesystem."
        fi
    fi

    # SELinux diagnostics (Fedora, RHEL, CentOS, Rocky, Alma)
    if command -v getenforce &>/dev/null || [ -f /sys/fs/selinux/enforce ]; then
        local selinux_mode="unknown"
        if command -v getenforce &>/dev/null; then
            selinux_mode=$(getenforce 2>/dev/null || echo "unknown")
        elif [ -f /sys/fs/selinux/enforce ]; then
            local enforce_val
            enforce_val=$(cat /sys/fs/selinux/enforce 2>/dev/null)
            case "$enforce_val" in
                1) selinux_mode="Enforcing" ;;
                0) selinux_mode="Permissive" ;;
                *) selinux_mode="unknown" ;;
            esac
        fi

        if [ "$selinux_mode" = "Enforcing" ]; then
            log_warn "${nok} SELinux is Enforcing. Docker bind mounts may be denied silently."
            log_warn "  Harbor compose files do not use :z/:Z volume labels."
            log_warn "  If containers report 'Permission denied' on mounted files, consider:"
            log_warn "    1. Install container-selinux: sudo dnf install -y container-selinux"
            log_warn "    2. Check for recent denials: sudo ausearch -m avc -ts recent --comm docker 2>/dev/null"
            log_warn "    3. As a last resort: sudo setenforce 0 (temporary, resets on reboot)"

            # Check if container-selinux is installed (provides base policies for containers)
            if command -v rpm &>/dev/null; then
                if rpm -q container-selinux &>/dev/null; then
                    log_info "${ok} container-selinux is installed"
                else
                    log_warn "${nok} container-selinux is not installed. Install it: sudo dnf install -y container-selinux"
                fi
            fi

            # Check for recent Docker AVC denials (non-destructive, fast)
            if command -v ausearch &>/dev/null; then
                local avc_count
                avc_count=$(ausearch -m avc -ts recent --comm docker 2>/dev/null | grep -c "^type=AVC" 2>/dev/null || echo "0")
                if [ "$avc_count" -gt 0 ] 2>/dev/null; then
                    log_warn "${nok} Found ${avc_count} recent SELinux AVC denial(s) for Docker."
                    log_warn "  Run 'sudo ausearch -m avc -ts recent --comm docker' for details."
                    log_warn "  Run 'sudo sealert -a /var/log/audit/audit.log' for human-readable explanations (if setroubleshoot is installed)."
                fi
            fi
        elif [ "$selinux_mode" = "Permissive" ]; then
            log_info "${ok} SELinux is Permissive (not blocking Docker)"
        elif [ "$selinux_mode" = "Disabled" ]; then
            log_info "${ok} SELinux is Disabled"
        else
            log_info "  SELinux status: ${selinux_mode}"
        fi
    fi

    # Fedora/RHEL-specific Docker guidance
    if [ -f /etc/os-release ]; then
        local doctor_distro_id
        doctor_distro_id=$(awk -F= '/^ID=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
        case "$doctor_distro_id" in
            fedora|rhel|centos|rocky|almalinux)
                # Check if using moby-engine instead of docker-ce (common misconfiguration on Fedora)
                if $docker_ok && command -v rpm &>/dev/null; then
                    if rpm -q moby-engine &>/dev/null && ! rpm -q docker-ce &>/dev/null; then
                        log_warn "  Using moby-engine instead of docker-ce. moby-engine was removed from Fedora 39+."
                        log_warn "  For better compatibility, switch to Docker's official packages:"
                        case "$doctor_distro_id" in
                            centos)
                                log_warn "    https://docs.docker.com/engine/install/centos/"
                                ;;
                            rhel|rocky|almalinux)
                                log_warn "    https://docs.docker.com/engine/install/rhel/"
                                ;;
                            *)
                                log_warn "    https://docs.docker.com/engine/install/fedora/"
                                ;;
                        esac
                    fi
                fi

                # Detect immutable variants
                local doctor_variant
                doctor_variant=$(awk -F= '/^VARIANT_ID=/{gsub(/"/,"",$2); print tolower($2)}' /etc/os-release)
                case "${doctor_variant:-}" in
                    silverblue|kinoite|sericea|onyx|coreos|iot)
                        log_info "  Immutable OS variant detected: ${doctor_variant}"
                        log_info "  Standard dnf install will not work. Use rpm-ostree or Toolbox."
                        ;;
                esac
                ;;
        esac
    fi

    # Check if the default profile file exists and is readable
    if [ -f "$default_profile" ] && [ -r "$default_profile" ]; then
        log_info "${ok} Default profile exists and is readable"
    else
        log_error "${nok} Default profile is missing or not readable at: $default_profile"
        log_error "  This usually means the Harbor installation is incomplete. Try reinstalling: curl -fsSL https://raw.githubusercontent.com/av/harbor/main/install.sh | bash"
        has_errors=true
    fi

    # Check if the .env file exists and is readable
    if [ -f ".env" ] && [ -r ".env" ]; then
        log_info "${ok} Current profile (.env) exists and is readable"
    else
        log_error "${nok} Current profile (.env) is missing or not readable."
        log_error "  Run 'harbor config update' to regenerate it from the default profile."
        has_errors=true
    fi

    # Check if CLI is linked and symlink target is valid
    local cli_path cli_name
    cli_path=$(env_manager get cli.path)
    cli_name=$(env_manager get cli.name)
    cli_path="${cli_path/#\~/$HOME}"
    if [ -L "$cli_path/$cli_name" ]; then
        local link_target
        link_target=$(readlink "$cli_path/$cli_name")
        if [ -f "$cli_path/$cli_name" ]; then
            log_info "${ok} CLI is linked"
        else
            log_error "${nok} CLI symlink is broken: $cli_path/$cli_name -> $link_target"
            log_error "    The target no longer exists. Run 'harbor link' to recreate."
            has_errors=true
        fi
    else
        log_error "${nok} CLI is not linked. Run 'harbor link' to create a symlink."
        has_errors=true
    fi

    # GPU checks: only show results for hardware that is actually present,
    # to avoid noisy warnings on systems without discrete GPUs
    if has_nvidia; then
        log_info "${ok} NVIDIA GPU detected"
        if has_nvidia_ctk; then
            log_info "${ok} NVIDIA Container Toolkit is installed"
        else
            log_warn "${nok} NVIDIA Container Toolkit is not installed. GPU containers won't be able to access the GPU. Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
            has_errors=true
        fi
    fi

    if has_rocm; then
        log_info "${ok} AMD GPU with ROCm support detected"
    elif [[ -e "/dev/kfd" ]]; then
        log_warn "${nok} AMD GPU hardware found (/dev/kfd) but ROCm support is incomplete. Check that amdgpu kernel module is loaded and /dev/dri/renderD* devices exist."
    fi

    if $has_errors; then
        log_error "Harbor Doctor checks failed. Please resolve the issues above."
        return 1
    else
        log_info "Harbor Doctor checks completed successfully."
        return 0
    fi
}

has_nvidia() {
    command -v nvidia-smi &>/dev/null
}

has_nvidia_ctk() {
    command -v nvidia-ctk &>/dev/null || command -v nvidia-container-toolkit &>/dev/null
}

has_nvidia_cdi() {
    # Check if nvidia.yaml is present in either
    # /etc/cdi or /var/run/cdi
    if [ -f /etc/cdi/nvidia.yaml ] || [ -f /var/run/cdi/nvidia.yaml ] || [ -f /var/run/cdi/nvidia-container-toolkit.json ]; then
        return 0
    else
        return 1
    fi
}

has_rocm() {
    # 1. Hardware check - /dev/kfd is the AMD GPU compute interface
    [[ -e "/dev/kfd" ]] || return 1

    # 2. Verify render nodes exist (needed for container device passthrough)
    ls /dev/dri/renderD* &>/dev/null || return 1

    # 3. Verify amdgpu kernel module is loaded
    lsmod 2>/dev/null | grep -q "^amdgpu " || return 1

    return 0
}

has_modern_compose() {
    local compose_version_raw
    compose_version_raw=$(docker compose version --short 2>/dev/null | sed -e 's/-desktop//')

    if [ -z "$compose_version_raw" ]; then
        log_debug "Could not detect Docker Compose version"
        return 1
    fi

    local compose_version=${compose_version_raw#v}
    if [ "$compose_version" = "dev" ]; then
        log_debug "Docker Compose reports version 'dev'; assuming it is modern"
        return 0
    fi

    local major_version minor_version patch_version
    if [[ "$compose_version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
        major_version=${BASH_REMATCH[1]}
        minor_version=${BASH_REMATCH[2]}
        patch_version=${BASH_REMATCH[3]}
    else
        log_debug "Unrecognized Docker Compose version '$compose_version_raw'; skipping numeric comparison"
        return 0
    fi

    if ((major_version > desired_compose_major)); then
        return 0
    elif ((major_version < desired_compose_major)); then
        log_debug "Major version is less than $desired_compose_major"
        return 1
    fi

    if ((minor_version > desired_compose_minor)); then
        return 0
    elif ((minor_version < desired_compose_minor)); then
        log_debug "Minor version is less than $desired_compose_minor"
        return 1
    fi

    if ((patch_version < desired_compose_patch)); then
        log_debug "Patch version is less than $desired_compose_patch"
        return 1
    fi

    return 0
}

# shellcheck disable=SC2034
__anchor_fns=true

harbor_upper() {
    LC_ALL=C printf '%s' "$1" | tr 'a-z' 'A-Z'
}

harbor_lower() {
    LC_ALL=C printf '%s' "$1" | tr 'A-Z' 'a-z'
}

resolve_compose_files() {
    # Find all .yml files in the services directory,
    # but do not go into subdirectories
    find "$harbor_home/services" -maxdepth 1 -name "*.yml" |
        # For each file, count the number of dots in the filename
        # and prepend this count to the filename
        awk -F. '{print NF-1, $0}' |
        # Sort by dot count (primary) then alphabetically (secondary)
        # to ensure deterministic order across filesystems
        sort -n -k1,1 -k2 |
        # Remove the dot count, leaving
        # just the sorted filenames
        cut -d' ' -f2-
}

run_routine() {
    local routine_name="$1"

    if [ -z "$routine_name" ]; then
        log_error "Usage: harbor routine <name>"
        log_error "Run 'ls $harbor_home/routines/' to see available routines."
        return 1
    fi

    if [[ "$routine_name" == *.* ]]; then
        local routine_path="$harbor_home/routines/$routine_name"
    else
        local routine_path="$harbor_home/routines/$routine_name.ts"
    fi

    if [ ! -f $routine_path ]; then
        log_error "Routine '$routine_name' not found at $routine_path"
        log_error "Run 'ls $harbor_home/routines/' to see available routines."
        return 1
    fi

    shift

    log_debug "Running routine: $routine_name"
    docker run --rm \
        -v "$harbor_home:$harbor_home" \
        -v harbor-deno-cache:/deno-dir:rw \
        -w "$harbor_home" \
        -e "HARBOR_LOG_LEVEL=$default_log_level" \
        -e "HARBOR_COMPOSE_CACHE=$HARBOR_COMPOSE_CACHE" \
        $default_routine_runtime \
        $routine_path "$@"
}

routine_compose_with_options() {
    local options=()

    if [ "$default_auto_capabilities" = "true" ]; then
        if has_nvidia && has_nvidia_ctk; then
            options+=("nvidia")
        elif has_nvidia_cdi; then
            options+=("cdi")
        fi

        if has_rocm; then
            options+=("rocm")
        fi

        if has_modern_compose; then
            options+=("mdc")
        fi
    fi

    local cmd
    cmd=$(run_routine mergeComposeFiles "$@" "${options[@]}")
    if [ -z "$cmd" ]; then
        log_error "Failed to resolve compose configuration."
        log_error "The compose file merge routine produced no output."
        log_error "Try 'harbor doctor' to diagnose, or set 'harbor config set legacy.cli true' to use the legacy compose resolver."
        return 1
    fi
    echo "$cmd"
}

compose_with_options() {
    if [[ $default_legacy_cli == 'false' ]]; then
        routine_compose_with_options "$@"
        return
    fi

    local base_dir="$harbor_home"
    local compose_files=("$base_dir/compose.yml") # Always include the base compose file
    local options=("${default_options[@]}" "${default_capabilities[@]}")

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
        --dir=*)
            base_dir="${1#*=}"
            shift
            ;;
        --no-defaults)
            options=()
            shift
            ;;
        --no-merge)
            # No-op in legacy mode (files are never merged)
            shift
            ;;
        *)
            options+=("$1")
            shift
            ;;
        esac
    done

    if [ "$default_auto_capabilities" = "true" ]; then
        if has_nvidia && has_nvidia_ctk; then
            options+=("nvidia")
        elif has_nvidia_cdi; then
            options+=("cdi")
        fi

        if has_rocm; then
            options+=("rocm")
        fi

        if has_modern_compose; then
            options+=("mdc")
        fi
    fi

    for file in $(resolve_compose_files); do
        if [ -f "$file" ]; then
            local filename=$(basename "$file")
            local match=false

            # This is a "cross" file, only to be included
            # if we're running all the mentioned services
            if [[ $filename == *".x."* ]]; then
                local cross="${filename#compose.x.}"
                cross="${cross%.yml}"

                # Convert dot notation to array
                local filename_parts=(${cross//./ })
                local all_matched=true

                for part in "${filename_parts[@]}"; do
                    # Skip capability files for wildcard match
                    if is_capability "$part"; then
                        # Capabilities must match exactly, no wildcards
                        if [[ ! " ${options[*]} " =~ " ${part} " ]]; then
                            all_matched=false
                            break
                        fi
                    else
                        if [[ ! " ${options[*]} " =~ " ${part} " ]] && [[ ! " ${options[*]} " =~ " * " ]]; then
                            all_matched=false
                            break
                        fi
                    fi
                done

                if $all_matched; then
                    compose_files+=("$file")
                fi

                # Either way, the processing
                # for this file is done
                continue
            fi

            # Check if file matches any of the options
            for option in "${options[@]}"; do
                if [[ $option == "*" ]]; then
                    # Capabilities should not be matched by "*", otherwise
                    # we'll run "nvidia" or "mdc" or "cdi" when we don't want to
                    if ! is_capability_file "$filename"; then
                        match=true
                    fi
                    break
                fi

                if [[ $filename == *".$option."* ]]; then
                    match=true
                    break
                fi
            done

            if $match; then
                compose_files+=("$file")
            fi
        fi
    done

    # Prepare docker compose command
    local cmd="docker compose"
    for file in "${compose_files[@]}"; do
        cmd+=" -f $file"
    done

    # Log amount of matched files
    log_debug "Matched compose files: ${#compose_files[@]}"

    # Return the command string
    echo "$cmd"
}

is_capability() {
    local capability="$1"
    local capabilities=("nvidia" "mdc" "cdi" "rocm" "build" "${default_capabilities[@]}")

    for cap in "${capabilities[@]}"; do
        if [ "$cap" = "$capability" ]; then
            return 0
        fi
    done

    return 1
}

is_capability_file() {
    local filename="$1"
    local capabilities=("nvidia" "mdc" "cdi" "rocm" "build" "${default_capabilities[@]}")

    for cap in "${capabilities[@]}"; do
        if [[ $filename == *".$cap."* ]]; then
            return 0
        fi
    done

    return 1
}

service_compose_exists() {
    local service="$1"
    local services_dir="${2:-$harbor_home/services}"

    if [ -f "$services_dir/compose.$service.yml" ] || [ -f "$services_dir/compose.$service.ts" ]; then
        return 0
    fi

    if compgen -G "$services_dir/compose.$service.*.yml" >/dev/null || compgen -G "$services_dir/compose.$service.*.ts" >/dev/null; then
        return 0
    fi

    return 1
}

resolve_compose_command() {
    local is_human=false

    case "$1" in
    --human | -h)
        shift
        is_human=true
        ;;
    esac

    for arg in "$@"; do
        if [[ "$arg" == --* ]]; then
            continue
        fi
        if ! is_capability "$arg" && ! service_compose_exists "$arg"; then
            log_error "Service '$arg' not found."
            return 1
        fi
    done

    local cmd
    cmd=$(compose_with_options --no-merge "$@") || return 1

    if $is_human; then
        # Replace -f <harbor_home>/ with newline + " - " for readability.
        # Use awk instead of sed for portable newline handling (BSD sed
        # does not interpret \n in replacement strings).
        local pattern="-f $harbor_home/"
        echo "$cmd" | awk -v pat="$pattern" -v rep=" - " '{
            while ((idx = index($0, pat)) > 0) {
                printf "%s\n%s", substr($0, 1, idx-1), rep
                $0 = substr($0, idx + length(pat))
            }
            print
        }'
    else
        echo "$cmd"
    fi
}

run_up() {
    _check_docker || return 1
    local should_tail=false
    local should_open=false
    local should_attach=false
    local no_defaults=false
    local skip_port_check=false
    local filtered_args=()
    local up_args=()

    for arg in "$@"; do
        case "$arg" in
        --no-defaults)
            no_defaults=true
            up_args+=("$arg")
            ;;
        --open | -o)
            should_open=true
            ;;
        --tail | -t)
            should_tail=true
            ;;
        --attach | -a)
            should_attach=true
            ;;
        --skip-port-check)
            skip_port_check=true
            ;;
        *)
            filtered_args+=("$arg")
            ;;
        esac
    done

    local display_services=("${filtered_args[@]}")
    if [ ${#display_services[@]} -eq 0 ] && ! $no_defaults; then
        display_services=("${default_options[@]}")
    fi

    # Verify that requested services exist
    for service in "${filtered_args[@]}"; do
        if is_capability "$service"; then
            continue
        fi
        if ! service_compose_exists "$service"; then
            log_error "Service '$service' not found."
            local suggestion
            suggestion=$(_suggest_service "$service")
            if [ -n "$suggestion" ]; then
                log_info "Did you mean: ${c_g}$suggestion${c_nc}?"
            fi
            log_info "Run 'harbor ls' to see available services."
            return 1
        fi
    done

    # Validate default services (may be stale after uninstalling or renaming services)
    if [ ${#filtered_args[@]} -eq 0 ] && ! $no_defaults; then
        local valid_defaults=()
        for service in "${default_options[@]}"; do
            if is_capability "$service" || service_compose_exists "$service"; then
                valid_defaults+=("$service")
            else
                log_warn "Default service '$service' no longer exists, skipping. Remove it with: harbor defaults rm $service"
            fi
        done
        display_services=("${valid_defaults[@]}")
        # Update the global so compose_with_options sees validated defaults
        default_options=("${valid_defaults[@]}")
    fi

    if [ ${#display_services[@]} -gt 0 ]; then
        log_info "Starting services: ${display_services[*]}"
    else
        log_warn "No services specified. Set defaults with 'harbor defaults add <service>' or specify services: 'harbor up <service>'"
        log_info "Run 'harbor ls' to see available services."
        return 0
    fi

    log_debug "Running 'up' for services: ${up_args[*]} ${filtered_args[*]}"
    for service in "${display_services[@]}"; do
        case "$service" in
        dmr)
            run_dmr_command start
            ;;
        mlx)
            run_mlx_command start
            ;;
        omlx)
            run_omlx_command start
            ;;
        esac
    done

    # Pre-check for port conflicts before starting services
    if ! $skip_port_check; then
        if ! _check_port_conflicts "${up_args[@]}" "${filtered_args[@]}"; then
            return 1
        fi
    fi

    $(compose_with_options "${up_args[@]}" "${filtered_args[@]}") up -d --wait
    local up_exit=$?

    if [ $up_exit -ne 0 ]; then
        log_error "Failed to start services."
        log_error "Run 'docker compose logs' in $harbor_home to see container errors."
        log_error "Common causes: port conflicts, missing images, or insufficient disk space."
        return $up_exit
    fi

    for service in "${display_services[@]}"; do
        local url
        if url=$(get_service_url "$service" 2>/dev/null); then
            log_info "  ${c_g}${service}${c_nc} - $url"
        else
            log_info "  ${c_g}${service}${c_nc}"
        fi
    done

    if [ "$default_autoopen" = "true" ]; then
        run_open "$default_open"
    fi

    for service in "${default_tunnels[@]}"; do
        establish_tunnel "$service"
    done

    if $should_attach; then
        run_attach "$filtered_args"
        return
    fi

    if $should_tail; then
        run_logs "$filtered_args"
    fi

    if $should_open; then
        run_open "$filtered_args"
    fi
}

run_down() {
    _check_docker || return 1
    local services=$(get_active_services)
    local matched_services=()
    local compose_targets=("$@")
    local requested_services=()
    local stop_dmr=false
    local stop_mlx=false
    local stop_omlx=false

    log_debug "Active services: $services"

    for service in "$@"; do
        case "$service" in
        --*)
            ;;
        dmr)
            stop_dmr=true
            requested_services+=("$service")
            ;;
        mlx)
            stop_mlx=true
            requested_services+=("$service")
            ;;
        omlx)
            stop_omlx=true
            requested_services+=("$service")
            ;;
        *)
            requested_services+=("$service")
            ;;
        esac
    done

    if [ ${#requested_services[@]} -eq 0 ]; then
        if echo "$services" | grep -q '\bdmr\b'; then
            stop_dmr=true
        fi
        if echo "$services" | grep -q '\bmlx\b'; then
            stop_mlx=true
        fi
        if echo "$services" | grep -q '\bomlx\b'; then
            stop_omlx=true
        fi
    fi

    # Sibling-finder uses raw active containers (not the compose-file-filtered
    # list) so companion services defined inside the same compose file —
    # e.g. beszel-agent, beszel-agent-init, dify-api, langfuse-worker — get
    # torn down with their parent. Without this, `harbor down beszel` only
    # stops the hub and leaves the docker.sock-mounted agent running.
    local raw_services=$(docker compose ps -a --format "{{.Service}}")
    for service in "$@"; do
        log_debug "Checking if service '$service' has companions running..."
        matched_service=$(echo "$raw_services" | grep "^$service-" || true)
        if [ -n "$matched_service" ]; then
            matched_services+=($matched_service)
        fi
    done

    log_debug "Matched: ${matched_services[*]}"

    if [ $# -eq 0 ]; then
        log_info "Stopping all services..."
        compose_targets=("*")
    else
        log_info "Stopping services: $*"
    fi

    if $stop_mlx; then
        run_mlx_command stop || true
    fi
    if $stop_omlx; then
        run_omlx_command stop || true
    fi
    if $stop_dmr; then
        run_dmr_command stop || true
    fi

    matched_services_str=$(printf " %s" "${matched_services[@]}")
    $(compose_with_options "${compose_targets[@]}") down --remove-orphans --timeout 10 "$@" $matched_services_str
    local down_exit=$?

    if [ $down_exit -eq 0 ]; then
        log_info "Services stopped."
    else
        log_error "Failed to stop services. Some containers may still be running."
        log_error "Try 'docker ps' to see what is still running, or 'docker compose down --force' to force stop."
        return $down_exit
    fi
}

run_restart() {
    _check_docker || return 1
    local active_services=$(get_active_services)

    if [ -z "$active_services" ] && [ $# -eq 0 ]; then
        log_warn "No active services to restart. Start services first with 'harbor up <service>'."
        return 0
    fi

    local services=()
    local flags=()

    for arg in "$@"; do
        if [[ "$arg" == -* ]]; then
            flags+=("$arg")
        else
            services+=("$arg")
        fi
    done

    local unique_services=()
    local all_services=($active_services "${services[@]}")

    for s in "${all_services[@]}"; do
        local is_seen=0
        for u in "${unique_services[@]}"; do
            if [[ "$s" == "$u" ]]; then
                is_seen=1
                break
            fi
        done
        if (( ! is_seen )); then
            unique_services+=("$s")
        fi
    done

    run_down "${services[@]}"
    run_up "${unique_services[@]}" "${flags[@]}"
}

run_ps() {
    _check_docker || return 1
    local compose_targets=("$@")

    if [ $# -eq 0 ]; then
        compose_targets=("*")
    fi

    $(compose_with_options "${compose_targets[@]}") ps "$@"
}

run_build() {
    _check_docker || return 1
    service=$1
    shift

    if [ -z "$service" ]; then
        log_error "Usage: harbor build <service>"
        return 1
    fi

    local services=$(get_services --silent)

    log_debug "Checking if service '$service' has subservices..."
    matched_service=$(echo "$services" | grep "^$service-")
    if [ -n "$matched_service" ]; then
        log_debug "Matched service: $matched_service"
        matched_services+=("$matched_service")
    fi

    matched_services_str=$(printf " %s" "${matched_services[@]}")
    log_debug "Building" "$service" "$@" $matched_services_str
    $(compose_with_options "*") build "$service" "$@" $matched_services_str
}

run_shell() {
    _check_docker || return 1
    service=$1
    shift

    if [ -z "$service" ]; then
        log_error "Usage: harbor shell <service>"
        exit 1
    fi

    local shell="bash"

    if [ -n "$1" ]; then
        shell="$1"
    fi

    $(compose_with_options "*") run -it --entrypoint "$shell" "$service"
}

run_logs() {
    _check_docker || return 1
    $(compose_with_options "*") logs -n 20 -f "$@"
}

run_pull() {
    _check_docker || return 1
    available_services=$(get_services --silent)

    for service in "$@"; do
        if echo "$available_services" | grep -q "^$service$"; then
            log_info "Pulling service $service"
        else
            run_models_pull "$service"
            return 0
        fi
    done

    $(compose_with_options "$@") pull
}

shell_single_quote() {
    printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

llamacpp_pull_model_args() {
    local model="$1"

    case "$model" in
    https://huggingface.co/*/blob/main/*.gguf)
        local decomposed
        local repo_name
        local file_specifier

        decomposed=$(parse_hf_url "$model")
        repo_name=$(echo "$decomposed" | cut -d"$delimiter" -f1)
        file_specifier=$(echo "$decomposed" | cut -d"$delimiter" -f2)

        if [ -z "$repo_name" ] || [ -z "$file_specifier" ] || [ "$repo_name" = "$model" ]; then
            log_error "Unable to parse Hugging Face GGUF URL: $model"
            return 1
        fi

        printf -- "--hf-repo %s --hf-file %s" \
            "$(shell_single_quote "$repo_name")" \
            "$(shell_single_quote "$file_specifier")"
        ;;
    *)
        printf -- "-hf %s" "$(shell_single_quote "$model")"
        ;;
    esac
}

run_llamacpp_pull() {
    local model="$1"
    log_info "Detected Llama.cpp target: $model"
    log_info "Starting ephemeral llama-server to pull model to cache..."

    local model_args
    model_args=$(llamacpp_pull_model_args "$model") || return 1

    local safe_model_name=$(echo "$model" | sed 's/[^a-zA-Z0-9._-]/-/g')
    local c_log="/tmp/pull-${safe_model_name}.log"

    # Embed simple logger to match Harbor's CLI style inside the container
    # Using printf for better portability and avoiding echo -e issues
    local script_logger="
    log_info() {
        printf \"\\033[90m%s\\033[0m [INFO] %s\\n\" \"\$(date +'%H:%M:%S')\" \"\$*\"
    }
    log_success() {
        printf \"\\033[90m%s\\033[0m [INFO] \\033[32m✔\\033[0m %s\\n\" \"\$(date +'%H:%M:%S')\" \"\$*\"
    }
    log_error() {
        printf \"\\033[90m%s\\033[0m [ERROR] \\033[31m✘\\033[0m %s\\n\" \"\$(date +'%H:%M:%S')\" \"\$*\"
    }
    "

    local cmd="
    $script_logger

    touch \"$c_log\"
    tail -f \"$c_log\" &
    TAIL_PID=\$!

    log_info 'Starting download process for $model...' >> \"$c_log\"

    /app/llama-server $model_args --port 8080 --host 0.0.0.0 --n-gpu-layers 0 -c 128 >> \"$c_log\" 2>&1 &
    SRV_PID=\$!

    while true; do
        if grep -q 'using cached file' \"$c_log\"; then
            log_success 'Model is already cached.'
            kill \$SRV_PID 2>/dev/null
            kill \$TAIL_PID 2>/dev/null
            exit 0
        fi

        # 'loading model' indicates download finished
        if grep -q 'main: loading model' \"$c_log\" || grep -q 'load_model: loading model' \"$c_log\"; then
            log_success 'Download completed successfully.'
            kill \$SRV_PID 2>/dev/null
            kill \$TAIL_PID 2>/dev/null
            exit 0
        fi

        # Fallback success
        if grep -q 'HTTP server listening' \"$c_log\"; then
            log_success 'Server ready (Download success).'
            kill \$SRV_PID 2>/dev/null
            kill \$TAIL_PID 2>/dev/null
            exit 0
        fi

        if ! kill -0 \$SRV_PID 2>/dev/null; then
            log_error 'Download process exited prematurely. Check logs above.'
            kill \$TAIL_PID 2>/dev/null
            exit 1
        fi
        sleep 0.5
    done
    "

    $(compose_with_options "llamacpp") run \
        --rm \
        --entrypoint /bin/sh \
        llamacpp \
        -c "$cmd"
}

run_run() {
    _check_docker || return 1
    service=$1
    shift

    # Check if it is an alias first
    local maybe_cmd=$(env_manager_dict aliases --silent get "$service")

    if [ -n "$maybe_cmd" ]; then
        log_info "Running alias $service -> \"$maybe_cmd\""
        eval "$maybe_cmd"
        return 0
    fi

    log_debug "'harbor run': no alias found for $service, running as service"
    local services=$(get_active_services)
    
    local tty_opt=""
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        tty_opt="-T"
    fi
    
    $(compose_with_options $services "$service") run $tty_opt --rm "$service" "$@"
}

launch_backend_is_supported() {
    case "$1" in
    ollama | llamacpp | ikllamacpp | vllm | dmr | mlx | omlx | tabbyapi | mistralrs | sglang | lmdeploy | aphrodite | ktransformers | unsloth-studio)
        return 0
        ;;
    *)
        return 1
        ;;
    esac
}

launch_backend_model_key() {
    case "$1" in
    ollama)
        echo "ollama.default.models"
        ;;
    llamacpp)
        echo "llamacpp.model"
        ;;
    ikllamacpp)
        echo "ikllamacpp.model"
        ;;
    vllm)
        echo "vllm.model"
        ;;
    dmr)
        echo "dmr.model"
        ;;
    mlx)
        echo "mlx.model"
        ;;
    omlx)
        echo "omlx.model"
        ;;
    tabbyapi)
        echo "tabbyapi.model"
        ;;
    mistralrs)
        echo "mistralrs.model"
        ;;
    sglang)
        echo "sglang.model"
        ;;
    aphrodite)
        echo "aphrodite.model"
        ;;
    ktransformers)
        echo "ktransformers.model"
        ;;
    *)
        return 1
        ;;
    esac
}

launch_backend_api_key() {
    local backend="$1"
    local key=""

    case "$backend" in
    omlx)
        key=$(env_manager --silent get omlx.api.key 2>/dev/null || true)
        ;;
    dmr)
        key=$(env_manager --silent get dmr.api.key 2>/dev/null || true)
        ;;
    esac

    if [ -n "$key" ]; then
        echo "$key"
        return 0
    fi

    return 1
}

launch_curl_with_auth() {
    local backend="$1"
    shift
    local api_key

    if api_key=$(launch_backend_api_key "$backend"); then
        curl -H "Authorization: Bearer $api_key" "$@"
    else
        curl "$@"
    fi
}

launch_url_with_v1() {
    local url="${1%/}"

    case "$url" in
    */v1)
        echo "$url"
        ;;
    *)
        echo "$url/v1"
        ;;
    esac
}

launch_backend_url() {
    local backend="$1"

    if ! launch_backend_is_supported "$backend"; then
        return 1
    fi

    get_url "$backend" 2>/dev/null
}

launch_backend_is_reachable() {
    local backend="$1"
    local url

    if ! url=$(launch_backend_url "$backend"); then
        return 1
    fi

    launch_curl_with_auth "$backend" -fsS --max-time 2 "$(launch_url_with_v1 "$url")/models" >/dev/null 2>&1
}

launch_start_services() {
    if [ "$#" -eq 0 ]; then
        return 0
    fi

    log_info "Starting services: $*"
    run_up --no-defaults "$@"
}

launch_supported_backends() {
    echo "ollama llamacpp ikllamacpp vllm dmr mlx omlx tabbyapi mistralrs sglang lmdeploy aphrodite ktransformers unsloth-studio"
}

launch_supported_host_tools() {
    echo "claude codex copilot droid hermes mi openclaw opencode pi pool vscode"
}

launch_supported_service_cli_handles() {
    echo "aider aichat cmdh fabric facts gptme nanobot nexa npcsh openhands oh opint interpreter plandex pdx promptfoo pf repopack tokscale"
}

launch_detect_backend() {
    local explicit_backend="$1"
    local backend
    local url
    local running_backends=()

    if [ -n "$explicit_backend" ]; then
        if ! launch_backend_is_supported "$explicit_backend"; then
            log_error "Unsupported launch backend '$explicit_backend'."
            log_info "Supported launch backends: $(launch_supported_backends)"
            return 1
        fi

        if ! is_service_running "$explicit_backend"; then
            log_info "Backend '$explicit_backend' is not running; starting it..."
            launch_start_services "$explicit_backend" || return 1
        fi

        if ! url=$(launch_backend_url "$explicit_backend"); then
            log_error "Could not resolve a host URL for backend '$explicit_backend'."
            log_info "Check the backend's published port with: harbor ps"
            return 1
        fi

        if ! launch_curl_with_auth "$explicit_backend" -fsS --max-time 2 "$(launch_url_with_v1 "$url")/models" >/dev/null 2>&1; then
            log_error "Backend '$explicit_backend' is running, but its OpenAI-compatible endpoint is not reachable at $(launch_url_with_v1 "$url")/models."
            log_info "Wait for the backend to finish loading, check its container health with: harbor ps, then retry."
            return 1
        fi

        echo "$explicit_backend"
        return 0
    fi

    for backend in $(launch_supported_backends); do
        if is_service_running "$backend" && launch_backend_is_reachable "$backend"; then
            echo "$backend"
            return 0
        fi

        if is_service_running "$backend"; then
            running_backends+=("$backend")
        fi
    done

    if [ ${#running_backends[@]} -gt 0 ]; then
        log_error "Running Harbor launch backend(s) are not reachable via /v1/models: ${running_backends[*]}"
        log_info "Wait for them to finish loading, check container health with: harbor ps, then retry."
        return 1
    fi

    log_info "No running Harbor OpenAI-compatible backend found; starting llamacpp..."
    launch_start_services llamacpp || return 1

    if launch_backend_is_reachable llamacpp; then
        echo "llamacpp"
        return 0
    fi

    log_error "Started llamacpp, but its OpenAI-compatible endpoint is not reachable at $(launch_url_with_v1 "$(launch_backend_url llamacpp)")/models."
    log_info "Wait for llamacpp to finish loading, check its container health with: harbor ps, then retry."
    return 1
}

launch_backend_configured_model() {
    local backend="$1"
    local key
    local value

    if ! key=$(launch_backend_model_key "$backend"); then
        return 1
    fi

    value=$(env_manager --silent get "$key" 2>/dev/null || true)
    value=$(echo "$value" | tr ';, ' '\n' | awk 'NF { print; exit }')

    if [ -n "$value" ] && [ "$value" != "auto" ]; then
        echo "$value"
        return 0
    fi

    return 1
}

launch_model_from_models_response() {
    local response="$1"
    local model

    model=$(launch_models_from_models_response "$response" | awk 'NF { print; exit }')
    if [ -n "$model" ] && [ "$model" != "null" ]; then
        echo "$model"
        return 0
    fi

    return 3
}

launch_models_from_models_response() {
    local response="$1"

    if ! command -v jq >/dev/null 2>&1; then
        return 4
    fi

    if ! printf '%s' "$response" | jq -e '
        (type == "object" and (
            (has("data") and (.data | type == "array")) or
            (has("models") and (.models | type == "array"))
        )) or
        type == "array"
    ' >/dev/null 2>&1; then
        return 2
    fi

    printf '%s' "$response" | jq -r '
        def model_id:
            if type == "string" then
                .
            elif type == "object" then
                .id // .name // .model // .root // empty
            else
                empty
            end;

        if type == "object" and (.data | type == "array") then
            .data[]? | model_id
        elif type == "object" and (.models | type == "array") then
            .models[]? | model_id
        elif type == "array" then
            .[]? | model_id
        else
            empty
        end
    ' 2>/dev/null | awk 'NF && $0 != "null" && !seen[$0]++ { print }'

    if [ "${PIPESTATUS[1]}" -ne 0 ]; then
        return 2
    fi

    return 0
}

launch_discover_models() {
    local backend="$1"
    local api_url="$2"
    local response
    local models
    local model
    local parse_rc

    if ! response=$(launch_curl_with_auth "$backend" -fsS --max-time 3 "$api_url/models" 2>/dev/null); then
        log_error "Could not read models from backend '$backend' at $api_url/models."
        log_info "Wait for the backend to finish loading, or pass a known model explicitly with --model <model>."
        return 1
    fi

    models=$(launch_models_from_models_response "$response")
    parse_rc=$?

    if [ $parse_rc -eq 0 ] && [ -n "$models" ]; then
        printf '%s\n' "$models"
        return 0
    fi

    if [ $parse_rc -eq 2 ]; then
        log_error "Backend '$backend' returned an invalid /v1/models response at $api_url/models."
        log_info "Check that the service exposes an OpenAI-compatible models endpoint, or pass a known model explicitly with --model <model>."
        return 1
    fi

    if [ $parse_rc -eq 4 ]; then
        log_error "jq is required to parse backend model discovery responses."
        log_info "Install jq, or pass a known model explicitly with --model <model>."
        return 1
    fi

    if model=$(launch_backend_configured_model "$backend"); then
        log_info "Backend '$backend' did not advertise models at $api_url/models; using configured Harbor model '$model'."
        echo "$model"
        return 0
    fi

    log_error "Backend '$backend' did not advertise any models at $api_url/models."
    log_info "Pull or load a model for '$backend', or pass one explicitly with --model <model>."
    return 1
}

launch_discover_model() {
    local backend="$1"
    local api_url="$2"

    launch_select_model "$backend" "$(launch_discover_models "$backend" "$api_url")"
}

launch_model_is_embedding() {
    local model
    model=$(harbor_lower "$1")

    case "$model" in
    *embed* | *embedding* | *bge-* | *e5-* | *gte-* | *rerank*)
        return 0
        ;;
    esac

    return 1
}

launch_select_model() {
    local backend="$1"
    local models="$2"
    local configured
    local model

    if configured=$(launch_backend_configured_model "$backend"); then
        while IFS= read -r model; do
            if [ "$model" = "$configured" ] && ! launch_model_is_embedding "$model"; then
                echo "$model"
                return 0
            fi
        done <<EOF
$models
EOF
    fi

    while IFS= read -r model; do
        if [ -n "$model" ] && ! launch_model_is_embedding "$model"; then
            echo "$model"
            return 0
        fi
    done <<EOF
$models
EOF

    printf '%s\n' "$models" | awk 'NF { print; exit }'
}

launch_append_unique() {
    local var_name="$1"
    local value="$2"
    local existing

    eval "local values=(\"\${${var_name}[@]}\")"
    for existing in "${values[@]}"; do
        if [ "$existing" = "$value" ]; then
            return 0
        fi
    done

    eval "${var_name}+=(\"$value\")"
}

launch_tool_group_tools() {
    case "$1" in
    web)
        echo "web_search read_url"
        ;;
    *)
        return 1
        ;;
    esac
}

launch_workflow_id_for_groups() {
    local group
    local id="boost"

    for group in "$@"; do
        id="$id-$group"
    done

    echo "$id"
}

launch_json_array() {
    local first=true
    local value

    printf '['
    for value in "$@"; do
        if $first; then
            first=false
        else
            printf ','
        fi
        printf '"%s"' "$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    done
    printf ']'
}

launch_boost_workflow_json() {
    local workflow_id="$1"
    shift
    local tools_json

    tools_json=$(launch_json_array "$@")
    printf '{"%s":{"name":"Harbor Launch %s","description":"Generated by harbor launch for selected tool groups","modules":[{"module":"tools","config":{"tools":%s}},{"module":"final"}]}}' \
        "$workflow_id" "$workflow_id" "$tools_json"
}

launch_tool_group_services() {
    case "$1" in
    web)
        echo "searxng"
        ;;
    esac
}

launch_workflow_model_name() {
    local workflow_id="$1"
    local model="$2"

    case "$model" in
    "$workflow_id"-*)
        echo "$model"
        ;;
    *)
        echo "$workflow_id-$model"
        ;;
    esac
}

launch_prefix_models() {
    local workflow_id="$1"
    local models="$2"
    local model

    while IFS= read -r model; do
        if [ -n "$model" ]; then
            launch_workflow_model_name "$workflow_id" "$model"
        fi
    done <<EOF
$models
EOF
}

launch_prepare_boost_workflow() {
    local target_backend="$1"
    local workflow_id="$2"
    local workflow_json="$3"
    shift 3
    local compose_services=("$target_backend" boost)
    local start_services=(boost)
    local service

    log_info "Starting Boost workflow '$workflow_id' for backend '$target_backend'..."
    for service in "$@"; do
        launch_append_unique compose_services "$service"
        launch_append_unique start_services "$service"
    done

    HARBOR_BOOST_WORKFLOWS="$workflow_json" \
        $(compose_with_options --no-defaults "${compose_services[@]}") up -d --wait "${start_services[@]}"
}

launch_args_include_model() {
    local arg

    for arg in "$@"; do
        case "$arg" in
        -m | --model | --model=*)
            return 0
            ;;
        esac
    done

    return 1
}

launch_pi_args_include_session() {
    local arg

    for arg in "$@"; do
        case "$arg" in
        --session-dir | --session-dir=* | --session | --session=* | --continue | -c | --resume | -r | --fork | --fork=*)
            return 0
            ;;
        esac
    done

    return 1
}

launch_pi_workspace_session_dir() {
    local workspace="$1"
    local slug

    slug=$(printf '%s' "$workspace" | sed 's#[^A-Za-z0-9._-]#-#g; s#--*#-#g; s#^-##; s#-$##')
    if [ -z "$slug" ]; then
        slug="workspace"
    fi

    echo "${HARBOR_LAUNCH_PI_SESSION_ROOT:-$HOME/.pi/agent/sessions}/$slug"
}

launch_in_original_dir() {
    (cd "$original_dir" && "$@")
}

launch_option_value_missing() {
    local value="${1-}"

    if [ -z "$value" ]; then
        return 0
    fi

    case "$value" in
    -*)
        return 0
        ;;
    esac

    return 1
}

launch_require_tool() {
    local tool="$1"
    local binary="$2"

    if ! command -v "$binary" >/dev/null 2>&1; then
        log_error "Host tool '$binary' for launch target '$tool' is not installed or is not on PATH."
        if service_compose_exists "$tool"; then
            log_info "'$tool' is also a Harbor service. To launch the service container instead, run: harbor launch --service $tool"
        fi
        return 1
    fi
}

launch_tool_binary() {
    case "$1" in
    vscode)
        echo "code"
        ;;
    *)
        echo "$1"
        ;;
    esac
}

launch_json_merge_file() {
    local path="$1"
    local filter="$2"
    shift 2
    local dir
    local tmp

    if ! command -v jq >/dev/null 2>&1; then
        log_error "jq is required to write launch config at $path."
        return 1
    fi

    dir=$(dirname "$path")
    mkdir -p "$dir" || return 1

    tmp=$(mktemp "${dir}/harbor-launch.XXXXXX") || return 1

    if [ -f "$path" ]; then
        if ! jq "$filter" "$@" "$path" >"$tmp"; then
            rm -f "$tmp"
            log_error "Could not update JSON launch config at $path."
            return 1
        fi
    else
        if ! printf '{}\n' | jq "$filter" "$@" >"$tmp"; then
            rm -f "$tmp"
            log_error "Could not create JSON launch config at $path."
            return 1
        fi
    fi

    mv "$tmp" "$path"
}

launch_opencode_config_content() {
    local provider="$1"
    local backend="$2"
    local api_url="$3"
    local api_key="$4"
    local model="$5"
    local models="$6"

    if ! command -v jq >/dev/null 2>&1; then
        log_error "jq is required to generate OpenCode launch config."
        return 1
    fi

    jq -cn \
        --arg provider "$provider" \
        --arg backend "$backend" \
        --arg api_url "$api_url" \
        --arg api_key "$api_key" \
        --arg model "$model" \
        --arg models "$models" \
        '((($models | split("\n") | map(select(length > 0))) as $ids | if ($ids | length) > 0 then $ids else [$model] end) as $model_ids | {
            "$schema": "https://opencode.ai/config.json",
            provider: {
                ($provider): {
                    npm: "@ai-sdk/openai-compatible",
                    name: ("Harbor " + $backend),
                    options: {
                        baseURL: $api_url,
                        apiKey: $api_key
                    },
                    models: (reduce $model_ids[] as $id ({}; .[$id] = {
                        name: $id,
                        attachment: true,
                        tool_call: true
                    }))
                }
            },
            agent: {
                "harbor-smoke": {
                    mode: "primary",
                    tools: {
                        invalid: false,
                        question: false,
                        bash: false,
                        read: false,
                        glob: false,
                        grep: false,
                        edit: false,
                        write: false,
                        task: false,
                        webfetch: false,
                        todowrite: false,
                        skill: false
                    }
                }
            }
        })'
}

launch_droid_config_path() {
    echo "${HARBOR_LAUNCH_DROID_CONFIG:-$HOME/.factory/config.json}"
}

launch_write_droid_config() {
    local backend="$1"
    local api_url="$2"
    local api_key="$3"
    local model="$4"
    local models="$5"
    local path

    path=$(launch_droid_config_path)
    launch_json_merge_file "$path" '
        (($models | split("\n") | map(select(length > 0))) as $ids | if ($ids | length) > 0 then $ids else [$model] end) as $model_ids
        | .custom_models = (
            ((.custom_models // []) | map(select((.base_url != ($api_url + "/")) or ((.model as $m | $model_ids | index($m)) | not))))
            + ($model_ids | map({
                model_display_name: (. + " [Harbor " + $backend + "]"),
                model: .,
                base_url: ($api_url + "/"),
                api_key: $api_key,
                provider: "generic-chat-completion-api",
                max_tokens: 64000
            }))
        )
    ' \
        --arg backend "$backend" \
        --arg api_url "$api_url" \
        --arg api_key "$api_key" \
        --arg model "$model" \
        --arg models "$models"
}

launch_pi_models_config_path() {
    echo "${HARBOR_LAUNCH_PI_MODELS_CONFIG:-$HOME/.pi/agent/models.json}"
}

launch_pi_settings_config_path() {
    echo "${HARBOR_LAUNCH_PI_SETTINGS_CONFIG:-$HOME/.pi/agent/settings.json}"
}

launch_write_pi_config() {
    local provider="$1"
    local api_url="$2"
    local api_key="$3"
    local model="$4"
    local models="$5"
    local models_path
    local settings_path

    models_path=$(launch_pi_models_config_path)
    settings_path=$(launch_pi_settings_config_path)

    launch_json_merge_file "$models_path" '
        (($models | split("\n") | map(select(length > 0))) as $ids | if ($ids | length) > 0 then $ids else [$model] end) as $model_ids
        |
        .providers[$provider] = {
            baseUrl: $api_url,
            api: "openai-completions",
            apiKey: $api_key,
            models: ($model_ids | map({ id: . }))
        }
    ' \
        --arg provider "$provider" \
        --arg api_url "$api_url" \
        --arg api_key "$api_key" \
        --arg model "$model" \
        --arg models "$models" || return 1

    launch_json_merge_file "$settings_path" '
        .defaultProvider = $provider
        | .defaultModel = $model
    ' \
        --arg provider "$provider" \
        --arg model "$model"
}

launch_openclaw_config_path() {
    echo "${HARBOR_LAUNCH_OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
}

launch_write_openclaw_config() {
    local provider="$1"
    local api_url="$2"
    local api_key="$3"
    local model="$4"
    local models="$5"
    local path

    path=$(launch_openclaw_config_path)
    launch_json_merge_file "$path" '
        (($models | split("\n") | map(select(length > 0))) as $ids | if ($ids | length) > 0 then $ids else [$model] end) as $model_ids
        |
        .agents.defaults.model.primary = ($provider + "/" + $model)
        | .models.providers[$provider].baseUrl = $api_url
        | .models.providers[$provider].apiKey = $api_key
        | .models.providers[$provider].api = "openai-completions"
        | .models.providers[$provider].models = (
            ((.models.providers[$provider].models // []) | map(select((.id as $m | $model_ids | index($m)) | not)))
            + ($model_ids | map({
                id: .,
                name: .,
                reasoning: false,
                input: ["text"],
                cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
                contextWindow: 64000,
                maxTokens: 64000
            }))
        )
    ' \
        --arg provider "$provider" \
        --arg api_url "$api_url" \
        --arg api_key "$api_key" \
        --arg model "$model" \
        --arg models "$models"
}

launch_print_host_config() {
    local tool="$1"
    local backend="$2"
    local base_url="$3"
    local api_url="$4"
    local model="$5"
    local api_key="$6"
    local models="$7"
    local provider="harbor-$backend"

    echo "tool=$tool"
    echo "backend=$backend"
    echo "model=$model"

    case "$tool" in
    claude)
        if [ "$backend" = "ollama" ]; then
            echo "ANTHROPIC_AUTH_TOKEN=ollama"
            echo "ANTHROPIC_API_KEY="
            echo "ANTHROPIC_BASE_URL=$base_url"
        elif [ "$backend" = "boost" ]; then
            local boost_url
            boost_url=$(get_url boost 2>/dev/null || echo "$base_url")
            local boost_key
            boost_key=$(env_manager --silent get BOOST_API_KEY 2>/dev/null || true)
            echo "ANTHROPIC_API_KEY=${boost_key:-sk-boost}"
            echo "ANTHROPIC_BASE_URL=$boost_url"
        else
            echo "ANTHROPIC_API_KEY=$api_key"
            echo "ANTHROPIC_BASE_URL=$base_url"
        fi
        ;;
    copilot)
        echo "COPILOT_PROVIDER_BASE_URL=$api_url"
        echo "COPILOT_PROVIDER_API_KEY=$api_key"
        echo "COPILOT_PROVIDER_WIRE_API=responses"
        echo "COPILOT_MODEL=$model"
        ;;
    codex)
        echo "OPENAI_API_KEY=$api_key"
        echo "codex -c model_providers.harbor_launch.name=\"Harbor $backend\" -c model_providers.harbor_launch.base_url=\"$api_url\" -c model_providers.harbor_launch.env_key=\"OPENAI_API_KEY\" -c model_provider=\"harbor_launch\" -m \"$model\""
        ;;
    droid)
        echo "DROID_CONFIG=$(launch_droid_config_path)"
        launch_write_droid_config "$backend" "$api_url" "$api_key" "$model" "$models" >/dev/null || return 1
        ;;
    hermes)
        echo "OPENAI_BASE_URL=$api_url"
        echo "OPENAI_API_KEY=$api_key"
        echo "HERMES_MODEL=$model"
        ;;
    mi)
        echo "OPENAI_BASE_URL=$base_url"
        echo "OPENAI_API_KEY=$api_key"
        echo "MODEL=$model"
        echo "mi"
        ;;
    openclaw)
        echo "OPENCLAW_CONFIG=$(launch_openclaw_config_path)"
        launch_write_openclaw_config "$provider" "$api_url" "$api_key" "$model" "$models" >/dev/null || return 1
        ;;
    opencode)
        echo "OPENAI_API_KEY=$api_key"
        echo "OPENCODE_CONFIG_CONTENT=$(launch_opencode_config_content "$provider" "$backend" "$api_url" "$api_key" "$model" "$models")"
        echo "opencode -m \"$provider/$model\""
        ;;
    pi)
        echo "PI_MODELS_CONFIG=$(launch_pi_models_config_path)"
        echo "PI_SETTINGS_CONFIG=$(launch_pi_settings_config_path)"
        launch_write_pi_config "$provider" "$api_url" "$api_key" "$model" "$models" >/dev/null || return 1
        ;;
    pool)
        echo "POOLSIDE_STANDALONE_BASE_URL=$api_url"
        echo "POOLSIDE_API_KEY=$api_key"
        echo "pool -m \"$model\""
        ;;
    vscode)
        echo "code ."
        ;;
    esac
}

launch_warn_codex_backend_compat() {
    local backend="$1"

    case "$backend" in
    llamacpp | ikllamacpp)
        log_info "Codex CLI uses the Responses API tool schema; llama.cpp-family backends may reject its tool payloads with: 400 'type' of tool must be 'function'."
        log_info "If Codex fails here, use OpenCode with this backend for prompt smoke tests, or use Codex with a backend that accepts Codex's Responses API tool schema."
        ;;
    esac
}

launch_host_tool_command() {
    local tool="$1"
    shift

    local backend=""
    local model=""
    local models=""
    local config_only=false
    local boost_tool_groups=()
    local boost_tools=()
    local boost_services=()
    local tool_args=()
    local backend_url
    local api_url
    local api_key="${OPENAI_API_KEY:-sk-harbor}"

    while [ $# -gt 0 ]; do
        case "$1" in
        --backend)
            if launch_option_value_missing "${2-}"; then
                log_error "Usage: harbor launch $tool --backend <service>"
                return 1
            fi
            backend="$2"
            shift 2
            ;;
        --backend=*)
            backend="${1#--backend=}"
            if launch_option_value_missing "$backend"; then
                log_error "Usage: harbor launch $tool --backend <service>"
                return 1
            fi
            shift
            ;;
        --model | -m)
            if launch_option_value_missing "${2-}"; then
                log_error "Usage: harbor launch $tool --model <model>"
                return 1
            fi
            model="$2"
            shift 2
            ;;
        --model=*)
            model="${1#--model=}"
            if launch_option_value_missing "$model"; then
                log_error "Usage: harbor launch $tool --model <model>"
                return 1
            fi
            shift
            ;;
        --config)
            config_only=true
            shift
            ;;
        --web)
            launch_append_unique boost_tool_groups "web"
            shift
            ;;
        --)
            shift
            tool_args+=("$@")
            break
            ;;
        *)
            tool_args+=("$1")
            shift
            ;;
        esac
    done

    if [ ${#boost_tool_groups[@]} -gt 0 ] && [ "$tool" = "claude" ]; then
        log_error "harbor launch $tool does not support --web because Claude Code uses the Anthropic Messages API, not OpenAI Chat Completions."
        log_info "Use an OpenAI-compatible host tool such as codex, opencode, copilot, droid, openclaw, pi, pool, or hermes."
        return 1
    fi

    local tool_binary
    tool_binary=$(launch_tool_binary "$tool")
    if ! $config_only; then
        launch_require_tool "$tool" "$tool_binary" || return 1
    fi

    if ! backend=$(launch_detect_backend "$backend"); then
        return 1
    fi

    local backend_key
    if backend_key=$(launch_backend_api_key "$backend"); then
        api_key="$backend_key"
    fi

    if ! backend_url=$(launch_backend_url "$backend"); then
        log_error "Could not resolve a host URL for backend '$backend'."
        return 1
    fi

    api_url=$(launch_url_with_v1 "$backend_url")

    if [ -z "$model" ]; then
        if ! models=$(launch_discover_models "$backend" "$api_url"); then
            log_error "Could not discover a model for backend '$backend'. Pass one explicitly with: harbor launch --backend $backend --model <model> $tool"
            return 1
        fi
        model=$(launch_select_model "$backend" "$models")
    else
        models="$model"
    fi

    if [ ${#boost_tool_groups[@]} -gt 0 ]; then
        local target_backend="$backend"
        local target_model="$model"
        local target_models="$models"
        local workflow_id
        local workflow_json
        local group
        local group_tools
        local tool_name
        local group_services
        local service_name

        for group in "${boost_tool_groups[@]}"; do
            if ! group_tools=$(launch_tool_group_tools "$group"); then
                log_error "Unsupported launch tool group '$group'."
                return 1
            fi
            for tool_name in $group_tools; do
                launch_append_unique boost_tools "$tool_name"
            done

            group_services=$(launch_tool_group_services "$group")
            for service_name in $group_services; do
                launch_append_unique boost_services "$service_name"
            done
        done

        workflow_id=$(launch_workflow_id_for_groups "${boost_tool_groups[@]}")
        workflow_json=$(launch_boost_workflow_json "$workflow_id" "${boost_tools[@]}")

        if ! $config_only; then
            launch_prepare_boost_workflow "$target_backend" "$workflow_id" "$workflow_json" "${boost_services[@]}" || return 1
        fi

        backend="boost"
        if ! backend_url=$(get_url boost 2>/dev/null); then
            log_error "Could not resolve a host URL for Boost."
            return 1
        fi
        api_url=$(launch_url_with_v1 "$backend_url")
        api_key=$(env_manager --silent get BOOST_API_KEY 2>/dev/null || true)
        if [ -z "$api_key" ]; then
            api_key="sk-boost"
        fi
        model=$(launch_workflow_model_name "$workflow_id" "$target_model")
        models=$(launch_prefix_models "$workflow_id" "$target_models")
    fi

    if $config_only; then
        launch_print_host_config "$tool" "$backend" "$backend_url" "$api_url" "$model" "$api_key" "$models"
        return 0
    fi

    case "$tool" in
    claude)
        local claude_base_url=""
        local claude_api_key=""
        local claude_auth_token=""

        if [ "$backend" = "ollama" ]; then
            claude_base_url="$backend_url"
            claude_auth_token="ollama"
        elif [ "$backend" = "boost" ]; then
            claude_base_url=$(get_url boost 2>/dev/null)
            claude_api_key=$(env_manager --silent get BOOST_API_KEY 2>/dev/null || true)
            claude_api_key="${claude_api_key:-sk-boost}"
        else
            claude_base_url="$backend_url"
            claude_api_key="$api_key"
        fi

        if launch_args_include_model "${tool_args[@]}"; then
            ANTHROPIC_AUTH_TOKEN="$claude_auth_token" ANTHROPIC_API_KEY="$claude_api_key" ANTHROPIC_BASE_URL="$claude_base_url" launch_in_original_dir claude "${tool_args[@]}"
        else
            ANTHROPIC_AUTH_TOKEN="$claude_auth_token" ANTHROPIC_API_KEY="$claude_api_key" ANTHROPIC_BASE_URL="$claude_base_url" launch_in_original_dir claude --model "$model" "${tool_args[@]}"
        fi
        ;;
    copilot)
            COPILOT_PROVIDER_BASE_URL="$api_url" \
            COPILOT_PROVIDER_API_KEY="$api_key" \
            COPILOT_PROVIDER_WIRE_API=responses \
            COPILOT_MODEL="$model" \
            launch_in_original_dir copilot "${tool_args[@]}"
        ;;
    codex)
        local codex_args=(
            -c "model_providers.harbor_launch.name=\"Harbor $backend\""
            -c "model_providers.harbor_launch.base_url=\"$api_url\""
            -c "model_providers.harbor_launch.env_key=\"OPENAI_API_KEY\""
            -c "model_provider=\"harbor_launch\""
        )

        if ! launch_args_include_model "${tool_args[@]}"; then
            codex_args+=(-m "$model")
        fi

        launch_warn_codex_backend_compat "$backend"
        OPENAI_API_KEY="$api_key" launch_in_original_dir codex "${codex_args[@]}" "${tool_args[@]}"
        ;;
    droid)
        launch_write_droid_config "$backend" "$api_url" "$api_key" "$model" "$models" || return 1
        launch_in_original_dir droid "${tool_args[@]}"
        ;;
    hermes)
        if [ "${#tool_args[@]}" -eq 0 ]; then
            tool_args=(chat)
        fi
        OPENAI_BASE_URL="$api_url" OPENAI_API_KEY="$api_key" HERMES_MODEL="$model" launch_in_original_dir hermes "${tool_args[@]}"
        ;;
    mi)
        OPENAI_BASE_URL="$backend_url" OPENAI_API_KEY="$api_key" MODEL="$model" launch_in_original_dir mi "${tool_args[@]}"
        ;;
    openclaw)
        local provider="harbor-$backend"
        launch_write_openclaw_config "$provider" "$api_url" "$api_key" "$model" "$models" || return 1
        if [ "${#tool_args[@]}" -eq 0 ]; then
            tool_args=(tui)
        fi
        launch_in_original_dir openclaw "${tool_args[@]}"
        ;;
    opencode)
        local provider="harbor-$backend"
        local config_content
        local opencode_args=()

        config_content=$(launch_opencode_config_content "$provider" "$backend" "$api_url" "$api_key" "$model" "$models")

        if ! launch_args_include_model "${tool_args[@]}"; then
            opencode_args+=(-m "$provider/$model")
        fi

        OPENAI_API_KEY="$api_key" OPENCODE_CONFIG_CONTENT="$config_content" launch_in_original_dir opencode "${opencode_args[@]}" "${tool_args[@]}"
        ;;
    pi)
        local provider="harbor-$backend"
        local pi_args=()
        launch_write_pi_config "$provider" "$api_url" "$api_key" "$model" "$models" || return 1
        if ! launch_pi_args_include_session "${tool_args[@]}"; then
            pi_args+=(--session-dir "$(launch_pi_workspace_session_dir "$original_dir")")
        fi
        launch_in_original_dir pi "${pi_args[@]}" "${tool_args[@]}"
        ;;
    pool)
        local pool_args=()
        if ! launch_args_include_model "${tool_args[@]}"; then
            pool_args+=(-m "$model")
        fi
        POOLSIDE_STANDALONE_BASE_URL="$api_url" POOLSIDE_API_KEY="$api_key" launch_in_original_dir pool "${pool_args[@]}" "${tool_args[@]}"
        ;;
    vscode)
        if [ "${#tool_args[@]}" -eq 0 ]; then
            tool_args=("$original_dir")
        fi
        launch_in_original_dir code "${tool_args[@]}"
        ;;
    esac
}

run_launch_command() {
    local force_service_launch=false
    local launch_options=()

    case "$1" in
    "" | -h | --help | help)
        echo "Usage: harbor launch [launch-options] [--service] <service|tool> [args]"
        echo
        echo "Launches a Harbor service CLI or host coding tool using the currently running Harbor services."
        echo "When an inference backend is already running, backend-specific compose"
        echo "overlays are included the same way they are for direct service CLI commands."
        echo "Host tool adapters accept launch options before the tool name: --backend,"
        echo "--model, --config, and --web."
        echo "Every argument after the tool name is passed to the launched tool unchanged."
        echo "--web starts Boost with web_search and read_url tools, starts SearXNG,"
        echo "and routes the tool to a generated boost-web-... workflow model."
        echo "If no backend is running, host tool adapters start llamacpp by default."
        echo "Use --service before the handle to bypass host tool adapters for name-colliding services."
        echo
        echo "Supported launch targets:"
        echo "  Host tools: $(launch_supported_host_tools)"
        echo "  Backends: $(launch_supported_backends)"
        echo "  Service CLI shortcuts: $(launch_supported_service_cli_handles)"
        echo "  Container services: any service from 'harbor ls'; use --service for collisions such as hermes, mi, openclaw, and opencode."
        echo
        echo "Examples:"
        echo "  harbor launch --web --backend ollama --model qwen3.5:4b codex"
        echo "  harbor launch --backend ollama --model qwen3.5:4b codex"
        echo "  harbor launch --backend ollama --model qwen3.5:4b mi"
        echo "  harbor launch --model qwen3.5:4b claude -p \"explain this repo\""
        echo "  harbor launch --backend ollama --model qwen3.5:4b copilot -p \"explain this repo\""
        echo "  harbor launch --config opencode"
        echo "  harbor launch --config openclaw"
        echo "  harbor launch --service opencode --help"
        echo "  harbor launch mi -p \"say hello\""
        echo "  harbor launch promptfoo eval"
        return 0
        ;;
    esac

    while [ $# -gt 0 ]; do
        case "$1" in
        --service)
            force_service_launch=true
            shift
            ;;
        --backend | --model | -m)
            if launch_option_value_missing "${2-}"; then
                log_error "Usage: harbor launch $1 <value> <tool> [args]"
                return 1
            fi
            launch_options+=("$1" "$2")
            shift 2
            ;;
        --backend=* | --model=*)
            if launch_option_value_missing "${1#*=}"; then
                log_error "Usage: harbor launch ${1%%=*} <value> <tool> [args]"
                return 1
            fi
            launch_options+=("$1")
            shift
            ;;
        --config | --web)
            launch_options+=("$1")
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
        esac
    done

    local service="$1"
    if [ -z "$service" ]; then
        log_error "Usage: harbor launch [launch-options] [--service] <service|tool> [args]"
        return 1
    fi
    shift
    local tool_args=("$@")

    if $force_service_launch; then
        if [ ${#launch_options[@]} -gt 0 ]; then
            log_error "Launch host-tool options cannot be used with --service."
            return 1
        fi
        if service_compose_exists "$service"; then
            run_run "$service" "${tool_args[@]}"
        else
            log_error "Service '$service' not found."
            return 1
        fi
        return
    fi

    case "$service" in
    claude | codex | copilot | droid | hermes | mi | openclaw | opencode | pi | pool | vscode)
        ;;
    *)
        if [ ${#launch_options[@]} -gt 0 ]; then
            log_error "Launch host-tool options must be used with a supported host tool."
            return 1
        fi
        ;;
    esac

    case "$service" in
    claude | codex | copilot | droid | hermes | mi | openclaw | opencode | pi | pool | vscode)
        launch_host_tool_command "$service" "${launch_options[@]}" -- "${tool_args[@]}"
        ;;
    aider)
        run_aider_command "$@"
        ;;
    aichat)
        run_aichat_command "$@"
        ;;
    cmdh)
        run_cmdh_command "$@"
        ;;
    fabric)
        run_fabric_command "$@"
        ;;
    facts)
        run_facts_command "$@"
        ;;
    gptme)
        run_gptme_command "$@"
        ;;
    nanobot)
        run_nanobot_command "$@"
        ;;
    nexa)
        run_nexa_command "$@"
        ;;
    npcsh)
        run_npcsh_command "$@"
        ;;
    openhands | oh)
        run_openhands_command "$@"
        ;;
    opint | interpreter)
        run_opint_command "$@"
        ;;
    plandex | pdx)
        run_plandex_command "$@"
        ;;
    promptfoo | pf)
        run_promptfoo_command "$@"
        ;;
    repopack)
        run_repopack_command "$@"
        ;;
    tokscale)
        run_tokscale_cli "$@"
        ;;
    *)
        if service_compose_exists "$service"; then
            run_run "$service" "$@"
        else
            log_error "Service '$service' not found."
            return 1
        fi
        ;;
    esac
}

run_stats() {
    _check_docker || return 1
    if [ ! -t 1 ]; then
        $(compose_with_options "*") stats --no-stream "$@"
    else
        $(compose_with_options "*") stats "$@"
    fi
}

run_attach() {
  _check_docker || return 1
  local service_name=$1

  if [ -z "$service_name" ]; then
      log_error "Usage: harbor attach <service>"
      return 1
  fi

  local container_name=$(get_container_name "$service_name")

  if docker ps --filter "name=$container_name" | grep -q "$container_name"; then
        log_info "Attaching to container $container_name..."
        docker attach "$container_name"
    else
        log_error "Container $container_name is not running. Start it with 'harbor up $service_name' first."
        return 1
  fi
}

run_hf_open() {
    local search_term="${*// /+}"
    local hf_url="https://huggingface.co/models?sort=trending&search=${search_term}"

    sys_open "$hf_url"
}

link_cli() {
    local target_dir
    target_dir=$(env_manager get cli.path)
    target_dir="${target_dir/#\~/$HOME}"
    local script_name=$(env_manager get cli.name)
    local short_name=$(env_manager get cli.short)
    local script_path="$harbor_home/harbor.sh"
    local create_short_link=false

    # Validate that the source script exists before creating a symlink to it.
    # A corrupted or partial install could leave harbor_home without harbor.sh,
    # producing a broken symlink that silently fails on every invocation.
    if [[ ! -f "$script_path" ]]; then
        log_error "Source script not found: $script_path"
        log_error "The Harbor installation may be corrupted. Reinstall with:"
        log_error "  curl -fsSL https://raw.githubusercontent.com/av/harbor/main/install.sh | bash"
        return 1
    fi

    # Check for "--short" flag
    for arg in "$@"; do
        if [[ "$arg" == "--short" ]]; then
            create_short_link=true
            break
        fi
    done

    # Determine which shell configuration file to update.
    # Check $SHELL first so that a bash user on macOS (where ~/.zshrc
    # exists by default) gets the right profile instead of always zshrc.
    local shell_profile=""
    local fish_config=""
    local user_shell="${SHELL##*/}"
    case "$user_shell" in
        zsh)
            shell_profile="$HOME/.zshrc"
            ;;
        bash)
            if [[ -f "$HOME/.bash_profile" ]]; then
                shell_profile="$HOME/.bash_profile"
            elif [[ -f "$HOME/.bashrc" ]]; then
                shell_profile="$HOME/.bashrc"
            elif [[ "$OSTYPE" == "darwin"* ]]; then
                # macOS bash login shells read .bash_profile
                shell_profile="$HOME/.bash_profile"
            else
                shell_profile="$HOME/.bashrc"
            fi
            ;;
        fish)
            # Fish uses a different config format; handle separately
            fish_config="$HOME/.config/fish/conf.d/harbor.fish"
            # Also update a POSIX profile for non-fish contexts (cron, scripts, etc.)
            if [[ -f "$HOME/.profile" ]]; then
                shell_profile="$HOME/.profile"
            elif [[ -f "$HOME/.bashrc" ]]; then
                shell_profile="$HOME/.bashrc"
            else
                shell_profile="$HOME/.profile"
            fi
            ;;
    esac

    # Fallback: if $SHELL didn't match or the file doesn't exist yet,
    # probe for existing profile files.
    if [[ -z "$shell_profile" && -z "$fish_config" ]]; then
        if [[ -f "$HOME/.zshrc" ]]; then
            shell_profile="$HOME/.zshrc"
        elif [[ -f "$HOME/.bashrc" ]]; then
            shell_profile="$HOME/.bashrc"
        elif [[ -f "$HOME/.bash_profile" ]]; then
            shell_profile="$HOME/.bash_profile"
        elif [[ -f "$HOME/.profile" ]]; then
            shell_profile="$HOME/.profile"
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            shell_profile="$HOME/.zshrc"
        elif [[ "$OSTYPE" == linux* ]]; then
            shell_profile="$HOME/.bashrc"
        else
            log_warn "Sorry, but Harbor can't determine which shell configuration file to update."
            log_warn "Please link the CLI manually."
            log_warn "Harbor supports: ~/.zshrc, ~/.bash_profile, ~/.bashrc, ~/.profile, fish"
            return 1
        fi
    fi

    # Ensure target directory exists
    if [[ ! -d "$target_dir" ]]; then
        log_info "Creating $target_dir..."
        if ! mkdir -p "$target_dir"; then
            log_error "Failed to create directory: $target_dir"
            log_error "Check permissions on the parent directory."
            return 1
        fi
    fi

    # Check if target directory exists in PATH (runtime or shell profile)
    local path_in_runtime=false
    local path_in_profile=false
    if echo "$PATH" | tr ':' '\n' | grep -qxF "$target_dir"; then
        path_in_runtime=true
    fi
    if [ -n "$shell_profile" ] && [ -f "$shell_profile" ] && grep -qF "$target_dir" "$shell_profile"; then
        path_in_profile=true
    fi
    if [ -n "$shell_profile" ] && [ "$path_in_profile" = false ]; then
        log_info "Adding $target_dir to PATH..."
        printf '\nexport PATH="$PATH:%s"\n' "$target_dir" >>"$shell_profile"
        echo "Updated $shell_profile with new PATH."
    fi
    if [ "$path_in_runtime" = false ]; then
        export PATH="$PATH:$target_dir"
    fi

    # Fish shell: write a fish-syntax config snippet so fish users get
    # harbor in their PATH without relying on POSIX profile sourcing.
    if [[ -n "$fish_config" ]]; then
        local fish_dir
        fish_dir=$(dirname "$fish_config")
        if [[ ! -d "$fish_dir" ]]; then
            mkdir -p "$fish_dir"
        fi
        if [[ ! -f "$fish_config" ]] || ! grep -qF "$target_dir" "$fish_config"; then
            log_info "Adding $target_dir to fish PATH..."
            printf '# Added by Harbor CLI\nif not contains "%s" $PATH\n    set -gx PATH $PATH "%s"\nend\n' \
                "$target_dir" "$target_dir" >"$fish_config"
            echo "Created $fish_config"
        fi
    fi

    # Warn if a non-symlink file already exists at the target path.
    # ln -sf removes existing symlinks, but a regular file (e.g., user's
    # own script named "harbor") would be silently replaced.
    if [[ -e "$target_dir/$script_name" && ! -L "$target_dir/$script_name" ]]; then
        log_warn "A non-symlink file exists at $target_dir/$script_name"
        log_warn "It will be replaced by a symlink to $script_path"
    fi

    # Create symlink
    if ln -sf "$script_path" "$target_dir/$script_name"; then
        log_info "Symlink created: $target_dir/$script_name -> $script_path"
    else
        log_warn "Failed to create symlink at $target_dir/$script_name"
        log_warn "Check that you have write permission to $target_dir"
        log_warn "You can also run: ln -sf $script_path $target_dir/$script_name"
        return 1
    fi

    # Create short symlink if "--short" flag is present
    if $create_short_link; then
        if [[ -e "$target_dir/$short_name" && ! -L "$target_dir/$short_name" ]]; then
            log_warn "A non-symlink file exists at $target_dir/$short_name"
            log_warn "It will be replaced by a symlink to $script_path"
        fi
        if ln -sf "$script_path" "$target_dir/$short_name"; then
            log_info "Short symlink created: $target_dir/$short_name -> $script_path"
        else
            log_warn "Failed to create short symlink at $target_dir/$short_name"
            log_warn "Check that you have write permission to $target_dir"
            return 1
        fi
    fi

    # Install tab completion scripts for the user's shell
    _install_completions

    local reload_hint=""
    if [[ -n "$shell_profile" ]]; then
        reload_hint="'source $shell_profile'"
    fi
    if [[ -n "$fish_config" ]]; then
        if [[ -n "$reload_hint" ]]; then
            reload_hint="$reload_hint (or 'source $fish_config' in fish)"
        else
            reload_hint="'source $fish_config' in fish"
        fi
    fi
    log_info "You may need to reload your shell or run $reload_hint for changes to take effect."
}

unlink_cli() {
    local target_dir
    target_dir=$(env_manager get cli.path)
    target_dir="${target_dir/#\~/$HOME}"
    local script_name=$(env_manager get cli.name)
    local short_name=$(env_manager get cli.short)

    log_info "Removing symlinks..."

    # Remove the main symlink
    if [ -L "$target_dir/$script_name" ]; then
        if rm "$target_dir/$script_name"; then
            log_info "Removed symlink: $target_dir/$script_name"
        else
            log_warn "Failed to remove symlink: $target_dir/$script_name"
            log_warn "Check permissions or remove manually: rm $target_dir/$script_name"
        fi
    else
        log_info "Main symlink does not exist or is not a symbolic link."
    fi

    # Remove the short symlink
    if [ -L "$target_dir/$short_name" ]; then
        if rm "$target_dir/$short_name"; then
            log_info "Removed short symlink: $target_dir/$short_name"
        else
            log_warn "Failed to remove short symlink: $target_dir/$short_name"
            log_warn "Check permissions or remove manually: rm $target_dir/$short_name"
        fi
    else
        log_info "Short symlink does not exist or is not a symbolic link."
    fi

    # Clean up PATH entries from shell profile files.
    # link_cli adds 'export PATH="$PATH:<target_dir>"' to shell profiles;
    # removing the symlinks without cleaning the profile leaves stale entries
    # that accumulate on repeated link/unlink cycles.
    local profiles_to_check=(
        "$HOME/.zshrc"
        "$HOME/.bashrc"
        "$HOME/.bash_profile"
        "$HOME/.profile"
    )
    local cleaned_profile=false
    for profile in "${profiles_to_check[@]}"; do
        if [ -f "$profile" ] && grep -qF "export PATH=\"\$PATH:$target_dir\"" "$profile"; then
            # Remove the exact line that link_cli added, preserving file permissions
            local temp_file
            temp_file=$(mktemp)
            grep -vF "export PATH=\"\$PATH:$target_dir\"" "$profile" > "$temp_file" || true
            # Preserve original file permissions (chmod --reference is GNU-only)
            local orig_perms
            orig_perms=$(stat -c '%a' "$profile" 2>/dev/null || stat -f '%Lp' "$profile" 2>/dev/null) && \
                chmod "$orig_perms" "$temp_file" 2>/dev/null || true
            mv "$temp_file" "$profile"
            log_info "Removed PATH entry from $profile"
            cleaned_profile=true
        fi
    done

    # Clean up fish config if it exists
    local fish_config="$HOME/.config/fish/conf.d/harbor.fish"
    if [ -f "$fish_config" ]; then
        rm -f "$fish_config"
        log_info "Removed fish config: $fish_config"
        cleaned_profile=true
    fi

    if [ "$cleaned_profile" = false ]; then
        log_info "No PATH entries found in shell profiles to clean up."
    fi

    # Remove tab completion scripts
    _uninstall_completions
}

# ========================================================================
# == Tab Completion
# ========================================================================

# Generate a bash completion script.
# The script discovers service names from compose files at completion time
# (cached for 60s) so it stays in sync with the installed services.
_generate_bash_completion() {
    cat <<'BASH_COMPLETION'
# Harbor CLI bash completion
# Generated by: harbor completion bash

_harbor_completions() {
    local cur prev words cword
    _init_completion 2>/dev/null || {
        COMPREPLY=()
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
        words=("${COMP_WORDS[@]}")
        cword=$COMP_CWORD
    }

    # Top-level subcommands
    local commands="up u start s down d restart r ps build shell logs log l pull exec run stats attach cmd help hf defaults alias aliases a link ln unlink unln launch open o url qr list ls version smi top dive eject config profile profiles p gum fixfs info update how find home vscode doctor bench history h size env dev tools eval routine volumes skills completion models tokscale tunnel t tunnels migrate modularmax ollama llamacpp ikllamacpp tgi litellm vllm dmr mlx omlx aphrodite openai opencode facts mi npcsh webui tabbyapi parllama oterm plandex pdx mistralrs interpreter opint cfd cloudflared cmdh fabric parler photoprism airllm txtai aider nanobot chatui comfyui aichat omnichain lmeval lm_eval sglang jupyter ol1 ktransformers openhands oh stt speaches boost nexa repopack k6 promptfoo pf webtop langflow kobold morphic gptme hermes mcp openfang"

    # Commands that accept service names as arguments
    local service_commands="up u start s down d logs log l build shell pull exec run stats attach cmd eject open o url qr launch dive env"

    # Config subcommands
    local config_subcommands="get set list ls search update reset"

    # Profile subcommands
    local profile_subcommands="list ls active use save save-as rm remove import export"

    # Completion subcommands
    local completion_shells="bash zsh fish"

    # HF subcommands
    local hf_subcommands="dl download parse-url find search cache ls token login"

    # Ollama subcommands
    local ollama_subcommands="model models show tags list ls pull run rm stop ps"

    # Dev subcommands
    local dev_subcommands="scaffold docs seed add-logos test lint lint-self-test"

    # Skills subcommands
    local skills_subcommands="list ls get path"

    # Defaults subcommands
    local defaults_subcommands="ls list add rm clear"

    # Get service names (cached for performance)
    _harbor_services() {
        local harbor_home cache_file cache_age services
        harbor_home="${HARBOR_HOME:-$HOME/.harbor}"
        cache_file="/tmp/.harbor_services_cache"
        cache_age=60

        # Use cache if fresh enough
        if [[ -f "$cache_file" ]]; then
            local now file_mtime age
            now=$(date +%s)
            file_mtime=$(stat -c %Y "$cache_file" 2>/dev/null || stat -f %m "$cache_file" 2>/dev/null || echo 0)
            age=$((now - file_mtime))
            if ((age < cache_age)); then
                cat "$cache_file"
                return
            fi
        fi

        # Generate from compose files
        if [[ -d "$harbor_home/services" ]]; then
            services=$(ls "$harbor_home"/services/compose.*.yml 2>/dev/null \
                | sed 's|.*/compose\.||; s|\.yml$||' \
                | grep -v '^x\.' \
                | sort)
            printf '%s' "$services" > "$cache_file" 2>/dev/null || true
            printf '%s' "$services"
        fi
    }

    # Determine completion context
    if ((cword == 1)); then
        # Complete top-level commands
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return
    fi

    local cmd="${words[1]}"

    case "$cmd" in
        config)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$config_subcommands" -- "$cur"))
            fi
            ;;
        profile|profiles|p)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$profile_subcommands" -- "$cur"))
            fi
            ;;
        completion)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$completion_shells" -- "$cur"))
            fi
            ;;
        hf)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$hf_subcommands" -- "$cur"))
            fi
            ;;
        ollama)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$ollama_subcommands" -- "$cur"))
            fi
            ;;
        dev)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$dev_subcommands" -- "$cur"))
            fi
            ;;
        skills)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$skills_subcommands" -- "$cur"))
            fi
            ;;
        defaults)
            if ((cword == 2)); then
                COMPREPLY=($(compgen -W "$defaults_subcommands" -- "$cur"))
            elif ((cword == 3)) && [[ "${words[2]}" == "add" ]]; then
                local services
                services=$(_harbor_services)
                COMPREPLY=($(compgen -W "$services" -- "$cur"))
            fi
            ;;
        up|u|start|s)
            if [[ "$cur" == --* ]]; then
                COMPREPLY=($(compgen -W "--tail --open --attach --no-defaults --skip-port-check" -- "$cur"))
            else
                local services
                services=$(_harbor_services)
                COMPREPLY=($(compgen -W "$services" -- "$cur"))
            fi
            ;;
        down|d|logs|log|l|build|shell|pull|exec|run|stats|attach|cmd|eject|open|o|url|qr|launch|dive|env)
            # Complete with service names
            local services
            services=$(_harbor_services)
            COMPREPLY=($(compgen -W "$services" -- "$cur"))
            ;;
    esac
}

complete -F _harbor_completions harbor
complete -F _harbor_completions h
BASH_COMPLETION
}

# Generate a zsh completion script.
_generate_zsh_completion() {
    cat <<'ZSH_COMPLETION'
#compdef harbor h

# Harbor CLI zsh completion
# Generated by: harbor completion zsh

_harbor() {
    local -a commands service_commands services
    local harbor_home cache_file

    commands=(
        'up:Start service(s)'
        'u:Start service(s)'
        'start:Start service(s)'
        's:Start service(s)'
        'down:Stop and remove containers'
        'd:Stop and remove containers'
        'restart:Down then up'
        'r:Down then up'
        'ps:List running containers'
        'build:Build a service'
        'shell:Open shell in service container'
        'logs:View container logs'
        'log:View container logs'
        'l:View container logs'
        'pull:Pull images or models'
        'exec:Execute command in service'
        'run:Run a one-off command'
        'stats:Show resource usage'
        'attach:Attach to running container'
        'cmd:Print docker compose command'
        'help:Show help'
        'hf:Hugging Face CLI'
        'tokscale:Monitor AI token usage'
        'models:Manage models'
        'defaults:Manage default services'
        'alias:Manage aliases'
        'aliases:Manage aliases'
        'a:Manage aliases'
        'link:Link CLI to PATH'
        'ln:Link CLI to PATH'
        'unlink:Remove CLI from PATH'
        'unln:Remove CLI from PATH'
        'launch:Launch service CLI'
        'open:Open service in browser'
        'o:Open service in browser'
        'url:Get service URL'
        'qr:Print service QR code'
        'list:List available services'
        'ls:List available services'
        'version:Show version'
        'smi:nvidia-smi'
        'top:nvidia-top'
        'dive:Inspect Docker images'
        'eject:Output resolved Compose config'
        'config:Manage configuration'
        'profile:Manage profiles'
        'profiles:Manage profiles'
        'p:Manage profiles'
        'gum:Run gum CLI'
        'fixfs:Fix file ownership for service volumes and caches'
        'info:Show system info'
        'update:Update Harbor'
        'how:Get help on how to do things'
        'find:Find models'
        'home:Print Harbor home directory'
        'vscode:Open home in VS Code'
        'doctor:Run diagnostics'
        'bench:Run benchmarks'
        'history:Command history'
        'h:Command history'
        'size:Show size info'
        'env:Manage service env vars'
        'dev:Dev tools'
        'tools:Tool management'
        'eval:Run promptfoo eval'
        'routine:Run internal routines'
        'volumes:Manage volumes'
        'skills:Manage agent skills'
        'completion:Generate shell completion scripts'
        'tunnel:Start tunnel'
        't:Start tunnel'
        'tunnels:Manage tunnels'
        'migrate:Run migration'
        'ollama:Ollama CLI'
        'llamacpp:Configure llamacpp'
        'ikllamacpp:Configure ik_llama.cpp'
        'tgi:Configure TGI'
        'litellm:Configure LiteLLM'
        'vllm:Configure VLLM'
        'dmr:Configure Docker Model Runner'
        'mlx:Configure MLX'
        'omlx:Configure oMLX'
        'aphrodite:Configure Aphrodite'
        'openai:Configure OpenAI'
        'opencode:Run opencode'
        'facts:Run facts CLI'
        'mi:Run mi agent'
        'npcsh:Run npcsh'
        'webui:Configure Open WebUI'
        'tabbyapi:Configure TabbyAPI'
        'parllama:Launch Parllama'
        'oterm:Configure oterm'
        'plandex:Launch Plandex'
        'pdx:Launch Plandex'
        'mistralrs:Configure mistral.rs'
        'interpreter:Launch Open Interpreter'
        'opint:Launch Open Interpreter'
        'cfd:Run cloudflared'
        'cloudflared:Run cloudflared'
        'cmdh:Run cmdh'
        'fabric:Run Fabric'
        'parler:Configure Parler'
        'photoprism:Configure PhotoPrism'
        'airllm:Configure AirLLM'
        'txtai:Configure txtai'
        'aider:Launch Aider'
        'nanobot:Run nanobot'
        'chatui:Configure ChatUI'
        'comfyui:Configure ComfyUI'
        'aichat:Run aichat'
        'omnichain:Omnichain service'
        'lmeval:LM Evaluation Harness'
        'lm_eval:LM Evaluation Harness'
        'sglang:Configure SGLang'
        'jupyter:Configure Jupyter'
        'ol1:Configure ol1'
        'ktransformers:Configure ktransformers'
        'openhands:Run OpenHands'
        'oh:Run OpenHands'
        'stt:Configure STT'
        'speaches:Configure Speaches'
        'boost:Configure Boost'
        'nexa:Run Nexa'
        'repopack:Run Repopack'
        'k6:Run k6'
        'promptfoo:Run promptfoo'
        'pf:Run promptfoo'
        'webtop:Configure Webtop'
        'langflow:Configure Langflow'
        'kobold:Configure Koboldcpp'
        'morphic:Configure Morphic'
        'gptme:Run gptme'
        'hermes:Configure Hermes'
        'mcp:Configure MCP'
        'modularmax:Configure Modular MAX'
        'openfang:Configure OpenFang'
    )

    # Cached service name lookup
    _harbor_services() {
        local cache_file="/tmp/.harbor_services_cache"
        local cache_age=60
        harbor_home="${HARBOR_HOME:-$HOME/.harbor}"

        if [[ -f "$cache_file" ]]; then
            local now file_mtime age
            now=$(date +%s)
            file_mtime=$(stat -c %Y "$cache_file" 2>/dev/null || stat -f %m "$cache_file" 2>/dev/null || echo 0)
            age=$((now - file_mtime))
            if ((age < cache_age)); then
                cat "$cache_file"
                return
            fi
        fi

        if [[ -d "$harbor_home/services" ]]; then
            local svcs
            svcs=$(ls "$harbor_home"/services/compose.*.yml 2>/dev/null \
                | sed 's|.*/compose\.||; s|\.yml$||' \
                | grep -v '^x\.' \
                | sort)
            printf '%s' "$svcs" > "$cache_file" 2>/dev/null || true
            printf '%s' "$svcs"
        fi
    }

    if ((CURRENT == 2)); then
        _describe -t commands 'harbor command' commands
        return
    fi

    case "${words[2]}" in
        up|u|start|s)
            if [[ "$PREFIX" == --* ]]; then
                local -a up_flags=(
                    '--tail:Start and tail the logs'
                    '--open:Start and open in browser'
                    '--attach:Attach to the first service'
                    '--no-defaults:Exclude default services'
                    '--skip-port-check:Skip port conflict pre-check'
                )
                _describe -t flags 'flag' up_flags
            else
                local -a svc_list
                svc_list=(${(f)"$(_harbor_services)"})
                _describe -t services 'service' svc_list
            fi
            ;;
        down|d|logs|log|l|build|shell|pull|exec|run|stats|attach|cmd|eject|open|o|url|qr|launch|dive|env)
            local -a svc_list
            svc_list=(${(f)"$(_harbor_services)"})
            _describe -t services 'service' svc_list
            ;;
        config)
            if ((CURRENT == 3)); then
                local -a config_cmds=(
                    'get:Get a config value'
                    'set:Set a config value'
                    'list:List all config'
                    'ls:List all config'
                    'search:Search config keys'
                    'update:Update config from defaults'
                    'reset:Reset config to defaults'
                )
                _describe -t config-commands 'config command' config_cmds
            fi
            ;;
        profile|profiles|p)
            if ((CURRENT == 3)); then
                local -a profile_cmds=(
                    'list:List profiles'
                    'ls:List profiles'
                    'active:Show active profile'
                    'use:Switch to a profile'
                    'save:Save current profile'
                    'save-as:Save profile with new name'
                    'rm:Remove a profile'
                    'remove:Remove a profile'
                    'import:Import a profile'
                    'export:Export a profile'
                )
                _describe -t profile-commands 'profile command' profile_cmds
            fi
            ;;
        completion)
            if ((CURRENT == 3)); then
                local -a shells=('bash' 'zsh' 'fish')
                _describe -t shells 'shell' shells
            fi
            ;;
        hf)
            if ((CURRENT == 3)); then
                local -a hf_cmds=('dl' 'download' 'parse-url' 'find' 'search' 'cache' 'ls' 'token' 'login')
                _describe -t hf-commands 'hf command' hf_cmds
            fi
            ;;
        ollama)
            if ((CURRENT == 3)); then
                local -a ollama_cmds=('model' 'models' 'show' 'tags' 'list' 'ls' 'pull' 'run' 'rm' 'stop' 'ps')
                _describe -t ollama-commands 'ollama command' ollama_cmds
            fi
            ;;
        dev)
            if ((CURRENT == 3)); then
                local -a dev_cmds=('scaffold' 'docs' 'seed' 'add-logos' 'test' 'lint' 'lint-self-test')
                _describe -t dev-commands 'dev command' dev_cmds
            fi
            ;;
        skills)
            if ((CURRENT == 3)); then
                local -a skills_cmds=('list' 'ls' 'get' 'path')
                _describe -t skills-commands 'skills command' skills_cmds
            fi
            ;;
        defaults)
            if ((CURRENT == 3)); then
                local -a defaults_cmds=(
                    'ls:List default services'
                    'list:List default services'
                    'add:Add a default service'
                    'rm:Remove a default service'
                    'clear:Remove all default services'
                )
                _describe -t defaults-commands 'defaults command' defaults_cmds
            elif ((CURRENT == 4)) && [[ "${words[3]}" == "add" ]]; then
                local -a svc_list
                svc_list=(${(f)"$(_harbor_services)"})
                _describe -t services 'service' svc_list
            fi
            ;;
    esac
}

compdef _harbor harbor
compdef _harbor h
ZSH_COMPLETION
}

# Generate a fish completion script.
_generate_fish_completion() {
    cat <<'FISH_COMPLETION'
# Harbor CLI fish completion
# Generated by: harbor completion fish

# Disable file completion by default
complete -c harbor -f

# Cached service name lookup
function __harbor_services
    set -l harbor_home (set -q HARBOR_HOME; and echo $HARBOR_HOME; or echo "$HOME/.harbor")
    set -l cache_file /tmp/.harbor_services_cache_fish
    set -l cache_age 60

    if test -f $cache_file
        set -l now (date +%s)
        set -l file_mtime (stat -c %Y $cache_file 2>/dev/null; or stat -f %m $cache_file 2>/dev/null; or echo 0)
        set -l age (math $now - $file_mtime)
        if test $age -lt $cache_age
            cat $cache_file
            return
        end
    end

    if test -d "$harbor_home/services"
        set -l svcs (ls "$harbor_home"/services/compose.*.yml 2>/dev/null | sed 's|.*/compose\.||; s|\.yml$||' | grep -v '^x\.' | sort)
        printf '%s\n' $svcs > $cache_file 2>/dev/null; or true
        printf '%s\n' $svcs
    end
end

# Condition helpers
function __harbor_no_subcommand
    set -l cmd (commandline -opc)
    test (count $cmd) -eq 1
end

function __harbor_using_subcommand
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 2; and contains -- $argv[1] $cmd[2]
end

function __harbor_service_subcommand
    set -l cmd (commandline -opc)
    if test (count $cmd) -ge 2
        contains -- $cmd[2] up u start s down d logs log l build shell pull exec run stats attach cmd eject open o url qr launch dive env
    end
end

# Top-level commands
complete -c harbor -n __harbor_no_subcommand -a up -d 'Start service(s)'
complete -c harbor -n __harbor_no_subcommand -a down -d 'Stop and remove containers'
complete -c harbor -n __harbor_no_subcommand -a restart -d 'Down then up'
complete -c harbor -n __harbor_no_subcommand -a ps -d 'List running containers'
complete -c harbor -n __harbor_no_subcommand -a build -d 'Build a service'
complete -c harbor -n __harbor_no_subcommand -a shell -d 'Open shell in service container'
complete -c harbor -n __harbor_no_subcommand -a logs -d 'View container logs'
complete -c harbor -n __harbor_no_subcommand -a pull -d 'Pull images or models'
complete -c harbor -n __harbor_no_subcommand -a exec -d 'Execute command in service'
complete -c harbor -n __harbor_no_subcommand -a run -d 'Run a one-off command'
complete -c harbor -n __harbor_no_subcommand -a stats -d 'Show resource usage'
complete -c harbor -n __harbor_no_subcommand -a attach -d 'Attach to running container'
complete -c harbor -n __harbor_no_subcommand -a cmd -d 'Print docker compose command'
complete -c harbor -n __harbor_no_subcommand -a help -d 'Show help'
complete -c harbor -n __harbor_no_subcommand -a hf -d 'Hugging Face CLI'
complete -c harbor -n __harbor_no_subcommand -a tokscale -d 'Monitor AI token usage'
complete -c harbor -n __harbor_no_subcommand -a models -d 'Manage models'
complete -c harbor -n __harbor_no_subcommand -a defaults -d 'Manage default services'
complete -c harbor -n __harbor_no_subcommand -a alias -d 'Manage aliases'
complete -c harbor -n __harbor_no_subcommand -a link -d 'Link CLI to PATH'
complete -c harbor -n __harbor_no_subcommand -a unlink -d 'Remove CLI from PATH'
complete -c harbor -n __harbor_no_subcommand -a launch -d 'Launch service CLI'
complete -c harbor -n __harbor_no_subcommand -a open -d 'Open service in browser'
complete -c harbor -n __harbor_no_subcommand -a url -d 'Get service URL'
complete -c harbor -n __harbor_no_subcommand -a qr -d 'Print service QR code'
complete -c harbor -n __harbor_no_subcommand -a list -d 'List available services'
complete -c harbor -n __harbor_no_subcommand -a ls -d 'List available services'
complete -c harbor -n __harbor_no_subcommand -a version -d 'Show version'
complete -c harbor -n __harbor_no_subcommand -a smi -d 'nvidia-smi'
complete -c harbor -n __harbor_no_subcommand -a top -d 'nvidia-top'
complete -c harbor -n __harbor_no_subcommand -a dive -d 'Inspect Docker images'
complete -c harbor -n __harbor_no_subcommand -a eject -d 'Output resolved Compose config'
complete -c harbor -n __harbor_no_subcommand -a config -d 'Manage configuration'
complete -c harbor -n __harbor_no_subcommand -a profile -d 'Manage profiles'
complete -c harbor -n __harbor_no_subcommand -a gum -d 'Run gum CLI'
complete -c harbor -n __harbor_no_subcommand -a fixfs -d 'Fix file ownership for service volumes'
complete -c harbor -n '__harbor_using_subcommand fixfs' -l dry-run -d 'Preview without changes'
complete -c harbor -n __harbor_no_subcommand -a info -d 'Show system info'
complete -c harbor -n __harbor_no_subcommand -a update -d 'Update Harbor'
complete -c harbor -n __harbor_no_subcommand -a how -d 'Get help on how to do things'
complete -c harbor -n __harbor_no_subcommand -a find -d 'Find models'
complete -c harbor -n __harbor_no_subcommand -a home -d 'Print Harbor home directory'
complete -c harbor -n __harbor_no_subcommand -a vscode -d 'Open home in VS Code'
complete -c harbor -n __harbor_no_subcommand -a doctor -d 'Run diagnostics'
complete -c harbor -n __harbor_no_subcommand -a bench -d 'Run benchmarks'
complete -c harbor -n __harbor_no_subcommand -a history -d 'Command history'
complete -c harbor -n __harbor_no_subcommand -a size -d 'Show size info'
complete -c harbor -n __harbor_no_subcommand -a env -d 'Manage service env vars'
complete -c harbor -n __harbor_no_subcommand -a dev -d 'Dev tools'
complete -c harbor -n __harbor_no_subcommand -a tools -d 'Tool management'
complete -c harbor -n __harbor_no_subcommand -a eval -d 'Run promptfoo eval'
complete -c harbor -n __harbor_no_subcommand -a routine -d 'Run internal routines'
complete -c harbor -n __harbor_no_subcommand -a volumes -d 'Manage volumes'
complete -c harbor -n __harbor_no_subcommand -a skills -d 'Manage agent skills'
complete -c harbor -n __harbor_no_subcommand -a completion -d 'Generate shell completions'
complete -c harbor -n __harbor_no_subcommand -a tunnel -d 'Start tunnel'
complete -c harbor -n __harbor_no_subcommand -a tunnels -d 'Manage tunnels'
complete -c harbor -n __harbor_no_subcommand -a migrate -d 'Run migration'
complete -c harbor -n __harbor_no_subcommand -a ollama -d 'Ollama CLI'
complete -c harbor -n __harbor_no_subcommand -a llamacpp -d 'Configure llamacpp'
complete -c harbor -n __harbor_no_subcommand -a tgi -d 'Configure TGI'
complete -c harbor -n __harbor_no_subcommand -a litellm -d 'Configure LiteLLM'
complete -c harbor -n __harbor_no_subcommand -a vllm -d 'Configure VLLM'
complete -c harbor -n __harbor_no_subcommand -a aphrodite -d 'Configure Aphrodite'
complete -c harbor -n __harbor_no_subcommand -a openai -d 'Configure OpenAI'
complete -c harbor -n __harbor_no_subcommand -a webui -d 'Configure Open WebUI'
complete -c harbor -n __harbor_no_subcommand -a aider -d 'Launch Aider'
complete -c harbor -n __harbor_no_subcommand -a facts -d 'Run facts CLI'
complete -c harbor -n __harbor_no_subcommand -a promptfoo -d 'Run promptfoo'
complete -c harbor -n __harbor_no_subcommand -a jupyter -d 'Configure Jupyter'
complete -c harbor -n __harbor_no_subcommand -a langflow -d 'Configure Langflow'
complete -c harbor -n __harbor_no_subcommand -a mcp -d 'Configure MCP'

# Service name completions for service-accepting commands
complete -c harbor -n __harbor_service_subcommand -a '(__harbor_services)'

# Flags for 'up' command
complete -c harbor -n '__harbor_using_subcommand up' -l tail -d 'Start and tail the logs'
complete -c harbor -n '__harbor_using_subcommand up' -l open -d 'Start and open in browser'
complete -c harbor -n '__harbor_using_subcommand up' -l attach -d 'Attach to the first service'
complete -c harbor -n '__harbor_using_subcommand up' -l no-defaults -d 'Exclude default services'
complete -c harbor -n '__harbor_using_subcommand up' -l skip-port-check -d 'Skip port conflict pre-check'

# Config subcommands
complete -c harbor -n '__harbor_using_subcommand config' -a get -d 'Get a config value'
complete -c harbor -n '__harbor_using_subcommand config' -a set -d 'Set a config value'
complete -c harbor -n '__harbor_using_subcommand config' -a list -d 'List all config'
complete -c harbor -n '__harbor_using_subcommand config' -a ls -d 'List all config'
complete -c harbor -n '__harbor_using_subcommand config' -a search -d 'Search config keys'
complete -c harbor -n '__harbor_using_subcommand config' -a update -d 'Update from defaults'
complete -c harbor -n '__harbor_using_subcommand config' -a reset -d 'Reset to defaults'

# Profile subcommands
complete -c harbor -n '__harbor_using_subcommand profile' -a list -d 'List profiles'
complete -c harbor -n '__harbor_using_subcommand profile' -a ls -d 'List profiles'
complete -c harbor -n '__harbor_using_subcommand profile' -a active -d 'Show active profile'
complete -c harbor -n '__harbor_using_subcommand profile' -a use -d 'Switch to a profile'
complete -c harbor -n '__harbor_using_subcommand profile' -a save -d 'Save current profile'
complete -c harbor -n '__harbor_using_subcommand profile' -a 'save-as' -d 'Save with new name'
complete -c harbor -n '__harbor_using_subcommand profile' -a rm -d 'Remove a profile'
complete -c harbor -n '__harbor_using_subcommand profile' -a import -d 'Import a profile'
complete -c harbor -n '__harbor_using_subcommand profile' -a export -d 'Export a profile'

# Completion subcommands
complete -c harbor -n '__harbor_using_subcommand completion' -a bash -d 'Generate bash completions'
complete -c harbor -n '__harbor_using_subcommand completion' -a zsh -d 'Generate zsh completions'
complete -c harbor -n '__harbor_using_subcommand completion' -a fish -d 'Generate fish completions'

# HF subcommands
complete -c harbor -n '__harbor_using_subcommand hf' -a dl -d 'Download model'
complete -c harbor -n '__harbor_using_subcommand hf' -a download -d 'Download model'
complete -c harbor -n '__harbor_using_subcommand hf' -a parse-url -d 'Parse HF file URL'
complete -c harbor -n '__harbor_using_subcommand hf' -a find -d 'Find models'
complete -c harbor -n '__harbor_using_subcommand hf' -a search -d 'Search models'
complete -c harbor -n '__harbor_using_subcommand hf' -a cache -d 'Manage HF cache'
complete -c harbor -n '__harbor_using_subcommand hf' -a ls -d 'List cached models'
complete -c harbor -n '__harbor_using_subcommand hf' -a token -d 'Manage HF token'
complete -c harbor -n '__harbor_using_subcommand hf' -a login -d 'Login to HF'

# Ollama subcommands
complete -c harbor -n '__harbor_using_subcommand ollama' -a model -d 'Set model'
complete -c harbor -n '__harbor_using_subcommand ollama' -a models -d 'List models'
complete -c harbor -n '__harbor_using_subcommand ollama' -a show -d 'Show model info'
complete -c harbor -n '__harbor_using_subcommand ollama' -a tags -d 'List model tags'
complete -c harbor -n '__harbor_using_subcommand ollama' -a list -d 'List models'
complete -c harbor -n '__harbor_using_subcommand ollama' -a ls -d 'List models'
complete -c harbor -n '__harbor_using_subcommand ollama' -a pull -d 'Pull a model'
complete -c harbor -n '__harbor_using_subcommand ollama' -a run -d 'Run a model'
complete -c harbor -n '__harbor_using_subcommand ollama' -a rm -d 'Remove a model'
complete -c harbor -n '__harbor_using_subcommand ollama' -a stop -d 'Stop a model'
complete -c harbor -n '__harbor_using_subcommand ollama' -a ps -d 'List running models'

# Dev subcommands
complete -c harbor -n '__harbor_using_subcommand dev' -a scaffold -d 'Scaffold a new service'
complete -c harbor -n '__harbor_using_subcommand dev' -a docs -d 'Regenerate docs'
complete -c harbor -n '__harbor_using_subcommand dev' -a seed -d 'Seed test data'
complete -c harbor -n '__harbor_using_subcommand dev' -a add-logos -d 'Resolve and write logos'
complete -c harbor -n '__harbor_using_subcommand dev' -a test -d 'Run container test matrix'
complete -c harbor -n '__harbor_using_subcommand dev' -a lint -d 'Run source lint'
complete -c harbor -n '__harbor_using_subcommand dev' -a lint-self-test -d 'Validate lint rules'

# Skills subcommands
complete -c harbor -n '__harbor_using_subcommand skills' -a list -d 'List skills'
complete -c harbor -n '__harbor_using_subcommand skills' -a ls -d 'List skills'
complete -c harbor -n '__harbor_using_subcommand skills' -a get -d 'Show a skill'
complete -c harbor -n '__harbor_using_subcommand skills' -a path -d 'Print skill path'

# Defaults subcommands
complete -c harbor -n '__harbor_using_subcommand defaults' -a ls -d 'List default services'
complete -c harbor -n '__harbor_using_subcommand defaults' -a list -d 'List default services'
complete -c harbor -n '__harbor_using_subcommand defaults' -a add -d 'Add a default service'
complete -c harbor -n '__harbor_using_subcommand defaults' -a rm -d 'Remove a default service'
complete -c harbor -n '__harbor_using_subcommand defaults' -a clear -d 'Remove all defaults'

# Aliases (h command)
complete -c h -f -w harbor
FISH_COMPLETION
}

# Output the completion script for the given shell, or install it.
run_completion_command() {
    local shell="$1"
    local install_flag="$2"

    case "$shell" in
        bash)
            _generate_bash_completion
            ;;
        zsh)
            _generate_zsh_completion
            ;;
        fish)
            _generate_fish_completion
            ;;
        "")
            echo "Usage: harbor completion <shell>"
            echo
            echo "Generate shell completion scripts for Harbor CLI."
            echo
            echo "Supported shells:"
            echo "  bash    Bash completion script"
            echo "  zsh     Zsh completion script"
            echo "  fish    Fish completion script"
            echo
            echo "To install completions for your current shell:"
            echo "  harbor completion bash  > ~/.local/share/bash-completion/completions/harbor"
            echo "  harbor completion zsh   > ~/.local/share/zsh/site-functions/_harbor"
            echo "  harbor completion fish  > ~/.config/fish/completions/harbor.fish"
            echo
            echo "Or source directly (bash/zsh):"
            echo "  source <(harbor completion bash)"
            echo "  source <(harbor completion zsh)"
            ;;
        *)
            log_error "Unknown shell: $shell"
            log_error "Supported shells: bash, zsh, fish"
            return 1
            ;;
    esac
}

# Install completion scripts for the current user's shell.
# Called by link_cli to set up completions alongside PATH.
_install_completions() {
    local user_shell="${SHELL##*/}"
    local installed=false

    case "$user_shell" in
        bash)
            local comp_dir="$HOME/.local/share/bash-completion/completions"
            if [[ ! -d "$comp_dir" ]]; then
                mkdir -p "$comp_dir" 2>/dev/null || return 0
            fi
            _generate_bash_completion > "$comp_dir/harbor" 2>/dev/null && {
                log_info "Installed bash completions to $comp_dir/harbor"
                installed=true
            }
            ;;
        zsh)
            # Use ~/.local/share/zsh/site-functions which is a standard fpath entry
            local comp_dir="$HOME/.local/share/zsh/site-functions"
            if [[ ! -d "$comp_dir" ]]; then
                mkdir -p "$comp_dir" 2>/dev/null || return 0
            fi
            _generate_zsh_completion > "$comp_dir/_harbor" 2>/dev/null && {
                log_info "Installed zsh completions to $comp_dir/_harbor"
                installed=true
            }
            # Ensure the directory is in fpath by adding to zshrc if needed
            local zshrc="$HOME/.zshrc"
            if [[ -f "$zshrc" ]] && ! grep -qF "$comp_dir" "$zshrc"; then
                printf '\nfpath=(%s $fpath)\nautoload -Uz compinit && compinit\n' "$comp_dir" >> "$zshrc"
                log_info "Added $comp_dir to fpath in $zshrc"
            fi
            ;;
        fish)
            local comp_dir="$HOME/.config/fish/completions"
            if [[ ! -d "$comp_dir" ]]; then
                mkdir -p "$comp_dir" 2>/dev/null || return 0
            fi
            _generate_fish_completion > "$comp_dir/harbor.fish" 2>/dev/null && {
                log_info "Installed fish completions to $comp_dir/harbor.fish"
                installed=true
            }
            ;;
    esac

    if [[ "$installed" = false ]]; then
        log_info "Run 'harbor completion $user_shell' to generate completion scripts manually."
    fi
}

# Remove completion scripts installed by _install_completions.
# Called by unlink_cli during cleanup.
_uninstall_completions() {
    local cleaned=false

    # Bash completions
    local bash_comp="$HOME/.local/share/bash-completion/completions/harbor"
    if [[ -f "$bash_comp" ]]; then
        rm -f "$bash_comp"
        log_info "Removed bash completions: $bash_comp"
        cleaned=true
    fi

    # Zsh completions
    local zsh_comp="$HOME/.local/share/zsh/site-functions/_harbor"
    if [[ -f "$zsh_comp" ]]; then
        rm -f "$zsh_comp"
        log_info "Removed zsh completions: $zsh_comp"
        cleaned=true
    fi
    # Clean up fpath entry from zshrc
    local zshrc="$HOME/.zshrc"
    local zsh_comp_dir="$HOME/.local/share/zsh/site-functions"
    if [[ -f "$zshrc" ]] && grep -qF "$zsh_comp_dir" "$zshrc"; then
        local temp_file
        temp_file=$(mktemp)
        grep -vF "$zsh_comp_dir" "$zshrc" > "$temp_file" || true
        # Also remove the compinit line that immediately followed the fpath line
        grep -v '^autoload -Uz compinit && compinit$' "$temp_file" > "${temp_file}.2" || true
        local orig_perms
        orig_perms=$(stat -c '%a' "$zshrc" 2>/dev/null || stat -f '%Lp' "$zshrc" 2>/dev/null) && \
            chmod "$orig_perms" "${temp_file}.2" 2>/dev/null || true
        mv "${temp_file}.2" "$zshrc"
        rm -f "$temp_file"
        log_info "Removed fpath entry from $zshrc"
    fi

    # Fish completions
    local fish_comp="$HOME/.config/fish/completions/harbor.fish"
    if [[ -f "$fish_comp" ]]; then
        rm -f "$fish_comp"
        log_info "Removed fish completions: $fish_comp"
        cleaned=true
    fi

    if [[ "$cleaned" = false ]]; then
        log_info "No completion scripts found to remove."
    fi
}

get_container_name() {
    local service_name="$1"
    local container_name="$default_container_prefix.$service_name"
    echo "$container_name"
}

get_service_port() {
    local services
    local target_name
    local port

    # Get list of running services
    services=$(docker compose ps -a --services --filter "status=running")

    # Check if any services are running
    if [ -z "$services" ]; then
        log_warn "No services are currently running."
        return 1
    fi

    service_name="$1"
    target_name=$(get_container_name "$1")

    # Check if the specified service is running
    if ! echo "$services" | grep -q "$service_name"; then
        log_warn "Service '$1' is not currently running."
        log_info "Running services:"
        log_info "$services"
        return 1
    fi

    # Get the port mapping for the service
    if port=$(docker port "$target_name" | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n 1) && [ -n "$port" ]; then
        echo "$port"
    else
        log_error "No port mapping found for service '$1'. The service may not expose a port, or it may still be starting up."
        return 1
    fi
}

get_service_url() {
    local service_name="$1"
    local port

    if port=$(get_service_port "$service_name"); then
        echo "http://localhost:$port"
        return 0
    else
        log_error "Failed to get port for service '$service_name'"
        return 1
    fi
}

get_addressable_url() {
    local service_name="$1"
    local port
    local ip_address

    if port=$(get_service_port "$service_name"); then
        if ip_address=$(get_ip); then
            echo "http://$ip_address:$port"
            return 0
        else
            log_error "Failed to get service '$service_name' IP address"
            return 1
        fi
    else
        log_error "Failed to get port for service '$service_name'"
        return 1
    fi
}

get_intra_url() {
    local service_name="$1"
    local container_name
    local intra_host
    local intra_port

    container_name=$(get_container_name "$service_name")
    intra_host=$container_name

    if intra_port=$(docker port $container_name | awk -F'[ /]' '{print $1}' | sort -n | uniq); then
        echo "http://$intra_host:$intra_port"
        return 0
    else
        log_error "Failed to get internal port for service '$service_name'"
        return 1
    fi
}

get_url() {
    local is_local=true
    local is_addressable=false
    local is_intra=false

    local filtered_args=()
    local arg

    for arg in "$@"; do
        case "$arg" in
        --intra | -i | --internal)
            is_local=false
            is_addressable=false
            is_intra=true
            ;;
        --addressable | -a | --lan)
            is_local=false
            is_intra=false
            is_addressable=true
            ;;
        *)
            filtered_args+=("$arg") # Add to filtered arguments
            ;;
        esac
    done

    # If nothing specified - use a handle
    # of the default service to open
    if [ ${#filtered_args[@]} -eq 0 ] || [ -z "${filtered_args[0]}" ]; then
        filtered_args[0]="$default_open"
    fi

    if $is_local; then
        get_service_url "${filtered_args[@]}"
    elif $is_addressable; then
        get_addressable_url "${filtered_args[@]}"
    elif $is_intra; then
        get_intra_url "${filtered_args[@]}"
    fi
}

print_qr() {
    local url="$1"
    $(compose_with_options "qrgen") run --rm qrgen "$url"
}

print_service_qr() {
    local url=$(get_url -a "$1")
    log_info "URL: $url"
    print_qr "$url"
}

sys_info() {
    show_version
    echo "=========================="
    get_services -a
    echo "=========================="
    docker info
}

sys_open() {
    url=$1
    local rc=1

    # Open the URL in the default browser.
    # In WSL, standard Linux openers (xdg-open) may not work because
    # there is no display server. Use wslview (from wslu) or
    # explorer.exe as WSL-specific fallbacks.
    if command -v xdg-open &>/dev/null; then
        xdg-open "$url" 2>/dev/null
        rc=$?
    fi
    if [ $rc -ne 0 ] && command -v wslview &>/dev/null; then
        wslview "$url" 2>/dev/null
        rc=$?
    fi
    if [ $rc -ne 0 ] && command -v open &>/dev/null; then
        open "$url"
        rc=$?
    fi
    if [ $rc -ne 0 ] && command -v explorer.exe &>/dev/null; then
        explorer.exe "$url" 2>/dev/null
        rc=$?
    fi
    if [ $rc -ne 0 ] && command -v start &>/dev/null; then
        start "$url"
        rc=$?
    fi

    if [ $rc -ne 0 ]; then
        log_error "Unable to open browser. Please visit $url manually."
        return 1
    fi
}

run_open() {
    local service_handle=$1
    local service_url

    # Check if the service has a custom URL
    local config_url=$(env_manager get "$service_handle.open_url")
    log_debug "Custom URL for $service_handle: $config_url"
    if [ -n "$config_url" ]; then
        if sys_open "$config_url"; then
            log_info "Opened $config_url in your default browser."
            return 0
        fi
    fi

    # Use docker port for the final fallback
    if service_url=$(get_url "$1"); then
        if sys_open "$service_url"; then
            log_info "Opened $service_url in your default browser."
            return 0
        fi
    else
        log_error "Failed to get service URL for '$1'. Is the service running? Try 'harbor up $1' first."
        return 1
    fi
}

smi() {
    if command -v nvidia-smi &>/dev/null; then
        nvidia-smi
    else
        log_error "nvidia-smi not found. Install NVIDIA drivers to use GPU monitoring."
    fi
}

nvidia_top() {
    if command -v nvtop &>/dev/null; then
        nvtop
    else
        log_error "nvtop not found. Install it with your package manager (e.g., 'sudo apt install nvtop')."
    fi
}

eject() {
    _check_docker || return 1

    case "$1" in
    --help | -h | help)
        echo "Usage: harbor eject [options] [services...]"
        echo ""
        echo "Output a fully-resolved Docker Compose configuration for the given services."
        echo "Accepts the same service arguments as 'harbor up'."
        echo ""
        echo "Options:"
        echo "  --no-defaults   Exclude default services, only include named services"
        echo ""
        echo "Examples:"
        echo "  harbor eject ollama                  Eject ollama + default services"
        echo "  harbor eject --no-defaults ollama    Eject only ollama"
        echo "  harbor eject ollama > compose.yml    Save to file"
        echo ""
        echo "NOTE: The output contains absolute paths to this Harbor installation"
        echo "and bind-mounted config files. To use on another machine, update the"
        echo "volume source paths to match that machine's Harbor install location."
        echo ""
        echo "WARNING: The ejected configuration inlines ALL environment"
        echo "variables from .env, including API keys and secrets."
        echo "Review the output before sharing."
        return 0
        ;;
    esac

    log_warn "Ejected config contains all .env variables including secrets. Review before sharing."
    local compose_cmd
    compose_cmd=$(compose_with_options "$@") || return 1
    $compose_cmd config
}

run_exec() {
    _check_docker || return 1
    local service_name=""
    local before_args=()
    local after_args=()
    local parsing_after=false

    # Parse arguments
    for arg in "$@"; do
        if [[ -z $service_name ]]; then
            if docker compose ps --services | grep -q "^${arg}$"; then
                service_name="$arg"
                parsing_after=true
            else
                before_args+=("$arg")
            fi
        elif $parsing_after; then
            after_args+=("$arg")
        fi
    done

    # Check if service name was found
    if [[ -z $service_name ]]; then
        log_error "No valid service name provided. Specify a running service to exec into."
        return 1
    fi

    # Check if the service is running
    if docker compose ps --services --filter "status=running" | grep -q "^${service_name}$"; then
        log_info "Service ${service_name} is running. Executing command..."

        # Construct the command
        local full_command=("${before_args[@]}" "${service_name}" "${after_args[@]}")

        # Execute the command
        # shellcheck disable=SC2068
        docker compose exec ${full_command[@]}
    else
        log_error "Service ${service_name} is not running. Please start it with 'harbor up ${service_name}' first."
        return 1
    fi
}

set_colors() {
    if [ -t 1 ] && command -v tput >/dev/null 2>&1 && tput setaf 1 >/dev/null 2>&1; then
        c_r=$(tput setaf 1)
        c_g=$(tput setaf 2)
        c_gray=$(tput setaf 8)
        c_nc=$(tput sgr0)
    elif [ -t 1 ]; then
        c_r='\033[0;31m'
        c_g='\033[0;32m'
        c_gray='\033[0;37m'
        c_nc='\033[0m'
    else
        c_r=''
        c_g=''
        c_gray=''
        c_nc=''
    fi

    # Define symbols
    ok="${c_g}✔${c_nc}"
    nok="${c_r}✘${c_nc}"
}

ensure_env_file() {
    local src_file=$default_profile
    local tgt_file=".env"

    if [ ! -f "$tgt_file" ]; then
        if [ ! -f "$src_file" ]; then
            log_error "Default profile not found: $src_file"
            log_error "Your Harbor installation may be corrupted. Try reinstalling with: curl -sS https://get.harbor.sh | bash"
            return 1
        fi
        echo "Creating .env file..."
        if ! cp "$src_file" "$tgt_file"; then
            log_error "Failed to create .env file from $src_file"
            return 1
        fi
        # .env may contain API keys — restrict to owner-only access
        chmod 600 "$tgt_file" 2>/dev/null || true
    fi
}

reset_env_file() {
    log_warn "Resetting Harbor configuration..."
    rm -f .env
    if ! ensure_env_file; then
        log_error "Failed to reset configuration."
        return 1
    fi
}

merge_env_files() {
    local default_file=$1
    local target_file=$2

    if [ -z "$default_file" ]; then
        default_file=$default_profile
    fi

    if [ -z "$target_file" ]; then
        target_file=".env"
    fi

    if [[ ! -f "$default_file" ]]; then
        log_error "Default profile not found: $default_file"
        log_error "Your Harbor installation may be corrupted. Try reinstalling with: curl -sS https://get.harbor.sh | bash"
        return 1
    fi

    # Check if both files exist
    if [[ ! -f "$target_file" ]]; then
        cp "$default_file" "$target_file"
        echo "Copied $default_file to $target_file"
        return
    fi

    # Create a temporary file; clean up on error or interrupt
    local temp_file
    temp_file=$(mktemp -t harbor.XXXXXX) || {
        log_error "Failed to create temporary file for config merge."
        return 1
    }
    trap 'rm -f "$temp_file" 2>/dev/null' RETURN

    # Variable to track empty lines
    local empty_lines=0
    # Variable to track repeated lines
    local prev_line=""
    local repeat_count=0

    # Read default file line by line and merge with target
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Handle empty lines
        if [[ -z "$line" ]]; then
            ((empty_lines++)) || true
            if ((empty_lines <= 2)); then
                echo "$line" >>"$temp_file"
            fi
            prev_line=""
            repeat_count=0
            continue
        else
            empty_lines=0
        fi

        # Check for repeated lines
        if [[ "$line" == "$prev_line" ]]; then
            ((repeat_count++)) || true
            if ((repeat_count <= 1)); then
                echo "$line" >>"$temp_file"
            fi
        else
            repeat_count=0
            if [[ "$line" =~ ^[[:alnum:]_]+=.* ]]; then
                var_name="${line%%=*}"
                if grep -q "^${var_name}=" "$target_file"; then
                    # If the variable exists in target, use that value
                    grep "^${var_name}=" "$target_file" >>"$temp_file"
                else
                    # If the variable doesn't exist in target, add the new line
                    echo "$line" >>"$temp_file"
                fi
            else
                # For comments or other content, add the new line as is
                echo "$line" >>"$temp_file"
            fi
        fi
        prev_line="$line"
    done <"$default_file"

    local added_custom=false
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^[[:alnum:]_]+=.* ]]; then
            var_name="${line%%=*}"
            if ! grep -q "^${var_name}=" "$default_file"; then
                if ! $added_custom; then
                    echo "" >> "$temp_file"
                    echo "# Custom Variables" >> "$temp_file"
                    added_custom=true
                fi
                echo "$line" >> "$temp_file"
            fi
        fi
    done <"$target_file"

    # Remove trailing newlines from the temp file
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$temp_file"
    else
        sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$temp_file"  # harbor-lint disable=HARBOR002
    fi

    # Move the temporary file to replace the target file
    mv "$temp_file" "$target_file" || {
        log_error "Failed to write merged config to $target_file"
        return 1
    }

    # Clear the RETURN trap since temp_file has been moved (no longer exists)
    trap - RETURN

    log_info "Merged content from $default_file into $target_file, preserving order and structure"
}

execute_and_process() {
    local command_to_execute="$1"
    local success_command="$2"
    local error_message="$3"

    # Execute the command and capture its output
    command_output=$(eval "$command_to_execute" 2>&1)
    exit_code=$?

    # Check the exit code
    if [ $exit_code -eq 0 ]; then
        # Replace placeholder with command output, using | as delimiter
        success_command_modified=$(echo "$success_command" | sed "s|{{output}}|$command_output|")
        # If the command succeeded, pass the output to the success command
        eval "$success_command_modified"
    else
        # If the command failed, print the custom error message and the output
        log_warn "$error_message Exit code: $exit_code. Output:"
        log_info "$command_output"
    fi
}

swap_and_retry() {

    local command=$1
    shift
    local args=("$@")
    record_history_entry "$default_history_file" "$default_history_size" "${args[*]}"

    # Try original order
    if "$command" "${args[@]}"; then
        return 0
    else
        local exit_code=$?

        # If failed and there are at least two arguments, try swapped order
        if [ $exit_code -eq $scramble_exit_code ]; then
            if [ ${#args[@]} -ge 2 ]; then
                log_warn "'harbor ${args[0]} ${args[1]}' failed, trying 'harbor ${args[1]} ${args[0]}'..."
                if "$command" "${args[1]}" "${args[0]}" "${args[@]:2}"; then
                    return 0
                else
                    # Check for common user-caused exit codes
                    exit_code=$?

                    # Check common exit codes
                    case $exit_code in
                    0)
                        log_debug "Process completed successfully"
                        return 0
                        ;;
                    1)
                        log_error "Command failed. Run 'harbor help' for usage or 'harbor doctor' to check your setup."
                        ;;
                    2)
                        log_error "Invalid command syntax. Run 'harbor help' for usage."
                        ;;
                    126)
                        log_error "Permission denied or not executable. Check file permissions and your PATH."
                        ;;
                    127)
                        log_error "Required command not found. Run 'harbor doctor' to check your dependencies."
                        ;;
                    128)
                        log_error "Invalid exit argument"
                        ;;
                    129)
                        log_warn "SIGHUP (Hangup) received"
                        ;;
                    130)
                        log_info "SIGINT (Keyboard interrupt) received"
                        ;;
                    131)
                        log_info "SIGQUIT (Keyboard quit) received"
                        ;;
                    137)
                        log_info "SIGKILL (Kill signal) received"
                        ;;
                    143)
                        log_info "SIGTERM (Termination signal) received"
                        ;;
                    *)
                        log_info "Exit code: $exit_code"
                        ;;
                    esac

                    return $exit_code
                fi
            else
                # Less than two arguments, retry is impossible
                return $exit_code
            fi
        fi

        return $exit_code
    fi
}

levenshtein_distance() {
    local s="$1" t="$2"
    local s_len=${#s} t_len=${#t}
    local -a d
    local i j cost

    for ((i = 0; i <= s_len; i++)); do d[$((i * (t_len + 1)))]=$i; done
    for ((j = 0; j <= t_len; j++)); do d[$j]=$j; done

    for ((i = 1; i <= s_len; i++)); do
        for ((j = 1; j <= t_len; j++)); do
            if [[ "${s:i-1:1}" == "${t:j-1:1}" ]]; then cost=0; else cost=1; fi
            local del=$((d[((i - 1) * (t_len + 1) + j)] + 1))
            local ins=$((d[(i * (t_len + 1) + j - 1)] + 1))
            local sub=$((d[((i - 1) * (t_len + 1) + j - 1)] + cost))
            local min=$del
            ((ins < min)) && min=$ins
            ((sub < min)) && min=$sub
            d[$((i * (t_len + 1) + j))]=$min
        done
    done

    echo "${d[$((s_len * (t_len + 1) + t_len))]}"
}

suggest_command() {
    local input="$1"
    local known_commands=(
        up u start s down d restart r ps build shell logs log l pull exec run
        stats attach cmd help --help -h hf defaults alias aliases a link ln
        unlink unln launch open o url qr list ls version --version -v smi top dive eject
        ollama llamacpp ikllamacpp tgi litellm vllm dmr mlx omlx aphrodite openai
        opencode facts mi npcsh webui tabbyapi parllama oterm plandex pdx mistralrs
        interpreter opint cfd cloudflared cmdh fabric parler photoprism airllm txtai
        aider nanobot chatui comfyui aichat omnichain lmeval lm_eval sglang
        jupyter ol1 ktransformers openhands oh stt speaches boost nexa
        repopack k6 promptfoo pf webtop langflow kobold morphic gptme hermes mcp tokscale
        migrate modularmax tunnel t tunnels config profile profiles p gum
        fixfs info update how find home vscode doctor bench history h size
        env dev tools eval routine volumes skills models completion openfang
    )

    local best_match=""
    local best_distance=999

    for cmd in "${known_commands[@]}"; do
        local dist
        dist=$(levenshtein_distance "$input" "$cmd")
        if ((dist < best_distance)); then
            best_distance=$dist
            best_match=$cmd
        fi
    done

    if ((best_distance <= 3 && best_distance > 0)); then
        echo "$best_match"
    fi
}

set_default_log_levels() {
    default_log_levels_DEBUG=0
    default_log_levels_INFO=1
    default_log_levels_WARN=2
    default_log_levels_ERROR=3

    default_logl_labels_DEBUG="${c_gray}DEBUG${c_nc}"
    default_logl_labels_INFO="INFO"
    default_logl_labels_WARN="WARN"
    default_logl_labels_ERROR="${c_r}ERROR${c_nc}"
}

get_default_log_level() {
    local level="$1"
    local var_name="default_log_levels_$level"
    eval echo \$$var_name
}

get_default_log_label() {
    local level="$1"
    local var_name="default_logl_labels_$level"
    eval echo \$$var_name
}

log() {
    local level="$1"
    shift

    local current_level=$(get_default_log_level "$level")
    local set_level=$(get_default_log_level "$default_log_level")
    local label=$(get_default_log_label "$level")

    # Check if the numeric value of the current log level is greater than or equal to the set default_log_level
    if [[ $current_level -ge $set_level ]]; then
        echo "${c_gray}$(date +'%H:%M:%S')${c_nc} [$label] $*" >&2
    fi
}

# Convenience functions for different log levels
log_debug() { log "DEBUG" "${c_gray}$*${c_nc}"; }
log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }

# shellcheck disable=SC2034
__anchor_envm=true

env_manager() {
    local env_file=".env"
    local prefix="HARBOR_"
    local silent=false
    local filtered_args=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
        --silent)
            silent=true
            shift
            ;;
        --env-file)
            env_file="$2"
            shift 2
            ;;
        --prefix)
            prefix="$2"
            shift 2
            ;;
        *)
            filtered_args+=("$1")
            shift
            ;;
        esac
    done

    set -- "${filtered_args[@]}"

    # Service-scoped config: harbor config <service> [command] [key] [value]
    if [[ -n "$1" ]] && [[ -f "services/$1/override.env" ]]; then
        env_file="services/$1/override.env"
        prefix=""
        shift

        case "$1" in
        get|set|ls|list|search|find|--help|-h)
            ;;
        *)
            if [[ $# -eq 0 ]]; then
                set -- "ls"
            elif [[ $# -eq 1 ]]; then
                set -- "get" "$1"
            else
                set -- "set" "$@"
            fi
            ;;
        esac
    fi

    case "$1" in
    get)
        if [[ -z "$2" ]]; then
            $silent || log_info "Usage: harbor config get <key>"
            return 1
        fi
        local upper_key
        upper_key=$(harbor_upper "$2")
        upper_key="${upper_key//[.-]/_}"
        upper_key="${upper_key#$prefix}"
        # Use head -1 to return only the first match when keys are
        # duplicated (e.g. after a buggy merge or manual edit).
        local value
        value=$(grep "^$prefix$upper_key=" "$env_file" | head -1 | cut -d '=' -f2-)
        value="${value#\"}" # Remove leading quote if present
        value="${value%\"}" # Remove trailing quote if present
        echo "$value"
        ;;
    set)
        if [[ -z "$2" ]]; then
            $silent || log_info "Usage: harbor config set <key> <value>"
            return 1
        fi
        local upper_key
        upper_key=$(harbor_upper "$2")
        upper_key="${upper_key//[.-]/_}"
        upper_key="${upper_key#$prefix}"
        shift 2          # Remove 'set' and the key from the arguments
        local value="$*" # Capture all remaining arguments as the value
        local full_key="$prefix$upper_key"
        if grep -q "^$full_key=" "$env_file"; then
            # Replace using line-number addressing to avoid sed delimiter
            # injection.  Values containing |, &, \, or other sed
            # metacharacters previously corrupted the .env file because
            # they were interpolated into a sed s||| command.
            local line_num
            line_num=$(grep -n "^${full_key}=" "$env_file" | head -1 | cut -d: -f1)
            local tmp_set
            tmp_set=$(mktemp -t harbor_set.XXXXXX) || {
                log_error "Failed to create temporary file for config set."
                return 1
            }
            head -n $((line_num - 1)) "$env_file" > "$tmp_set"
            printf '%s="%s"\n' "$full_key" "$value" >> "$tmp_set"
            tail -n +$((line_num + 1)) "$env_file" >> "$tmp_set"
            mv "$tmp_set" "$env_file" || {
                rm -f "$tmp_set"
                log_error "Failed to write updated config to $env_file"
                return 1
            }
        else
            # Defensively ensure the env file ends with a newline before
            # appending — otherwise a missing trailing newline upstream
            # (e.g. profiles/default.env hand-edited without one) glues the
            # new line onto the previous one and breaks subsequent grep
            # lookups (`^KEY=` no longer matches mid-line).
            if [ -s "$env_file" ] && [ -n "$(tail -c1 "$env_file")" ]; then
                printf '\n' >>"$env_file"
            fi
            printf '%s="%s"\n' "$full_key" "$value" >>"$env_file"
            if [[ "$prefix" == "HARBOR_" ]]; then
                log_warn "Key $full_key is not a known Harbor config variable. To set a service env var, use: harbor config <service> set <key> <value>"
            fi
        fi
        $silent || log_info "Set $full_key to: \"$value\""
        ;;
    unset | rm | remove)
        if [[ -z "$2" ]]; then
            $silent || log_info "Usage: harbor config unset <key>"
            return 1
        fi
        local upper_key
        upper_key=$(harbor_upper "$2")
        upper_key="${upper_key//[.-]/_}"
        upper_key="${upper_key#$prefix}"
        if grep -q "^$prefix$upper_key=" "$env_file"; then
            if [[ "$(uname)" == "Darwin" ]]; then
                sed -i '' "/^$prefix$upper_key=/d" "$env_file"
            else
                sed -i "/^$prefix$upper_key=/d" "$env_file"  # harbor-lint disable=HARBOR002
            fi
            $silent || log_info "Removed $prefix$upper_key"
        else
            $silent || log_warn "Key $prefix$upper_key is not set in $env_file"
        fi
        ;;
    list | ls)
        run_routine configSearch list --env-file "$env_file" --prefix "$prefix"
        ;;
    reset)
        shift
        if $silent; then
            reset_env_file
        else
            run_gum confirm "Are you sure you want to reset Harbor configuration?" && reset_env_file || log_warn "Reset cancelled"
        fi
        ;;
    update)
        shift
        merge_env_files
        ;;
    search | find)
        run_routine configSearch search --env-file "$env_file" --prefix "$prefix" "$2"
        ;;
    --help | -h)
        echo "Harbor configuration management"
        echo
        echo "Usage:"
        echo "  harbor config {get|set|ls|list|search|reset|update} [key] [value]"
        echo "  harbor config <service> [get|set|ls|search] [key] [value]"
        echo "  harbor config <service> [key] [value]"
        echo
        echo "Options:"
        echo " --silent        Suppress all non-essential output"
        echo " --env-file      Specify a different environment file (default: .env)"
        echo " --prefix        Specify a different variable prefix (default: HARBOR_)"
        echo
        echo "Commands:"
        echo " get <key>       Get the value of a configuration key"
        echo " set <key> <value> Set the value of a configuration key"
        echo " ls|list         List all configuration keys and values"
        echo " search|find <query> Search config keys and values"
        echo " reset           Reset Harbor configuration to default .env"
        echo " update          Merge upstream config changes from default .env"
        echo
        echo "Service-scoped config:"
        echo " harbor config <service> ls              List service env vars"
        echo " harbor config <service> get <key>       Get a service env var"
        echo " harbor config <service> set <key> <val> Set a service env var"
        echo " harbor config <service> <key>           Shorthand get"
        echo " harbor config <service> <key> <val>     Shorthand set"
        return 0
        ;;
    *)
        $silent || echo "Usage: harbor config [options] {get|set|ls|search|reset|update} [key] [value]  OR  harbor config <service> [command] [key] [value]"
        return 1
        ;;
    esac
}

env_manager_alias() {
    local field=$1
    shift
    local get_command=""
    local set_command=""

    # Check if optional commands are provided
    if [[ "$1" == "--on-get" ]]; then
        get_command="$2"
        shift 2
    fi
    if [[ "$1" == "--on-set" ]]; then
        set_command="$2"
        shift 2
    fi

    case $1 in
    --help | -h)
        echo "Harbor config: $field"
        echo
        echo "This field is a string, use the following actions to manage it:"
        echo
        echo "  no arguments  - Get the current value"
        echo "  <value>       - Set a new value"
        echo
        return 0
        ;;
    esac

    if [ $# -eq 0 ]; then
        env_manager get "$field"
        if [ -n "$get_command" ]; then
            eval "$get_command"
        fi
    else
        env_manager set "$field" "$@"
        if [ -n "$set_command" ]; then
            eval "$set_command"
        fi
    fi
}

env_manager_arr() {
    local field=$1
    shift
    local delimiter=";"
    local get_command=""
    local set_command=""
    local add_command=""
    local remove_command=""

    case "$1" in
    --help | -h)
        echo "Harbor config: $field"
        echo
        echo "This field is an array, use the following actions to manage it:"
        echo
        echo "  ls            - List all values"
        echo "  clear         - Remove all values"
        echo "  rm <value>    - Remove a value"
        echo "  rm <index>    - Remove a value by index"
        echo "  add <value>   - Add a value"
        echo
        return 0
        ;;
    esac

    # Parse optional hook commands
    while [[ "$1" == --* ]]; do
        case "$1" in
        --on-get)
            get_command="$2"
            shift 2
            ;;
        --on-set)
            set_command="$2"
            shift 2
            ;;
        --on-add)
            add_command="$2"
            shift 2
            ;;
        --on-remove)
            remove_command="$2"
            shift 2
            ;;
        esac
    done

    local action=$1
    local value=$2

    # Helper function to get the current array
    get_array() {
        local array_string=$(env_manager get "$field")
        echo "$array_string"
    }

    # Helper function to set the array
    set_array() {
        local new_array=$1
        env_manager set "$field" "$new_array"
        if [ -n "$set_command" ]; then
            eval "$set_command"
        fi
    }

    case "$action" in
    ls | list | "")
        # Show all values
        local array=$(get_array)
        if [ -z "$array" ]; then
            log_info "Config $field is empty"
        else
            echo "$array" | tr "$delimiter" "\n"
        fi
        if [ -n "$get_command" ]; then
            eval "$get_command"
        fi
        ;;
    clear)
        # Clear all values
        set_array ""
        log_info "All values removed from $field"
        if [ -n "$remove_command" ]; then
            eval "$remove_command"
        fi
        ;;
    rm)
        if [ -z "$value" ]; then
            # Remove all values
            set_array ""
            log_info "All values removed from $field"
        else
            # Remove one value
            local array=$(get_array)
            if [ "$value" -eq "$value" ] 2>/dev/null; then
                # If value is a number, treat it as an index
                local new_array=$(echo "$array" | awk -F"$delimiter" -v idx="$value" '{
                        OFS=FS;
                        for(i=1;i<=NF;i++) {
                            if(i-1 != idx) {
                                a[++n] = $i
                            }
                        }
                        for(i=1;i<=n;i++) {
                            printf("%s%s", a[i], (i==n)?"":OFS)
                        }
                    }')
            else
                # Otherwise, treat it as a value to be removed
                local new_array=$(echo "$array" | awk -F"$delimiter" -v val="$value" '{
                        OFS=FS;
                        for(i=1;i<=NF;i++) {
                            if($i != val) {
                                a[++n] = $i
                            }
                        }
                        for(i=1;i<=n;i++) {
                            printf("%s%s", a[i], (i==n)?"":OFS)
                        }
                    }')
            fi
            set_array "$new_array"
            log_info "Value removed from $field"
        fi
        if [ -n "$remove_command" ]; then
            eval "$remove_command"
        fi
        ;;
    add)
        if [ -z "$value" ]; then
            echo "Usage: env_manager_arr $field add <value>"
            return 1
        fi
        local array=$(get_array)
        if [ -z "$array" ]; then
            new_array="$value"
        else
            new_array="${array}${delimiter}${value}"
        fi
        set_array "$new_array"
        log_info "Value added to $field"
        if [ -n "$add_command" ]; then
            eval "$add_command"
        fi
        ;;
    -h | --help | help)
        echo "Usage: $field [--on-get <command>] [--on-set <command>] [--on-add <command>] [--on-remove <command>] {ls|rm|add} [value]"
        ;;
    *)
        return 1
        ;;
    esac
}

env_manager_dict() {
    local field=$1
    shift

    local delimiter=","
    local silent=false

    local get_command=""
    local set_command=""

    case "$1" in
    --silent | -s)
        silent=true
        shift
        ;;
    --help | -h)
        echo "Harbor dict: $field"
        echo
        echo "This field is a dictionary, use the following actions to manage it:"
        echo
        echo " ls - List all key/value pairs"
        echo " get <key> - Get a key value"
        echo " set <key> <value> - Set a key value"
        echo " rm <key> - Remove a key/value pair"
        echo
        return 0
        ;;
    esac

    # Parse optional hook commands
    while [[ "$1" == --* ]]; do
        case "$1" in
        --on-get)
            get_command="$2"
            shift 2
            ;;
        --on-set)
            set_command="$2"
            shift 2
            ;;
        esac
    done

    local action=$1
    local key=$2
    local value=$3

    # Helper function to get the current dictionary
    get_dict() {
        local dict_string=$(env_manager get "$field")
        echo "$dict_string"
    }

    # Helper function to set the dictionary
    set_dict() {
        local new_dict=$1
        # Escape double quotes before setting
        new_dict=$(echo "$new_dict" | sed 's/"/\\\\"/g')
        env_manager set "$field" "$new_dict"
        if [ -n "$set_command" ]; then
            eval "$set_command"
        fi
    }

    case "$action" in
    ls | list | "")
        # Show all key/value pairs
        local dict=$(get_dict)
        if [ -z "$dict" ]; then
            $silent || log_info "Config $field is empty"
        else
            echo "$dict" | tr "$delimiter" "\n" | sed 's/=/: /'
        fi
        if [ -n "$get_command" ]; then
            eval "$get_command"
        fi
        ;;
    get)
        if [ -z "$key" ]; then
            $silent || echo "Usage: env_dict_manager $field get <key>"
            return 1
        fi
        local dict=$(get_dict)
        local value=$(echo "$dict" | awk -F"$delimiter" -v key="$key" '{
                for(i=1;i<=NF;i++) {
                    split($i,kv,"=")
                    if(kv[1] == key) {
                        print kv[2]
                        exit
                    }
                }
            }')
        if [ -n "$value" ]; then
            echo "$value"
        else
            $silent || log_info "Key $key not found in $field"
        fi
        if [ -n "$get_command" ]; then
            eval "$get_command"
        fi
        ;;
    set)
        if [ -z "$key" ] || [ -z "$value" ]; then
            echo "Usage: env_dict_manager $field set <key> <value>"
            return 1
        fi
        local dict=$(get_dict)
        local new_dict=$(echo "$dict" | awk -F"$delimiter" -v key="$key" -v val="$value" '{
                OFS=FS
                found=0
                for(i=1;i<=NF;i++) {
                    split($i,kv,"=")
                    if(kv[1] == key) {
                        $i = key "=" val
                        found=1
                    }
                }
                if(!found) {
                    $0 = $0 (NF?OFS:"") key "=" val
                }
                print $0
            }')
        set_dict "$new_dict"
        $silent || log_info "Key '$key' set in $field"
        ;;
    rm)
        if [ -z "$key" ]; then
            echo "Usage: env_dict_manager $field rm <key>"
            return 1
        fi
        local dict=$(get_dict)
        local new_dict=$(echo "$dict" | awk -F"$delimiter" -v key="$key" '{
                OFS=FS
                for(i=1;i<=NF;i++) {
                    split($i,kv,"=")
                    if(kv[1] != key) {
                        a[++n] = $i
                    }
                }
                for(i=1;i<=n;i++) {
                    printf("%s%s", a[i], (i==n)?"":OFS)
                }
            }')
        set_dict "$new_dict"
        $silent || log_info "Key '$key' removed from $field"
        ;;
    -h | --help | help)
        echo "Usage: $field [--on-get <command>] [--on-set <command>] {ls|get|set|rm} [key] [value]"
        ;;
    *)
        return 1
        ;;
    esac
}

env_manager_dict_alias() {
    local dict_var=$1
    local field=$2
    shift 2

    local get_command=""
    local set_command=""

    # Parse optional hook commands
    while [[ "$1" == --* ]]; do
        case "$1" in
        --on-get)
            get_command="$2"
            shift 2
            ;;
        --on-set)
            set_command="$2"
            shift 2
            ;;
        esac
    done

    local value=$1

    if [ -z "$dict_var" ] || [ -z "$field" ]; then
        echo "Usage: env_manager_dict_alias <dict_var> <field> [--on-get <command>] [--on-set <command>] [value]"
        return 1
    fi

    if [ -z "$value" ]; then
        # Get mode
        env_manager_dict "$dict_var" --on-get "$get_command" get "$field"
    else
        # Set mode
        env_manager_dict "$dict_var" --on-set "$set_command" set "$field" "$value"
    fi
}

override_yaml_value() {
    local file="$1"
    local key="$2"
    local new_value="$3"
    local temp_file="$(mktemp -t harbor.XXXXXX)"

    if [ -z "$file" ] || [ -z "$key" ] || [ -z "$new_value" ]; then
        echo "Usage: override_yaml_value <file_path> <key> <new_value>"
        return 1
    fi

    awk -v key="$key" -v value="$new_value" '
    $0 ~ key {
        sub(/:[[:space:]]*.*/, ": " value)
    }
    {print}
    ' "$file" >"$temp_file" && mv "$temp_file" "$file"

    if [ $? -eq 0 ]; then
        log_info "Successfully updated '$key' in $file"
    else
        log_error "Failed to update '$key' in $file"
        return 1
    fi
}

# shellcheck disable=SC2034
__anchor_profiles=true

_suggest_service() {
    local input="$1"
    local best_match=""
    local best_distance=999

    for svc_file in "$harbor_home"/services/compose.*.yml "$harbor_home"/services/compose.*.ts; do
        [ -f "$svc_file" ] || continue
        local base
        base=$(basename "$svc_file")
        # Extract service name: compose.<name>.yml or compose.<name>.<variant>.yml
        local name="${base#compose.}"
        name="${name%%.*}"
        # Skip cross-files (compose.x.*)
        [[ "$name" == "x" ]] && continue

        local dist
        dist=$(levenshtein_distance "$input" "$name")
        if ((dist < best_distance)); then
            best_distance=$dist
            best_match=$name
        fi
    done

    if ((best_distance <= 3 && best_distance > 0)); then
        echo "$best_match"
    fi
}

run_defaults_command() {
    case "$1" in
    add)
        if [ -z "$2" ]; then
            echo "Usage: harbor defaults add <service>"
            return 1
        fi
        local svc="$2"
        # Validate that the service exists
        if ! is_capability "$svc" && ! service_compose_exists "$svc"; then
            log_error "Service '$svc' not found."
            local suggestion
            suggestion=$(_suggest_service "$svc")
            if [ -n "$suggestion" ]; then
                log_info "Did you mean: ${c_g}$suggestion${c_nc}?"
            fi
            log_info "Run 'harbor ls' to see available services."
            return 1
        fi
        # Check for duplicates
        local current
        current=$(env_manager get services.default)
        if [ -n "$current" ]; then
            local IFS=";"
            for existing in $current; do
                if [ "$existing" = "$svc" ]; then
                    log_warn "Service '$svc' is already in defaults."
                    return 0
                fi
            done
            unset IFS
        fi
        env_manager_arr services.default add "$svc"
        ;;
    rm)
        if [ -n "$2" ]; then
            # If removing by name (not index), check it exists in defaults
            if ! [ "$2" -eq "$2" ] 2>/dev/null; then
                local current
                current=$(env_manager get services.default)
                local found=false
                if [ -n "$current" ]; then
                    local IFS=";"
                    for existing in $current; do
                        if [ "$existing" = "$2" ]; then
                            found=true
                            break
                        fi
                    done
                    unset IFS
                fi
                if ! $found; then
                    log_error "Service '$2' is not in defaults."
                    log_info "Current defaults: $(env_manager get services.default | tr ';' ' ')"
                    return 1
                fi
            fi
        fi
        env_manager_arr services.default "$@"
        ;;
    *)
        env_manager_arr services.default "$@"
        ;;
    esac
}

run_profile_command() {
    case "$1" in
    save | add)
        shift
        harbor_profile_save "$@"
        ;;
    set | use | load)
        shift
        harbor_profile_set "$@"
        ;;
    remove | rm)
        shift
        harbor_profile_remove "$@"
        ;;
    list | ls)
        shift
        harbor_profile_list
        ;;
    merge | m)
        shift
        harbor_profile_merge "$@"
        ;;
    --help | -h | "")
        echo "Harbor profile management"
        echo "Usage: harbor profile <command> [profile_name]"
        echo
        echo "Commands:"
        echo "  save|add <profile_name>      - Save the current configuration as a profile"
        echo "  set|use|load <profile_name>  - Set current profile (supports URLs)"
        echo "  remove|rm <profile_name>     - Remove a profile"
        echo "  list|ls                      - List all profiles"
        echo "  merge|m <profile_name>       - Merge a profile into the current configuration"
        echo
        echo "Profile names may contain letters, numbers, hyphens, underscores, and dots."
        echo "Use a URL with 'set' to download and apply a remote profile."
        return 0
        ;;
    *)
        log_error "Unknown profile command: $1"
        echo "Usage: harbor profile {save|set|load|remove|list|merge} [profile_name]" >&2
        return 1
        ;;
    esac
}

harbor_profile_save() {
    local profile_name=$1

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    # Validate profile name: alphanumeric, hyphens, underscores, dots only
    if [[ ! "$profile_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
        log_error "Invalid profile name '$profile_name'. Use only letters, numbers, hyphens, underscores, and dots."
        return 1
    fi

    # Prevent path traversal
    if [[ "$profile_name" == *".."* ]] || [[ "$profile_name" == *"/"* ]]; then
        log_error "Invalid profile name '$profile_name'. Path components are not allowed."
        return 1
    fi

    local profile_file="$profiles_dir/$profile_name.env"

    if [ ! -f "$default_current_env" ]; then
        log_error "No current configuration to save. Run 'harbor up' first to initialize."
        return 1
    fi

    if [ -f "$profile_file" ]; then
        if ! run_gum confirm "Profile '$profile_name' already exists. Overwrite?"; then
            echo "Save cancelled."
            return 1
        fi
    fi

    mkdir -p "$profiles_dir" || {
        log_error "Failed to create profiles directory: $profiles_dir"
        return 1
    }
    cp "$default_current_env" "$profile_file" || {
        log_error "Failed to save profile. Check disk space and permissions."
        return 1
    }
    log_info "Profile '$profile_name' saved."
}

harbor_profile_list() {
    local found=false
    echo "Available profiles:"
    for profile in "$profiles_dir"/*.env; do
        [ -f "$profile" ] || continue
        found=true
        basename "$profile" .env
    done
    if ! $found; then
        log_info "No saved profiles. Save the current config with: harbor profile save <name>"
    fi
}

# Helper function to check if a string is a URL
is_url() {
    local input="$1"
    if [[ "$input" =~ ^https?:// ]]; then
        return 0
    else
        return 1
    fi
}

# Helper function to convert URLs to raw content URLs for common services
resolve_raw_url() {
    local url="$1"

    # GitHub blob URLs -> raw.githubusercontent.com
    if [[ "$url" =~ github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+) ]]; then
        local user="${BASH_REMATCH[1]}"
        local repo="${BASH_REMATCH[2]}"
        local branch="${BASH_REMATCH[3]}"
        local path="${BASH_REMATCH[4]}"
        echo "https://raw.githubusercontent.com/${user}/${repo}/${branch}/${path}"
        return 0
    fi

    # GitHub gist URLs
    if [[ "$url" =~ gist\.github\.com/([^/]+)/([^/#]+) ]]; then
        local user="${BASH_REMATCH[1]}"
        local gist_id="${BASH_REMATCH[2]}"
        echo "https://gist.githubusercontent.com/${user}/${gist_id}/raw"
        return 0
    fi

    # GitLab blob URLs -> raw
    if [[ "$url" =~ gitlab\.com/([^/]+)/([^/]+)/(-/)?blob/([^/]+)/(.+) ]]; then
        local user="${BASH_REMATCH[1]}"
        local repo="${BASH_REMATCH[2]}"
        local branch="${BASH_REMATCH[4]}"
        local path="${BASH_REMATCH[5]}"
        echo "https://gitlab.com/${user}/${repo}/-/raw/${branch}/${path}"
        return 0
    fi

    # Pastebin URLs -> raw
    if [[ "$url" =~ pastebin\.com/([^/]+)$ ]] && [[ ! "$url" =~ pastebin\.com/raw/ ]]; then
        local paste_id="${BASH_REMATCH[1]}"
        echo "https://pastebin.com/raw/${paste_id}"
        return 0
    fi

    # Bitbucket URLs -> raw
    if [[ "$url" =~ bitbucket\.org/([^/]+)/([^/]+)/src/([^/]+)/(.+) ]]; then
        local user="${BASH_REMATCH[1]}"
        local repo="${BASH_REMATCH[2]}"
        local branch="${BASH_REMATCH[3]}"
        local path="${BASH_REMATCH[4]}"
        echo "https://bitbucket.org/${user}/${repo}/raw/${branch}/${path}"
        return 0
    fi

    # If no transformation needed, return original URL
    echo "$url"
    return 0
}

# Validate profile content downloaded from a remote URL.
#
# Profile (.env) values are later consumed via shell substitution in several
# code paths (for example, "$(env_manager get cli.path)" expanded inside an
# `eval` invocation). A malicious remote profile can therefore achieve
# arbitrary command execution by embedding command substitution `$(...)` or
# backticks `` `...` `` in a value. This function inspects each non-comment,
# non-empty line of a downloaded profile and rejects the file if it contains
# constructs that could be evaluated as code, or if a key is not a plain
# identifier.
#
# Locally authored profiles (saved via `harbor profile add`) are not passed
# through this check because their content is produced by Harbor itself.
validate_profile_content() {
    local file="$1"
    local lineno=0
    local line key value

    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))

        # Skip blank lines and comments
        case "$line" in
            "" | \#*) continue ;;
        esac

        # Strip leading "export " if present
        line="${line#export }"

        # Must be KEY=VALUE
        if [[ "$line" != *=* ]]; then
            log_error "Profile validation failed at line $lineno: not a KEY=VALUE assignment"
            return 1
        fi

        key="${line%%=*}"
        value="${line#*=}"

        # Key must be a plain identifier
        if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            log_error "Profile validation failed at line $lineno: invalid key \"$key\""
            return 1
        fi

        # Reject command substitution and backticks anywhere in the value.
        # Even inside double quotes these would be expanded when the value is
        # later interpolated through shell evaluation.
        if [[ "$value" == *'$('* ]] || [[ "$value" == *'`'* ]]; then
            log_error "Profile validation failed at line $lineno: value for \"$key\" contains command substitution"
            return 1
        fi
    done < "$file"

    return 0
}

# Helper function to download a profile from URL
download_profile() {
    local url="$1"
    local profile_name="$2"
    local profile_file="$profiles_dir/${profile_name}.env"

    log_info "Downloading profile from: $url"

    # Resolve to raw content URL if needed
    local raw_url
    raw_url=$(resolve_raw_url "$url")

    if [ "$raw_url" != "$url" ]; then
        log_info "Resolved to raw URL: $raw_url"
    fi

    # Create profiles directory if it doesn't exist
    mkdir -p "$profiles_dir"

    # Download the file
    if curl -sL "$raw_url" -o "$profile_file"; then
        # Check if downloaded file is empty or contains error content
        if [ ! -s "$profile_file" ]; then
            log_error "Downloaded profile is empty"
            rm -f "$profile_file"
            return 1
        fi

        # Basic validation - check if it looks like an env file
        if ! grep -q "=" "$profile_file" && ! grep -q "^#" "$profile_file"; then
            log_error "Downloaded content does not appear to be a valid profile file"
            rm -f "$profile_file"
            return 1
        fi

        # Security validation: reject profiles whose values could trigger
        # arbitrary command execution when later consumed via shell expansion.
        # See validate_profile_content() above for the threat model.
        if ! validate_profile_content "$profile_file"; then
            log_error "Refusing to install profile from $url: unsafe content detected"
            rm -f "$profile_file"
            return 1
        fi

        log_warn "Loaded profile from a remote URL ($url)."
        log_warn "Remote profiles can change Harbor configuration; review with: cat \"$profile_file\""
        log_info "Successfully downloaded profile as: $profile_name"
        return 0
    else
        log_error "Failed to download profile from: $raw_url"
        rm -f "$profile_file"
        return 1
    fi
}

harbor_profile_set() {
    local profile_name=$1
    local profile_file="$profiles_dir/$profile_name.env"

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    # Check if profile_name is a URL
    if is_url "$profile_name"; then
        # Generate a profile name from the URL
        local url_profile_name
        url_profile_name=$(basename "$profile_name" .env)
        # If basename doesn't give a meaningful name, create one from timestamp
        if [[ "$url_profile_name" == "$profile_name" ]] || [[ "$url_profile_name" == "" ]]; then
            url_profile_name="url_profile_$(date +%s)"
        fi

        # Download the profile
        if ! download_profile "$profile_name" "$url_profile_name"; then
            return 1
        fi

        # Update variables to use the downloaded profile
        profile_name="$url_profile_name"
        profile_file="$profiles_dir/$profile_name.env"
    fi

    if [ ! -f "$profile_file" ]; then
        log_error "Profile '$profile_name' not found."
        log_info "Run 'harbor profile list' to see available profiles."
        return 1
    fi

    # Check if profile file is shorter than .env file
    if [ -f ".env" ]; then
        local profile_size
        local env_size
        profile_size=$(wc -c < "$profile_file" 2>/dev/null || echo 0)
        env_size=$(wc -c < ".env" 2>/dev/null || echo 0)

        if [ "$profile_size" -lt "$env_size" ]; then
            log_info "Profile is smaller than current config; merging to preserve new config keys."
            harbor_profile_merge "$profile_name"
            return $?
        fi
    fi

    cp "$profile_file" .env
    log_info "Profile '$profile_name' loaded."
}

harbor_profile_merge() {
    local profile_name=$1
    local profile_file="$profiles_dir/$profile_name.env"

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    if [ ! -f "$profile_file" ]; then
        log_error "Profile '$profile_name' not found."
        log_info "Available profiles: $(harbor_profile_list 2>/dev/null | tail -n +2 | tr '\n' ' ')"
        return 1
    fi

    local tmp_env_merge
    tmp_env_merge=$(mktemp -t harbor.XXXXXX) || {
        log_error "Failed to create temporary file for merge."
        return 1
    }
    trap 'rm -f "$tmp_env_merge" 2>/dev/null' RETURN

    cp "$profile_file" "$tmp_env_merge"
    if ! merge_env_files "$default_current_env" "$tmp_env_merge"; then
        log_error "Failed to merge current config into profile."
        return 1
    fi
    if ! merge_env_files "$default_profile" "$tmp_env_merge"; then
        log_error "Failed to merge default profile."
        return 1
    fi

    cp "$tmp_env_merge" "$default_current_env" || {
        log_error "Failed to write merged config."
        return 1
    }
    trap - RETURN
    rm -f "$tmp_env_merge" 2>/dev/null
    log_info "Profile '$profile_name' merged into current configuration."
}

harbor_profile_remove() {
    local profile_name=$1

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    # Validate profile name
    if [[ ! "$profile_name" =~ ^[A-Za-z0-9._-]+$ ]] || [[ "$profile_name" == *".."* ]]; then
        log_error "Invalid profile name '$profile_name'."
        return 1
    fi

    local profile_file="$profiles_dir/$profile_name.env"

    if [ "$profile_name" == "default" ]; then
        log_error "Cannot remove the default profile."
        return 1
    fi

    if [ ! -f "$profile_file" ]; then
        log_error "Profile '$profile_name' not found."
        log_info "Available profiles: $(harbor_profile_list 2>/dev/null | tail -n +2 | tr '\n' ' ')"
        return 1
    fi

    run_gum confirm "Are you sure you want to remove profile '$profile_name'?" || return 1

    if ! rm -f "$profile_file"; then
        log_error "Failed to remove profile file: $profile_file"
        log_error "Try manually: rm '$profile_file'"
        return 1
    fi
    log_info "Profile '$profile_name' removed."
}

# shellcheck disable=SC2034
__anchor_utils=true

run_harbor_find() {
    local dirs=""
    local dir raw_dir

    for raw_dir in \
        "$(env_manager get hf.cache)" \
        "$(env_manager get llamacpp.cache)" \
        "$(env_manager get ollama.cache)" \
        "$(env_manager get vllm.cache)" \
        "$(env_manager get comfyui.workspace)"; do
        # Safe tilde expansion without eval
        dir="${raw_dir/#\~/$HOME}"
        if [ -d "$dir" ]; then
            dirs="$dirs $dir"
        fi
    done

    if [ -z "$dirs" ]; then
        return 0
    fi

    find $dirs -type f -follow -path "*$**" 2>/dev/null || true
}

run_hf_docker_cli() {
    $(compose_with_options "hf") run --rm hf "$@"
}

run_tokscale_cli() {
    $(compose_with_options "tokscale") run --rm tokscale "$@"
}

check_hf_cache() {
    local maybe_cache_entry

    maybe_cache_entry=$(run_hf_docker_cli scan-cache | grep $1)

    if [ -z "$maybe_cache_entry" ]; then
        log_warn "$1 is missing in Hugging Face cache."
        return 1
    else
        log_info "$1 found in the cache."
        return 0
    fi
}

parse_hf_url() {
    local url=$1
    local base_url="https://huggingface.co/"
    local ref="/blob/main/"

    # Extract repo name
    repo_name=${url#$base_url}
    repo_name=${repo_name%%$ref*}

    # Extract file specifier
    file_specifier=${url#*$ref}

    # Return values separated by a delimiter (we'll use '|')
    echo "$repo_name$delimiter$file_specifier"
}

hf_url_2_llama_spec() {
    local decomposed=$(parse_hf_url $1)
    local repo_name=$(echo "$decomposed" | cut -d"$delimiter" -f1)
    local file_specifier=$(echo "$decomposed" | cut -d"$delimiter" -f2)

    echo "--hf-repo $repo_name --hf-file $file_specifier"
}

hf_spec_2_folder_spec() {
    # Replace all "/" with "_"
    echo "${1//\//_}"
}

docker_fsacl() {
    # Single-folder chown helper. Currently unused -- run_fixfs handles
    # all fixfs logic with batching and deduplication. Kept as a public
    # API in case external scripts or future code need per-folder fixes.
    local folder=$1

    _check_docker || return 1

    if [[ ! -e "$folder" ]]; then
        log_debug "fsacl: skipping non-existent path: $folder"
        return 0
    fi

    # macOS: Docker Desktop osxfs/virtiofs maps all bind-mounted files as
    # owned by the Docker Desktop user. chown inside a container is a no-op.
    if [[ "$(uname)" == "Darwin" ]]; then
        log_debug "fsacl: skipping on macOS (Docker Desktop manages file ownership via osxfs/virtiofs)"
        return 0
    fi

    local uid=$(id -u)
    local gid=$(id -g)
    log_debug "fsacl: $folder (chown to $uid:$gid)"

    local abs_folder=$(_portable_realpath "$folder")

    docker run --rm \
        --entrypoint sh \
        -v "$abs_folder:/target" \
        -u root \
        alpine:3.20 \
        -c "chown -R $uid:$gid /target" || {
        log_warn "Failed to fix permissions for: $folder"
        return 1
    }
}

run_fixfs() {
    local dry_run=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
        --dry-run)
            dry_run=true
            shift
            ;;
        --help | -h | help)
            echo "Fix file ownership for Harbor service volumes and caches"
            echo
            echo "Usage: harbor fixfs [--dry-run]"
            echo
            echo "Options:"
            echo "  --dry-run   Show which paths would be fixed without changing anything"
            echo
            echo "Discovers all external cache, workspace, and config directories"
            echo "from your Harbor configuration and sets ownership to your user."
            echo "Useful after Docker creates bind-mount directories as root."
            echo
            echo "Note: Not needed on macOS (Docker Desktop manages ownership)."
            echo "Note: Not applicable with rootless Docker (uid remapping)."
            return 0
            ;;
        *)
            log_error "Unknown option: $1"
            log_error "Usage: harbor fixfs [--dry-run]"
            return 1
            ;;
        esac
    done

    # Docker is required to run a privileged container for chown
    if ! $dry_run; then
        _check_docker || return 1
    fi

    # On macOS, Docker Desktop uses osxfs/virtiofs to share host files with
    # containers. All bind-mounted files appear owned by the user running
    # Docker Desktop regardless of on-disk ownership. chown inside a
    # container is silently ignored -- the host filesystem is unaffected.
    # Warn and exit early since the operation would be a misleading no-op.
    if [[ "$(uname)" == "Darwin" ]]; then
        log_warn "harbor fixfs is not needed on macOS."
        log_warn "Docker Desktop for Mac uses osxfs/virtiofs, which transparently"
        log_warn "maps file ownership. Permission issues on macOS are typically caused"
        log_warn "by Docker Desktop file sharing settings, not file ownership."
        log_warn "Check Docker Desktop > Settings > Resources > File Sharing."
        return 0
    fi

    # Detect rootless Docker -- the uid namespace is remapped, so chown
    # to the host uid inside the container sets ownership to a different
    # actual uid on the host filesystem.
    if ! $dry_run; then
        local docker_security
        docker_security=$(docker info --format '{{.SecurityOptions}}' 2>/dev/null || true)
        if echo "$docker_security" | grep -q 'rootless'; then
            log_warn "Rootless Docker detected. File ownership is managed through"
            log_warn "user namespace remapping. harbor fixfs may not produce the"
            log_warn "expected results. If you still have permission issues, check"
            log_warn "your subuid/subgid configuration."
            log_warn "See: https://docs.docker.com/engine/security/rootless/"
            return 0
        fi
    fi

    local uid=$(id -u)
    local gid=$(id -g)

    local paths=("$harbor_home")

    # Discover external folder-type config values via env_manager search.
    # Paths starting with ./ are under harbor_home, already covered by
    # the recursive chown on $harbor_home above.
    local suffixes=("_CACHE" "_WORKSPACE" "_CONFIG_PATH" "_CONFIG_DIR")
    local search_failed=false
    for suffix in "${suffixes[@]}"; do
        local search_output
        search_output=$(env_manager --silent search "$suffix" 2>/dev/null) || {
            # Config search may fail if deno is unavailable or .env is broken.
            # Continue with what we have -- at minimum $harbor_home is covered.
            if ! $search_failed; then
                log_warn "Could not search config for $suffix paths (config search unavailable)."
                log_warn "Only harbor_home ($harbor_home) will be fixed."
                search_failed=true
            fi
            continue
        }
        while read -r _key value; do
            [[ -z "$value" || "$value" == ./* ]] && continue
            paths+=("${value/#\~/$HOME}")
        done <<< "$search_output"
    done

    # Deduplicate paths. When two config keys point to the same directory
    # (or a key points to a child of another already-listed path), chowning
    # both wastes time and mounts the same filesystem twice.
    local -a unique_paths=()
    local -a seen_abs=()
    for path in "${paths[@]}"; do
        [[ -z "$path" ]] && continue

        # Resolve to absolute for comparison (create first if missing so
        # _portable_realpath can resolve). In dry-run mode, report but
        # don't create missing directories.
        if [[ ! -e "$path" ]]; then
            if $dry_run; then
                log_info "  [would create] $path"
                continue
            fi
            log_debug "fixfs: creating missing directory: $path"
            mkdir -p "$path" || {
                log_warn "fixfs: failed to create directory: $path"
                continue
            }
        fi

        local abs_path
        abs_path=$(_portable_realpath "$path")

        # Check for exact duplicate or child of already-listed parent
        local is_dup=false
        for seen in "${seen_abs[@]}"; do
            if [[ "$abs_path" == "$seen" ]]; then
                is_dup=true
                break
            fi
            if [[ "$abs_path" == "$seen"/* ]]; then
                is_dup=true
                log_debug "fixfs: skipping $abs_path (child of $seen)"
                break
            fi
        done
        $is_dup && continue

        unique_paths+=("$abs_path")
        seen_abs+=("$abs_path")
    done

    if [[ ${#unique_paths[@]} -eq 0 ]]; then
        log_warn "No valid paths found to fix."
        return 0
    fi

    if $dry_run; then
        log_info "Dry run: would fix ownership to $uid:$gid for ${#unique_paths[@]} path(s):"
        for abs_path in "${unique_paths[@]}"; do
            local owner
            owner=$(stat -c '%u:%g' "$abs_path" 2>/dev/null || stat -f '%u:%g' "$abs_path" 2>/dev/null || echo "?:?")
            if [[ "$owner" == "$uid:$gid" ]]; then
                log_info "  $abs_path (already $uid:$gid)"
            else
                log_info "  $abs_path (currently $owner -> $uid:$gid)"
            fi
        done
        return 0
    fi

    log_info "Fixing permissions for ${#unique_paths[@]} path(s)..."
    log_info "Target ownership: $uid:$gid"

    # Process paths individually so a single mount failure doesn't block
    # all other paths. Large caches (e.g. ~/.cache/huggingface at 100GB+)
    # can take a long time; per-path feedback lets users see progress.
    local fixed=0
    local failed=0
    for abs_path in "${unique_paths[@]}"; do
        log_info "  $abs_path ..."

        docker run --rm \
            --entrypoint sh \
            -v "$abs_path:/target" \
            -u root \
            alpine:3.20 \
            -c "chown -R $uid:$gid /target" 2>/dev/null || {
            log_warn "  Failed: $abs_path"
            log_warn "  Check that the path exists and Docker can mount it."
            ((failed++)) || true
            continue
        }
        ((fixed++)) || true
    done

    if [[ $failed -gt 0 ]]; then
        log_warn "Fixed $fixed path(s), failed $failed path(s)."
        log_warn "For failed paths, try: sudo chown -R $(id -u):$(id -g) <path>"
        return 1
    fi

    log_info "Successfully fixed permissions for $fixed path(s)."
}

open_home_code() {
    # If VS Code executable is available
    if command -v code &>/dev/null; then
        code "$harbor_home"
    else
        # shellcheck disable=SC2016
        log_warn '"code" is not installed or not available in $PATH.'
    fi
}

unsafe_update() {
    if ! git fetch origin main --depth 1; then
        log_error "Failed to fetch latest main branch from origin."
        log_error "Check your internet connection and try again."
        return 1
    fi

    # Check if FETCH_HEAD was actually created by the fetch
    if ! git rev-parse --verify FETCH_HEAD >/dev/null 2>&1; then
        log_error "Fetch succeeded but no FETCH_HEAD was created."
        log_error "The remote repository may be empty or misconfigured."
        return 1
    fi

    # Skip reset if already at the same commit
    local local_head remote_head
    local_head=$(git rev-parse HEAD 2>/dev/null)
    remote_head=$(git rev-parse FETCH_HEAD 2>/dev/null)
    if [ "$local_head" = "$remote_head" ]; then
        log_info "Already up to date (latest dev)."
        # Return 2 to signal "no changes" (distinct from 0=updated, 1=error)
        return 2
    fi

    if ! git reset --hard FETCH_HEAD; then
        log_error "Failed to reset to latest main branch."
        log_error "Your working tree may be in an inconsistent state. Run 'git status' in $harbor_home to inspect."
        return 1
    fi
    if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
        if ! git checkout -B main FETCH_HEAD; then
            log_error "Failed to switch to main branch."
            log_error "Run 'git status' in $harbor_home to inspect."
            return 1
        fi
    fi
}

resolve_harbor_version() {
    local response version
    response=$(curl -fsSL "$harbor_release_url" 2>/dev/null) || {
        log_warn "Failed to fetch latest release info from $harbor_release_url" >&2
        return 1
    }
    if command -v jq >/dev/null 2>&1; then
        version=$(printf '%s\n' "$response" | jq -r '.tag_name // empty' 2>/dev/null)
    else
        version=$(printf '%s\n' "$response" | sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n1)
    fi
    if [ -z "$version" ]; then
        log_warn "Could not parse version from GitHub API response" >&2
        return 1
    fi
    printf '%s\n' "$version"
}

update_harbor() {
    local is_latest=false
    local old_version="$version"

    case "$1" in
    --latest | -l)
        is_latest=true
        ;;
    esac

    # Same-version skip: if already on the target version, avoid the full fetch/checkout cycle
    local target_version=""
    if $is_latest; then
        : # --latest always fetches (no way to know if remote has new commits without fetching)
    else
        local current_tag
        current_tag=$(git describe --tags --exact-match HEAD 2>/dev/null)
        if [ -n "$current_tag" ]; then
            target_version=$(resolve_harbor_version)
            if [ -z "$target_version" ]; then
                log_error "Could not determine the latest Harbor version."
                log_error "Check your internet connection and try again."
                return 1
            fi
            if [ "$current_tag" = "$target_version" ]; then
                log_info "Already up to date ($target_version)."
                return 0
            fi
        fi
    fi

    # Warn about running services before updating — compose files may change between versions
    local running_services
    running_services=$(docker compose ps --services --filter "status=running" 2>/dev/null | tr '\n' ' ')
    if [ -n "$running_services" ]; then
        log_warn "Running services detected: $running_services"
        log_warn "Compose files may change between versions. Stop services first with 'harbor down'"
        log_warn "or restart them after update with 'harbor restart'."
    fi

    # Stash user-modified override.env files so checkout/reset doesn't fail or destroy them
    local had_stash=false
    if ! git diff --quiet -- 'services/*/override.env' 2>/dev/null; then
        git stash push --quiet -- 'services/*/override.env' 2>/dev/null && had_stash=true
    fi

    # Helper to restore stashed override.env files on error
    _restore_stash_on_error() {
        if [ "$had_stash" = true ]; then
            git stash pop --quiet 2>/dev/null || true
        fi
        # Provide rollback hint using the old version
        if [ -n "$old_version" ]; then
            log_info "To roll back, run: cd $harbor_home && git checkout tags/v$old_version"
        fi
    }

    local did_update=true
    if $is_latest; then
        log_info "Updating to the latest dev version..."
        local update_rc=0
        unsafe_update || update_rc=$?
        if [ "$update_rc" -eq 1 ]; then
            _restore_stash_on_error
            return 1
        elif [ "$update_rc" -eq 2 ]; then
            # Already up to date — restore stash and skip merge/migrate
            did_update=false
        fi
    else
        # target_version was already resolved in the same-version check above,
        # but if we skipped that check (e.g., not on an exact tag), resolve now
        if [ -z "${target_version:-}" ]; then
            target_version=$(resolve_harbor_version)
        fi
        if [ -z "$target_version" ]; then
            log_error "Could not determine the latest Harbor version."
            log_error "Check your internet connection and try again."
            _restore_stash_on_error
            return 1
        fi
        harbor_version="$target_version"
        log_info "Updating to version $harbor_version..."
        if ! git fetch --all --tags; then
            log_error "Failed to fetch updates from the remote repository."
            log_error "Check your internet connection and try again."
            _restore_stash_on_error
            return 1
        fi
        if ! git checkout "tags/$harbor_version"; then
            log_error "Failed to check out version $harbor_version."
            log_error "This version tag may not exist. Check available versions at https://github.com/av/harbor/releases"
            _restore_stash_on_error
            return 1
        fi
    fi

    if [ "$had_stash" = true ]; then
        git stash pop --quiet 2>/dev/null || {
            log_warn "Could not auto-restore override.env changes (merge conflict)."
            log_warn "Your overrides are saved in 'git stash'. Recover manually:"
            log_warn "  cd $harbor_home && git stash show -p | git apply --3way"
            log_warn "Or restore individual override.env files from 'git stash list'."
        }
    fi

    # Skip merge/migrate/success message if nothing changed
    if [ "$did_update" = false ]; then
        return 0
    fi

    log_info "Merging .env files..."
    if ! merge_env_files; then
        log_warn "Config merge encountered issues. Your .env may need manual review."
        log_warn "Run 'harbor config update' to retry, or compare with profiles/default.env"
        if [ -n "$old_version" ]; then
            log_warn "To roll back: cd $harbor_home && git checkout tags/v$old_version"
        fi
    fi

    log_info "Running config migrations..."
    if ! run_migrate_command; then
        log_warn "Config migration encountered issues."
        log_warn "Run 'harbor migrate --dry-run' to preview and 'harbor migrate' to retry."
        if [ -n "$old_version" ]; then
            log_warn "To roll back: cd $harbor_home && git checkout tags/v$old_version"
        fi
    fi

    # Read the new version from the updated script on disk
    local new_version
    new_version=$(grep '^version="' "$harbor_home/harbor.sh" 2>/dev/null | head -1 | cut -d'"' -f2)
    if [ -n "$new_version" ]; then
        log_info "Harbor updated successfully: $old_version -> $new_version"
    else
        log_info "Harbor updated successfully."
    fi
}

run_migrate_command() {
    case "$1" in
    -h | --help | help)
        echo "Harbor Migration Tool"
        echo
        echo "Usage: harbor migrate [options]"
        echo
        echo "Options:"
        echo "  --dry-run           Preview migration without making changes"
        echo "  --target <version>  Override target Harbor version"
        echo "  -h, --help          Show this help message"
        echo
        echo "This command migrates your Harbor configuration schema to the current Harbor version."
        ;;
    *)
        log_debug "Running migration script"
        local target_config_version
        target_config_version=$(grep '^HARBOR_CONFIG_VERSION=' "$default_profile" | cut -d '=' -f2-)
        target_config_version="${target_config_version#\"}"
        target_config_version="${target_config_version%\"}"

        if [[ -z "$target_config_version" ]]; then
            # Read version from the on-disk script, not $version which may be stale after self-update
            target_config_version=$(grep '^version="' "$harbor_home/harbor.sh" 2>/dev/null | head -1 | cut -d'"' -f2)
            if [[ -z "$target_config_version" ]]; then
                target_config_version="$version"
            fi
        fi

        if command -v deno &>/dev/null; then
            deno run -A --unstable-sloppy-imports "$harbor_home/.scripts/migrate.ts" --target "$target_config_version" "$@"
        elif command -v docker &>/dev/null; then
            log_debug "deno not found, running migration in container"
            docker run --rm \
                -v "$harbor_home:$harbor_home" \
                -v harbor-deno-cache:/deno-dir:rw \
                -w "$harbor_home" \
                denoland/deno:distroless \
                run -A --unstable-sloppy-imports \
                "./.scripts/migrate.ts" --target "$target_config_version" "$@"
        else
            log_warn "Neither deno nor docker available to run config migrations."
            log_warn "Install deno (https://deno.land) or ensure Docker is running, then run: harbor migrate"
            return 1
        fi
        ;;
    esac
}

get_active_services() {
    local services
    services=$(docker compose ps --format "{{.Service}}")
    local valid_services=()
    for s in $services; do
        if service_compose_exists "$s"; then
            # Deduplicate by checking if it is already in valid_services
            local found=0
            for v in "${valid_services[@]}"; do
                if [[ "$v" == "$s" ]]; then
                    found=1
                    break
                fi
            done
            if [[ $found -eq 0 ]]; then
                valid_services+=("$s")
            fi
        fi
    done
    echo "${valid_services[@]}"
}

is_service_running() {
    if docker compose ps --services --filter "status=running" | grep -q "^$1$"; then
        return 0
    else
        return 1
    fi
}

get_services() {
    local is_active=false
    local is_silent=false
    local filtered_args=()

    for arg in "$@"; do
        case "$arg" in
        --silent | -s)
            is_silent=true
            ;;
        --active | -a)
            is_active=true
            ;;
        *)
            filtered_args+=("$arg") # Add to filtered arguments
            ;;
        esac
    done

    if $is_active; then
        local active_services=$(docker compose ps --format "{{.Service}}")

        if [ -z "$active_services" ]; then
            log_warn "Harbor has no active services."
        else
            $is_silent || log_info "Harbor active services:"
            echo "$active_services"
        fi
    else
        $is_silent || log_info "Harbor services:"
        $(compose_with_options "*") config --services
    fi
}

get_ip() {
    # Try ip command first (Linux)
    if command -v ip >/dev/null 2>&1; then
        ip route get 1 | awk '{print $7; exit}'
        return
    fi

    # Fallback to ifconfig (macOS, older Linux)
    if command -v ifconfig >/dev/null 2>&1; then
        ifconfig | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -n1
        return
    fi

    # Last resort: hostname -I (GNU/Linux) or ipconfig getifaddr (macOS)
    if hostname -I >/dev/null 2>&1; then
        hostname -I | awk '{print $1}'
    elif command -v ipconfig >/dev/null 2>&1; then
        # macOS: ipconfig getifaddr returns the IP for a given interface
        ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1"
    else
        echo "127.0.0.1"
    fi
}

extract_tunnel_url() {
    # cloudflared emits the URL inside a boxed table row; match the URL
    # literal itself with POSIX ERE (BSD/BusyBox grep do not support PCRE).
    grep -Eo 'https://[A-Za-z0-9.-]+\.trycloudflare\.com' | head -n1
}

establish_tunnel() {
    case $1 in
    down | stop | d | s)
        echo "Stopping all tunnels"
        docker stop $(docker ps -q --filter "name=cfd.tunnel") || true
        exit 0
        ;;
    esac

    local intra_url=$(get_url -i "$@")
    local container_name=$(get_container_name "cfd.tunnel.$(date +%s)")
    local tunnel_url=""

    log_info "Starting new tunnel"
    log_info "Container name: $container_name"
    log_info "Intra URL: $intra_url"
    $(compose_with_options "cfd") run --rm -d --name "$container_name" cfd --url "$intra_url" || {
        log_error "Failed to start container"
        exit 1
    }

    local timeout=60
    local elapsed=0
    while [ -z "$tunnel_url" ] && [ $elapsed -lt $timeout ]; do
        sleep 1
        log_info "Waiting for tunnel URL..."
        tunnel_url=$(docker logs -n 200 $container_name 2>&1 | extract_tunnel_url) || true
        elapsed=$((elapsed + 1))
    done

    if [ -z "$tunnel_url" ]; then
        log_error "Failed to obtain tunnel URL within $timeout seconds"
        docker stop "$container_name" || true
        exit 1
    fi

    log_info "Tunnel URL: $tunnel_url"
    print_qr "$tunnel_url" || {
        log_error "Failed to print QR code"
        exit 1
    }
}

record_history_entry() {
    local file="$1"
    local max_entries="$2"
    local input="harbor $3"

    # Check if the input already exists in the file
    if ! grep -Fxq -- "$input" "$file" 2>/dev/null; then
        log_debug "Recording history entry: '$file', '$max_entries', '$input'"

        printf '%s\n' "$input" >>"$file"

        # If we've exceeded max entries, remove oldest entries.
        # BSD wc left-pads the count — strip whitespace before integer compare.
        if [ "$(wc -l <"$file" | tr -d ' ')" -gt "$max_entries" ]; then
            local history_dir
            local temp_file
            history_dir=$(dirname "$file")
            temp_file=$(mktemp "$history_dir/harbor-history.XXXXXX") || return 0

            if tail -n "$max_entries" "$file" >"$temp_file"; then
                mv "$temp_file" "$file"
            else
                rm -f "$temp_file"
            fi
        fi
    fi
}

run_history() {
    case "$1" in
    ls | list)
        shift
        cat "$default_history_file"
        ;;
    size)
        shift
        env_manager_alias history.size "$@"
        ;;
    clear)
        log_info "Clearing history"
        echo "" >"$default_history_file"
        ;;
    --help | -h)
        echo "Harbor history management"
        echo
        echo "Usage: harbor history {ls|size|clear}"
        echo
        echo "Commands:"
        echo "  ls|list - List all history entries"
        echo "  size    - Get or set the maximum number of history entries"
        echo "  clear   - Clear all history entries"
        return 0
        ;;
    *)
        local max_entries=10
        local history_file="$default_history_file"
        local tmp_dir=$(mktemp -d -t harbor.XXXXXX)
        local services=$(get_active_services)

        local output_file="$tmp_dir/selected_command.txt"
        local entrypoint="/bin/sh -c \"/usr/local/bin/gum filter < ${history_file} > /tmp/gum_test/selected_command.txt\""

        $(compose_with_options $services "gum") run \
            --rm \
            -it \
            -e "TERM=xterm-256color" \
            -v "$harbor_home:$harbor_home" \
            -v "$tmp_dir:/tmp/gum_test" \
            --workdir "$harbor_home" \
            --entrypoint "$entrypoint" \
            gum

        if [ -s "$output_file" ]; then
            log_debug "Selected command: $(cat "$output_file")"
            eval "$(cat "$output_file")"
        else
            log_info "No command selected"
        fi

        rm -rf "$tmp_dir"
        ;;
    esac
}

run_harbor_size() {
    local cache_dirs dir size

    cache_dirs=$(harbor config ls | awk -v home="$HOME" '
        NF < 2 { next }
        $1 ~ /CACHE/ || ($1 ~ /WORKSPACE/ && $1 !~ /WORKSPACES/) {
            path=$NF
            sub(/^~/, home, path)
            print path
        }
    ')
    # Add $(harbor home) to the list
    cache_dirs+=$'\n'"$(harbor home)"

    # Print header
    echo "Harbor size:"
    echo "----------------------"

    # Iterate through each directory and print its size
    while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        [ -d "$dir" ] || continue

        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        echo "$dir: $size"
    done <<<"$cache_dirs"
}

run_harbor_env() {
    local service=$1

    # Check folder
    if [ -z "$service" ]; then
        log_error "Please provide a service name."
        return 1
    fi

    shift
    local mgr_cmd="ls"
    local env_var=""
    local env_val=""

    case "$1" in
    get|set|ls|list|search|find|unset|rm|remove)
        mgr_cmd=$1
        env_var=$2
        shift 2
        env_val="$*"
        ;;
    "")
        ;;
    *)
        env_var=$1
        shift
        if [ $# -gt 0 ]; then
            mgr_cmd="set"
            env_val="$*"
        else
            mgr_cmd="get"
        fi
        ;;
    esac

    local env_file="services/$service/override.env"

    log_debug "'env' $env_file - $mgr_cmd $env_var $env_val"

    if [ ! -f "$env_file" ]; then
        log_error "Unknown service: $service. Please provide a valid service name."
        return 1
    fi

    if [ -n "$env_val" ]; then
        env_manager --env-file "$env_file" --prefix "" "$mgr_cmd" "$env_var" "$env_val"
    elif [ -n "$env_var" ]; then
        env_manager --env-file "$env_file" --prefix "" "$mgr_cmd" "$env_var"
    else
        env_manager --env-file "$env_file" --prefix "" "$mgr_cmd"
    fi
}

# Corresponds to the ".scripts" folder
run_harbor_dev() {
    local use_container=false
    local filtered_args=()

    if ! command -v deno &>/dev/null; then
        use_container=true
    fi

    for arg in "$@"; do
        case "$arg" in
        --container)
            use_container=true
            ;;
        *)
            filtered_args+=("$arg") # Add to filtered arguments
            ;;
        esac
    done

    local script="${filtered_args[0]}"
    local script_args=("${filtered_args[@]:1}")

    if $use_container; then
        log_debug "running in container: $script"
        docker run --rm \
            -v "$harbor_home:$harbor_home" \
            -v harbor-deno-cache:/deno-dir:rw \
            -w "$harbor_home" \
            denoland/deno:distroless \
            run -A --unstable-sloppy-imports \
            "./.scripts/$script.ts" "${script_args[@]}"
    else
        log_debug "running on host: $script"
        deno run -A --unstable-sloppy-imports "./.scripts/$script.ts" "${script_args[@]}"
    fi
}

run_harbor_tools() {
    run_routine manageTools "$@"
}

# shellcheck disable=SC2034
__anchor_service_clis=true

run_gum() {
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        if [ "$1" = "confirm" ]; then
            return 1
        fi
        log_error "gum requires a TTY"
        return 1
    fi
    docker run --rm -it -e "TERM=xterm-256color" $default_gum_image "$@"
}

run_dive() {
    local dive_image=wagoodman/dive
    docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock $dive_image "$@"
}

run_av_tools() {
    docker run --rm -it -p 6274:6274 -p 6277:6277 -v cache:/app/cache ghcr.io/av/tools:latest "$@"
}

run_llamacpp_command() {
    update_model_spec() {
        local spec=""
        local current_model=$(env_manager get llamacpp.model)
        local current_gguf=$(env_manager get llamacpp.gguf)

        if [ -n "$current_model" ]; then
            spec=$(hf_url_2_llama_spec $current_model)
        else
            spec="-m $current_gguf"
        fi

        env_manager set llamacpp.model.specifier "$spec"
    }

    case "$1" in
    models|ls)
        shift
        curl -s $(harbor url llamacpp)/models | jq -r '.data[].id'
        ;;
    model)
        shift
        env_manager_alias llamacpp.model --on-set update_model_spec "$@"
        ;;
    gguf)
        shift
        env_manager_alias llamacpp.gguf --on-set update_model_spec "$@"
        ;;
    args)
        shift
        env_manager_alias llamacpp.extra.args "$@"
        ;;
    build)
        shift
        case "$1" in
        on)
            local current_caps=$(env_manager get capabilities.default)
            if [[ ! ";${current_caps};" =~ ";build;" ]]; then
                if [ -z "$current_caps" ]; then
                    env_manager set capabilities.default "build"
                else
                    env_manager set capabilities.default "${current_caps};build"
                fi
            fi
            log_info "Build from source enabled for llamacpp"
            log_info "Run 'harbor build llamacpp' to build, then 'harbor up llamacpp'"
            ;;
        off)
            local current_caps=$(env_manager get capabilities.default)
            local new_caps=$(echo "$current_caps" | sed 's/;*build//g; s/^;//; s/;$//')
            env_manager set capabilities.default "$new_caps"
            log_info "Build from source disabled for llamacpp"
            ;;
        ref)
            shift
            env_manager_alias llamacpp.build.ref "$@"
            ;;
        *)
            echo "Usage: harbor llamacpp build <command>"
            echo
            echo "Commands:"
            echo "  on              - Enable building llamacpp from source"
            echo "  off             - Disable building from source (use pre-built images)"
            echo "  ref [git ref]   - Get or set git ref to build (branch/tag/commit)"
            ;;
        esac
        ;;
    -h | --help | help)
        echo "Please note that this is not llama.cpp CLI, but a Harbor CLI to manage llama.cpp service."
        echo "Access llama.cpp own CLI by running 'harbor exec llamacpp' when it's running."
        echo
        echo "Usage: harbor llamacpp <command>"
        echo
        echo "Commands:"
        echo "  harbor llamacpp model [Hugging Face URL] - Get or set the llamacpp model to run"
        echo "  harbor llamacpp gguf [gguf path]         - Get or set the path to GGUF to run"
        echo "  harbor llamacpp args [args]              - Get or set extra args to pass to the llama.cpp CLI"
        echo "  harbor llamacpp build on|off|ref         - Manage building from source"
        ;;
    *)
        return 1
        ;;
    esac
}

run_ikllamacpp_command() {
    update_model_spec() {
        local spec=""
        local current_model
        local current_gguf
        current_model=$(env_manager get ikllamacpp.model)
        current_gguf=$(env_manager get ikllamacpp.gguf)

        if [ -n "$current_model" ]; then
            spec=$(hf_url_2_llama_spec "$current_model")
        else
            spec="-m $current_gguf"
        fi

        env_manager set ikllamacpp.model.specifier "$spec"
    }

    case "$1" in
    models|ls)
        shift
        local base_url
        base_url=$(harbor url ikllamacpp)
        curl -s "${base_url}/v1/models" | jq -r '.data[].id'
        ;;
    model)
        shift
        env_manager_alias ikllamacpp.model --on-set update_model_spec "$@"
        ;;
    gguf)
        shift
        env_manager_alias ikllamacpp.gguf --on-set update_model_spec "$@"
        ;;
    args)
        shift
        env_manager_alias ikllamacpp.extra.args "$@"
        ;;
    build)
        shift
        case "$1" in
        on)
            local current_caps
            current_caps=$(env_manager get capabilities.default)
            if [[ ! ";${current_caps};" =~ ";build;" ]]; then
                if [ -z "$current_caps" ]; then
                    env_manager set capabilities.default "build"
                else
                    env_manager set capabilities.default "${current_caps};build"
                fi
            fi
            log_info "Build from source enabled for ikllamacpp"
            log_info "Run 'harbor build ikllamacpp' to build, then 'harbor up ikllamacpp'"
            ;;
        off)
            local current_caps
            local new_caps
            current_caps=$(env_manager get capabilities.default)
            new_caps=$(echo "$current_caps" | sed 's/;*build//g; s/^;//; s/;$//')
            env_manager set capabilities.default "$new_caps"
            log_info "Build from source disabled for ikllamacpp"
            ;;
        ref)
            shift
            env_manager_alias ikllamacpp.build.ref "$@"
            ;;
        *)
            echo "Usage: harbor ikllamacpp build <command>"
            echo
            echo "Commands:"
            echo "  on              - Enable ikllamacpp source builds"
            echo "  off             - Disable source builds (use pre-built images)"
            echo "  ref [git ref]   - Get or set git ref to build (branch/tag/commit)"
            ;;
        esac
        ;;
    -h | --help | help)
        echo "Please note that this is not ik_llama.cpp CLI, but a Harbor CLI to manage ikllamacpp service."
        echo "Access ik_llama.cpp own CLI by running 'harbor exec ikllamacpp' when it's running."
        echo
        echo "Usage: harbor ikllamacpp <command>"
        echo
        echo "Commands:"
        echo "  harbor ikllamacpp models                     - List models served by ik_llama.cpp"
        echo "  harbor ikllamacpp model [Hugging Face URL]   - Get or set the ikllamacpp model to run"
        echo "  harbor ikllamacpp gguf [gguf path]           - Get or set the path to GGUF to run"
        echo "  harbor ikllamacpp args [args]                - Get or set extra args to pass to the server"
        echo "  harbor ikllamacpp build on|off|ref           - Manage building from source"
        ;;
    *)
        return 1
        ;;
    esac
}

run_tgi_command() {
    update_model_spec() {
        local spec=""
        local current_model=$(env_manager get tgi.model)
        local current_quant=$(env_manager get tgi.quant)
        local current_revision=$(env_manager get tgi.revision)

        if [ -n "$current_model" ]; then
            spec="--model-id $current_model"
        fi

        if [ -n "$current_quant" ]; then
            spec="$spec --quantize $current_quant"
        fi

        if [ -n "$current_revision" ]; then
            spec="$spec --revision $current_revision"
        fi

        env_manager set tgi.model.specifier "$spec"
    }

    case "$1" in
    model)
        shift
        env_manager_alias tgi.model --on-set update_model_spec "$@"
        ;;
    args)
        shift
        env_manager_alias tgi.extra.args "$@"
        ;;
    quant)
        shift
        env_manager_alias tgi.quant --on-set update_model_spec "$@"
        ;;
    revision)
        shift
        env_manager_alias tgi.revision --on-set update_model_spec "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not TGI CLI, but a Harbor CLI to manage TGI service."
        echo "Access TGI own CLI by running 'harbor exec tgi' when it's running."
        echo
        echo "Usage: harbor tgi <command>"
        echo
        echo "Commands:"
        echo "  harbor tgi model [user/repo]   - Get or set the TGI model repository to run"
        echo "  harbor tgi quant"
        echo "    [awq|eetq|exl2|gptq|marlin|bitsandbytes|bitsandbytes-nf4|bitsandbytes-fp4|fp8]"
        echo "    Get or set the TGI quantization mode. Must match the contents of the model repository."
        echo "  harbor tgi revision [revision] - Get or set the TGI model revision to run"
        echo "  harbor tgi args [args]         - Get or set extra args to pass to the TGI CLI"
        ;;
    *)
        return 1
        ;;
    esac
}

run_litellm_command() {
    case "$1" in
    username)
        shift
        env_manager_alias litellm.ui.username "$@"
        ;;
    password)
        shift
        env_manager_alias litellm.ui.password "$@"
        ;;
    ui)
        shift
        if service_url=$(get_url litellm 2>&1); then
            sys_open "$service_url/ui"
        else
            log_error "Failed to get service URL for litellm: $service_url"
            exit 1
        fi
        ;;
    -h | --help | help)
        echo "Please note that this is not LiteLLM CLI, but a Harbor CLI to manage LiteLLM service."
        echo
        echo "Usage: harbor litellm <command>"
        echo
        echo "Commands:"
        echo "  harbor litellm username [username] - Get or set the LITeLLM UI username"
        echo "  harbor litellm password [username] - Get or set the LITeLLM UI password"
        echo "  harbor litellm ui                  - Open LiteLLM UI screen"
        ;;
    *)
        return 1
        ;;
    esac
}

run_hf_command() {
    case "$1" in
    parse-url)
        shift
        parse_hf_url "$@"
        return
        ;;
    token)
        shift
        env_manager_alias hf.token "$@"
        return
        ;;
    cache)
        shift
        env_manager_alias hf.cache "$@"
        return
        ;;
    dl)
        shift
        $(compose_with_options "hfdownloader") run --rm hfdownloader "$@"
        return
        ;;
    path)
        shift
        local found_path
        local spec="$1"

        if check_hf_cache "$1"; then
            found_path=$(run_hf_docker_cli download "$1")
            echo "$found_path"
        fi

        return
        ;;
    find)
        shift
        run_hf_open "$@"
        return
        ;;
    # Matching HF signature, but would love just "help"
    -h | --help)
        echo "Please note that this is a combination of Hugging Face"
        echo "CLI with additional Harbor-specific commands."
        echo
        echo "Harbor extensions:"
        echo "Usage: harbor hf <command>"
        echo
        echo "Commands:"
        echo "  harbor hf token [token]    - Get or set the Hugging Face API token"
        echo "  harbor hf cache            - Get or set the location of Hugging Face cache"
        echo "  harbor hf dl [args]        - Download a model from Hugging Face"
        echo "  harbor hf path [user/repo] - Resolve the path to a model dir in HF cache"
        echo "  harbor hf find [query]     - Search for a model on Hugging Face"
        echo
        echo "Original CLI help:"
        ;;
    esac

    run_hf_docker_cli "$@"
}

show_models_help() {
    echo "Manage models across Ollama, HuggingFace, llama.cpp, DMR, MLX, and oMLX"
    echo ""
    echo "Usage: harbor models <command> [options]"
    echo ""
    echo "Commands:"
    echo "  ls [--json] [--source SOURCE]  List models"
    echo "  pull [--source SOURCE] <model> Download a model"
    echo "  rm [--source SOURCE] <model>   Remove a model"
    echo "  <source> <command> ...         Alias for --source SOURCE"
    echo ""
    echo "Sources: ollama, hf, llamacpp, dmr, mlx, omlx"
    echo ""
    echo "Examples:"
    echo "  harbor models ls"
    echo "  harbor models ls --source dmr"
    echo "  harbor models ls --json"
    echo "  harbor models pull qwen3:8b"
    echo "  harbor models pull --source dmr ai/smollm2"
    echo "  harbor models pull --source mlx mlx-community/Qwen3.5-4B-4bit"
    echo "  harbor models pull --source omlx mlx-community/Qwen3.5-4B-4bit"
    echo "  harbor models pull bartowski/Llama-3.2-1B-Instruct-GGUF"
    echo "  harbor models rm qwen3:8b"
}

config_bool_enabled() {
    case "$(harbor_lower "$1")" in
    1 | true | yes | on)
        return 0
        ;;
    esac

    return 1
}

harbor_resolve_path() {
    local path="$1"
    path="${path/#\~/$HOME}"

    case "$path" in
    /*)
        echo "$path"
        ;;
    ./*)
        echo "$harbor_home/${path#./}"
        ;;
    *)
        echo "$harbor_home/$path"
        ;;
    esac
}

sed_replacement_escape() {
    printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

docker_cli_subcommand_available() {
    local subcommand="$1"
    command -v docker >/dev/null 2>&1 && docker "$subcommand" --help 2>&1 | grep -q "Usage:  docker $subcommand"
}

docker_model_subcommand_available() {
    local subcommand="$1"
    docker_cli_subcommand_available model && docker model "$subcommand" --help 2>&1 | grep -q "docker model $subcommand"
}

docker_model_available() {
    docker_cli_subcommand_available model
}

run_privileged_install_command() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        if ! command -v sudo >/dev/null 2>&1; then
            log_error "sudo is required to install host packages automatically."
            return 1
        fi
        sudo "$@"
    fi
}

dmr_install_linux_plugin() {
    if command -v apt-get >/dev/null 2>&1; then
        log_info "Installing Docker Model Runner plugin with apt."
        run_privileged_install_command apt-get update
        run_privileged_install_command apt-get install -y docker-model-plugin
        return
    fi

    if command -v dnf >/dev/null 2>&1; then
        log_info "Installing Docker Model Runner plugin with dnf."
        run_privileged_install_command dnf install -y docker-model-plugin
        return
    fi

    log_error "Docker Model Runner CLI is missing and automatic installation is only supported through apt or dnf on Linux."
    return 1
}

dmr_desktop_enable_available() {
    docker_cli_subcommand_available desktop && docker desktop enable model-runner --help 2>&1 | grep -q 'model-runner'
}

dmr_install_components() {
    if docker_model_available; then
        return 0
    fi

    log_info "Docker Model Runner CLI is missing; attempting to install or enable it."

    if [[ "$(uname -s)" == "Linux" ]]; then
        dmr_install_linux_plugin || return 1
    elif dmr_desktop_enable_available; then
        docker desktop enable model-runner || return 1
    else
        log_error "Docker Model Runner CLI is not available. Install/update Docker Desktop or install docker-model-plugin, then retry."
        return 1
    fi

    if ! docker_model_available; then
        log_error "Docker Model Runner CLI is still unavailable after automatic setup."
        return 1
    fi
}

dmr_install_runner() {
    if docker model status >/dev/null 2>&1; then
        return 0
    fi

    if docker_model_subcommand_available install-runner; then
        log_info "Installing Docker Model Runner runtime."
        docker model install-runner || return 1
    fi
}

dmr_host_start() {
    local manage_host enable_tcp auto_pull runner_port model

    manage_host=$(env_manager get dmr.manage.host)
    if ! config_bool_enabled "$manage_host"; then
        log_info "DMR host management is disabled; expecting Docker Model Runner at $(env_manager get dmr.upstream.url)."
        return 0
    fi

    dmr_install_components || return 1
    dmr_install_runner || return 1

    enable_tcp=$(env_manager get dmr.enable.tcp)
    runner_port=$(env_manager get dmr.runner.port)
    if config_bool_enabled "$enable_tcp"; then
        if docker desktop enable model-runner --tcp="$runner_port" >/dev/null 2>&1; then
            log_info "Docker Model Runner TCP endpoint enabled on port $runner_port."
        else
            log_warn "Could not enable Docker Model Runner TCP endpoint automatically; continuing with existing Docker Desktop configuration."
        fi
    fi

    auto_pull=$(env_manager get dmr.auto.pull)
    model=$(env_manager get dmr.model)
    if config_bool_enabled "$auto_pull" && [ -n "$model" ]; then
        if docker model inspect "$model" >/dev/null 2>&1; then
            log_debug "DMR model already present: $model"
        else
            log_info "Pulling DMR model: $model"
            docker model pull "$model"
        fi
    fi
}

dmr_host_stop() {
    if docker model ps --format '{{.ModelName}}' 2>/dev/null | grep -q .; then
        log_info "Unloading running DMR models..."
        docker model unload --all || true
    fi
}

mlx_workspace_path() {
    harbor_resolve_path "$(env_manager get mlx.workspace)"
}

mlx_uv_run() {
    (cd "$(mlx_workspace_path)" && uv run "$@")
}

mlx_host_start() {
    local manage_host workspace

    manage_host=$(env_manager get mlx.manage.host)
    if ! config_bool_enabled "$manage_host"; then
        log_info "MLX host management is disabled; expecting mlx-lm at $(env_manager get mlx.upstream.url)."
        return 0
    fi

    workspace=$(mlx_workspace_path)
    mkdir -p "$workspace/logs"

    local runner_port hf_path logfile local_url
    runner_port=$(env_manager get mlx.runner.port)
    hf_path=$(env_manager get mlx.hf.path)
    logfile="$workspace/logs/mlx-lm.log"
    local_url="http://localhost:$runner_port"

    if curl -s -o /dev/null -w '' "$local_url/v1/models" 2>/dev/null; then
        log_info "mlx-lm is already running on port $runner_port"
    else
        log_info "Starting mlx-lm from $workspace (model: $hf_path)"
        (cd "$workspace" && nohup uv run python -m mlx_lm.server --model "$hf_path" --port "$runner_port" >>"$logfile" 2>&1 & disown)

        local retries=0 max_retries=60
        while ! curl -s -o /dev/null -w '' "$local_url/v1/models" 2>/dev/null; do
            retries=$((retries + 1))
            if [ "$retries" -ge "$max_retries" ]; then
                log_error "mlx-lm failed to start within ${max_retries}s. Check $logfile"
                return 1
            fi
            sleep 1
        done
        log_info "mlx-lm is ready on port $runner_port"
    fi
}

mlx_host_stop() {
    local manage_host runner_port pids

    manage_host=$(env_manager get mlx.manage.host)
    if ! config_bool_enabled "$manage_host"; then
        return 0
    fi

    runner_port=$(env_manager get mlx.runner.port)
    pids=$(lsof -ti "tcp:$runner_port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        log_info "Stopping mlx-lm (port $runner_port)"
        echo "$pids" | xargs kill 2>/dev/null || true
    else
        log_debug "No mlx-lm process found on port $runner_port"
    fi
}

omlx_workspace_path() {
    harbor_resolve_path "$(env_manager get omlx.workspace)"
}

omlx_base_path() {
    harbor_resolve_path "$(env_manager get omlx.base.path)"
}

omlx_model_dir_path() {
    harbor_resolve_path "$(env_manager get omlx.model.dir)"
}

omlx_cache_dir_path() {
    harbor_resolve_path "$(env_manager get omlx.cache.dir)"
}

omlx_uv_run() {
    (cd "$(omlx_workspace_path)" && uv run "$@")
}

omlx_curl() {
    local url="$1"
    shift || true
    local api_key
    api_key=$(env_manager get omlx.api.key)

    if [ -n "$api_key" ]; then
        curl "$@" -H "Authorization: Bearer $api_key" "$url"
    else
        curl "$@" "$url"
    fi
}

omlx_host_start() {
    local manage_host workspace base_path model_dir cache_dir

    manage_host=$(env_manager get omlx.manage.host)
    if ! config_bool_enabled "$manage_host"; then
        log_info "oMLX host management is disabled; expecting oMLX at $(env_manager get omlx.upstream.url)."
        return 0
    fi

    workspace=$(omlx_workspace_path)
    base_path=$(omlx_base_path)
    model_dir=$(omlx_model_dir_path)
    cache_dir=$(omlx_cache_dir_path)
    mkdir -p "$workspace/logs" "$base_path" "$model_dir" "$cache_dir"

    local runner_port logfile local_url api_key extra_args
    runner_port=$(env_manager get omlx.runner.port)
    logfile="$workspace/logs/omlx.log"
    local_url="http://localhost:$runner_port"
    api_key=$(env_manager get omlx.api.key)
    extra_args=$(env_manager get omlx.extra.args)

    if omlx_curl "$local_url/v1/models" -s -o /dev/null -w '' 2>/dev/null; then
        log_info "oMLX is already running on port $runner_port"
    else
        log_info "Starting oMLX from $workspace (models: $model_dir)"
        local cmd=(uv run omlx serve --model-dir "$model_dir" --host 127.0.0.1 --port "$runner_port" --base-path "$base_path" --paged-ssd-cache-dir "$cache_dir")
        if [ -n "$api_key" ]; then
            cmd+=(--api-key "$api_key")
        fi
        if [ -n "$extra_args" ]; then
            local extra_args_array=()
            read -r -a extra_args_array <<< "$extra_args"
            cmd+=("${extra_args_array[@]}")
        fi
        (cd "$workspace" && nohup "${cmd[@]}" >>"$logfile" 2>&1 & disown)

        local retries=0 max_retries=60
        while ! omlx_curl "$local_url/v1/models" -s -o /dev/null -w '' 2>/dev/null; do
            retries=$((retries + 1))
            if [ "$retries" -ge "$max_retries" ]; then
                log_error "oMLX failed to start within ${max_retries}s. Check $logfile"
                return 1
            fi
            sleep 1
        done
        log_info "oMLX is ready on port $runner_port"
    fi
}

omlx_host_stop() {
    local manage_host runner_port pids

    manage_host=$(env_manager get omlx.manage.host)
    if ! config_bool_enabled "$manage_host"; then
        return 0
    fi

    runner_port=$(env_manager get omlx.runner.port)
    pids=$(lsof -ti "tcp:$runner_port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        log_info "Stopping oMLX (port $runner_port)"
        echo "$pids" | xargs kill 2>/dev/null || true
    else
        log_debug "No oMLX process found on port $runner_port"
    fi
}

run_models_routine() {
    local requested_source=""
    local arg
    local prev_was_source=false
    for arg in "$@"; do
        if $prev_was_source; then
            requested_source="$arg"
            prev_was_source=false
            continue
        fi
        case "$arg" in
        --source | -s)
            prev_was_source=true
            ;;
        esac
    done

    local hf_cache
    hf_cache=$(env_manager get hf.cache)
    hf_cache="${hf_cache/#\~/$HOME}"
    local ollama_url
    ollama_url=$(env_manager get ollama.internal.url)
    local llamacpp_cache
    llamacpp_cache=$(env_manager get llamacpp.cache)
    llamacpp_cache="${llamacpp_cache/#\~/$HOME}"
    local dmr_url=""
    if [ "$requested_source" = "dmr" ]; then
        dmr_url=$(env_manager get dmr.upstream.url)
        case "${dmr_url%/}" in
        */engines)
            dmr_url="${dmr_url%/}"
            ;;
        *)
            dmr_url="${dmr_url%/}/engines"
            ;;
        esac
    elif is_service_running "dmr"; then
        dmr_url="http://dmr:8080"
    fi
    local mlx_url=""
    if [ "$requested_source" = "mlx" ]; then
        mlx_url=$(env_manager get mlx.upstream.url)
    elif is_service_running "mlx"; then
        mlx_url="http://mlx:8080"
    fi
    local omlx_url=""
    if [ "$requested_source" = "omlx" ]; then
        omlx_url=$(env_manager get omlx.upstream.url)
    elif is_service_running "omlx"; then
        omlx_url="http://omlx:8080"
    fi
    local dmr_api_key omlx_api_key
    dmr_api_key=$(env_manager get dmr.api.key)
    omlx_api_key=$(env_manager get omlx.api.key)

    if { [ -z "$requested_source" ] || [ "$requested_source" = "ollama" ]; } && ! is_service_running "ollama"; then
        log_debug "Ollama is not running, launching..."
        run_up --no-defaults ollama
    fi

    docker run --rm \
        --network=harbor_harbor-network \
        --add-host "host.docker.internal:host-gateway" \
        --add-host "model-runner.docker.internal:host-gateway" \
        -v "$harbor_home:$harbor_home" \
        -v "$hf_cache:$hf_cache:rw" \
        -v "$llamacpp_cache:$llamacpp_cache:rw" \
        -v harbor-deno-cache:/deno-dir:rw \
        -w "$harbor_home" \
        -e "HARBOR_LOG_LEVEL=$default_log_level" \
        -e "HARBOR_COMPOSE_CACHE=$HARBOR_COMPOSE_CACHE" \
        -e "HARBOR_HF_CACHE=$hf_cache" \
        -e "HARBOR_OLLAMA_URL=$ollama_url" \
        -e "HARBOR_LLAMACPP_CACHE=$llamacpp_cache" \
        -e "HARBOR_DMR_URL=$dmr_url" \
        -e "HARBOR_MLX_URL=$mlx_url" \
        -e "HARBOR_OMLX_URL=$omlx_url" \
        -e "HARBOR_DMR_API_KEY=$dmr_api_key" \
        -e "HARBOR_OMLX_API_KEY=$omlx_api_key" \
        $default_routine_runtime \
        ./routines/models.ts "$@"
}

run_models_pull() {
    local source=""
    if [ "$1" = "--source" ] || [ "$1" = "-s" ]; then
        source="$2"
        shift 2
    fi

    local model="$1"
    local repo="${model%:*}"

    case "$source" in
    dmr)
        run_dmr_command pull "$model"
        return
        ;;
    mlx)
        run_mlx_command pull "$model"
        return
        ;;
    omlx)
        run_omlx_command pull "$model"
        return
        ;;
    ollama)
        run_ollama_command pull "$model"
        return
        ;;
    hf)
        run_hf_docker_cli download "$model"
        return
        ;;
    llamacpp)
        run_llamacpp_pull "$model"
        return
        ;;
    "")
        ;;
    *)
        log_error "Unknown model source: $source"
        return 1
        ;;
    esac

    local hf_meta
    hf_meta=$(curl -sf --connect-timeout 5 "https://huggingface.co/api/models/$repo" 2>/dev/null) || true

    if [ -z "$hf_meta" ]; then
        run_ollama_command pull "$model"
        return
    fi

    local has_gguf
    has_gguf=$(echo "$hf_meta" | grep -o '"rfilename":"[^"]*\.gguf"' | head -1)

    if [ -n "$has_gguf" ]; then
        run_llamacpp_pull "$model"
    else
        run_hf_docker_cli download "$model"
    fi
}

models_extract_source_subcommand() {
    case "$1" in
    ollama | hf | llamacpp | dmr | mlx | omlx)
        echo "$1"
        return 0
        ;;
    esac

    return 1
}

run_models_command() {
    local source_subcommand=""

    if source_subcommand=$(models_extract_source_subcommand "$1" 2>/dev/null); then
        shift
        set -- "$1" "--source" "$source_subcommand" "${@:2}"
    fi

    case "$1" in
    ls|list)
        shift
        run_models_routine ls "$@"
        ;;
    pull)
        shift
        run_models_pull "$@"
        ;;
    rm|remove)
        shift
        if [ "$1" = "--source" ] || [ "$1" = "-s" ]; then
            local source="$2"
            shift 2
            case "$source" in
            dmr)
                run_dmr_command rm "$@"
                return
                ;;
            mlx)
                run_mlx_command rm "$@"
                return
                ;;
            omlx)
                run_omlx_command rm "$@"
                return
                ;;
            *)
                run_models_routine rm --source "$source" "$@"
                return
                ;;
            esac
        fi
        run_models_routine rm "$@"
        ;;
    -h|--help|help|"")
        show_models_help
        ;;
    *)
        log_error "Unknown models subcommand: $1"
        show_models_help
        exit 1
        ;;
    esac
}

run_dmr_command() {
    local cmd="${1:-help}"
    shift || true

    case "$cmd" in
    start | serve)
        dmr_host_start
        ;;
    stop)
        dmr_host_stop
        ;;
    status)
        docker model status
        ;;
    ls | list | models)
        docker model ls "$@"
        ;;
    pull)
        docker_model_available || { log_error "Docker Model Runner CLI is not available."; return 1; }
        docker model pull "$@"
        ;;
    rm | remove)
        docker_model_available || { log_error "Docker Model Runner CLI is not available."; return 1; }
        docker model rm "$@"
        ;;
    help | -h | --help)
        echo "Usage: harbor dmr <start|stop|status|ls|pull|rm>"
        echo "Manages Docker Model Runner for the Harbor dmr backend."
        ;;
    *)
        log_error "Unknown dmr subcommand: $cmd"
        return 1
        ;;
    esac
}

run_mlx_command() {
    local cmd="${1:-help}"
    shift || true
    local runner_port url
    runner_port="$(env_manager get mlx.runner.port)"
    url="http://localhost:$runner_port"

    case "$cmd" in
    start | serve)
        mlx_host_start
        ;;
    stop)
        mlx_host_stop
        ;;
    status)
        curl -fsS "$url/v1/models"
        ;;
    logs)
        local logfile
        logfile="$(mlx_workspace_path)/logs/mlx-lm.log"
        if [ -f "$logfile" ]; then
            cat "$logfile"
        else
            log_error "No log file found at $logfile"
        fi
        ;;
    pull)
        local hf_path="${1:-$(env_manager get mlx.hf.path)}"
        if [ -z "$hf_path" ]; then
            log_error "Usage: harbor mlx pull <hf_path>"
            return 1
        fi
        mlx_uv_run hf download "$hf_path"
        ;;
    rm | remove)
        log_error "Model removal is not supported. Manage the HuggingFace cache manually."
        return 1
        ;;
    ls | list | models)
        curl -fsS "$url/v1/models"
        ;;
    help | -h | --help)
        echo "Usage: harbor mlx <start|stop|status|logs|ls|pull|rm>"
        echo "Manages host mlx-lm for the Harbor mlx backend."
        ;;
    *)
        log_error "Unknown mlx subcommand: $cmd"
        return 1
        ;;
    esac
}

run_omlx_command() {
    local cmd="${1:-help}"
    shift || true
    local runner_port url
    runner_port="$(env_manager get omlx.runner.port)"
    url="http://localhost:$runner_port"

    case "$cmd" in
    start | serve)
        omlx_host_start
        ;;
    stop)
        omlx_host_stop
        ;;
    status)
        omlx_curl "$url/v1/models" -fsS
        ;;
    logs)
        local logfile
        logfile="$(omlx_workspace_path)/logs/omlx.log"
        if [ -f "$logfile" ]; then
            cat "$logfile"
        else
            log_error "No log file found at $logfile"
            return 1
        fi
        ;;
    pull)
        local hf_path="${1:-$(env_manager get omlx.hf.path)}"
        if [ -z "$hf_path" ]; then
            log_error "Usage: harbor omlx pull <hf_path>"
            return 1
        fi
        case "$hf_path" in
        /* | .. | ../* | */../* | */..)
            log_error "Invalid model path: $hf_path"
            return 1
            ;;
        esac
        local model_dir target_dir
        model_dir="$(omlx_model_dir_path)"
        target_dir="$model_dir/$hf_path"
        mkdir -p "$(dirname "$target_dir")"
        omlx_uv_run hf download "$hf_path" --local-dir "$target_dir"
        ;;
    rm | remove)
        local model="$1"
        if [ -z "$model" ]; then
            log_error "Usage: harbor omlx rm <model_dir_or_hf_path>"
            return 1
        fi
        case "$model" in
        /* | .. | ../* | */../* | */..)
            log_error "Invalid model path: $model"
            return 1
            ;;
        esac
        local model_dir target_dir
        model_dir="$(omlx_model_dir_path)"
        target_dir="$model_dir/$model"
        if [ ! -d "$target_dir" ]; then
            log_error "No oMLX model directory found at $target_dir"
            return 1
        fi
        rm -rf "$target_dir"
        log_info "Removed oMLX model directory: $target_dir"
        ;;
    ls | list | models)
        omlx_curl "$url/v1/models" -fsS
        ;;
    help | -h | --help)
        echo "Usage: harbor omlx <start|stop|status|logs|ls|pull|rm>"
        echo "Manages host oMLX for the Harbor omlx backend."
        ;;
    *)
        log_error "Unknown omlx subcommand: $cmd"
        return 1
        ;;
    esac
}

run_vllm_command() {
    update_model_spec() {
        local spec=""
        local current_model=$(env_manager get vllm.model)

        if [ -n "$current_model" ]; then
            spec="--model $current_model"
        fi

        env_manager set vllm.model.specifier "$spec"

        # Litellm model specifier for vLLM
        override_yaml_value ./litellm/litellm.vllm.yaml "model:" "openai/$current_model"
    }

    case "$1" in
    model)
        shift
        env_manager_alias vllm.model --on-set update_model_spec "$@"
        ;;
    args)
        shift
        env_manager_alias vllm.extra.args "$@"
        ;;
    version)
        shift
        env_manager_alias vllm.version "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not VLLM CLI, but a Harbor CLI to manage VLLM service."
        echo "Access VLLM own CLI by running 'harbor exec vllm' when it's running."
        echo
        echo "Usage: harbor vllm <command>"
        echo
        echo "Commands:"
        echo "  harbor vllm model [user/repo]   - Get or set the VLLM model repository to run"
        echo "  harbor vllm args [args]         - Get or set extra args to pass to the VLLM CLI"
        echo "  harbor vllm version [version]   - Get or set VLLM version (docker tag)"
        ;;
    *)
        return 1
        ;;
    esac
}

run_aphrodite_command() {
    case "$1" in
    model)
        shift
        env_manager_alias aphrodite.model "$@"
        ;;
    args)
        shift
        env_manager_alias aphrodite.extra.args "$@"
        ;;
    version)
        shift
        env_manager_alias aphrodite.version "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not Aphrodite CLI, but a Harbor CLI to manage Aphrodite service."
        echo "Access Aphrodite own CLI by running 'harbor exec aphrodite' when it's running."
        echo
        echo "Usage: harbor aphrodite <command>"
        echo
        echo "Commands:"
        echo "  harbor aphrodite model <user/repo>   - Get/set the Aphrodite model to run"
        echo "  harbor aphrodite args <args>         - Get/set extra args to pass to the Aphrodite CLI"
        echo "  harbor aphrodite version <version>   - Get/set Aphrodite version docker tag"
        ;;
    *)
        return 1
        ;;
    esac
}

run_opencode_command() {
    case "$1" in
    workspaces)
        shift
        env_manager_arr opencode.workspaces "$@"
        ;;
    -h | --help | help)
        echo "Usage: harbor opencode <command>"
        echo
        echo "Commands:"
        echo "  harbor opencode workspaces [ls|rm|add] - Manage workspace directories for OpenCode"
        echo "                                             Workspaces are mounted as /root/<name> in the container"
        ;;
    *)
        return 1
        ;;
    esac
}

run_facts_command() {
    local tty_opt=""
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        tty_opt="-T"
    fi

    $(compose_with_options --no-defaults "facts") run \
        $tty_opt \
        --rm \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        --entrypoint facts \
        facts "$@"
}

run_mi_command() {
    local tty_opt=""
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        tty_opt="-T"
    fi

    case "$1" in
    -h | --help | help | -v | --version | version)
        $(compose_with_options --no-defaults "mi") run \
            $tty_opt \
            --rm \
            -v "$original_dir:$original_dir" \
            --workdir "$original_dir" \
            mi "$@"
        ;;
    *)
        local services
        services=$(get_active_services)
        $(compose_with_options "$services" "mi") run \
            $tty_opt \
            --rm \
            -v "$original_dir:$original_dir" \
            --workdir "$original_dir" \
            mi "$@"
        ;;
    esac
}

run_npcsh_command() {
    local tty_opt=""
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        tty_opt="-T"
    fi

    case "$1" in
    -h | --help | help | -v | --version | version)
        $(compose_with_options --no-defaults "npcsh") run \
            $tty_opt \
            --rm \
            -v "$original_dir:$original_dir" \
            --workdir "$original_dir" \
            npcsh bash -lc 'export NPCSH_ENGINE="${NPCSH_ENGINE:-python}" NPCSH_INITIALIZED="${NPCSH_INITIALIZED:-1}"; exec npcsh "$@"' harbor-npcsh "$@"
        ;;
    *)
        local services
        services=$(get_active_services)
        $(compose_with_options "$services" "npcsh") run \
            $tty_opt \
            --rm \
            -v "$original_dir:$original_dir" \
            --workdir "$original_dir" \
            npcsh bash -lc 'export NPCSH_ENGINE="${NPCSH_ENGINE:-python}" NPCSH_INITIALIZED="${NPCSH_INITIALIZED:-1}"; exec npcsh "$@"' harbor-npcsh "$@"
        ;;
    esac
}

run_open_ai_command() {
    update_main_key() {
        local key=$(env_manager get openai.keys | cut -d";" -f1)
        env_manager set openai.key "$key"
    }

    update_main_url() {
        local url=$(env_manager get openai.urls | cut -d";" -f1)
        env_manager set openai.url "$url"
    }

    case "$1" in
    keys)
        shift
        env_manager_arr openai.keys --on-set update_main_key "$@"
        ;;
    urls)
        shift
        env_manager_arr openai.urls --on-set update_main_url "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not an OpenAI CLI, but a Harbor CLI to manage OpenAI configuration."
        echo
        echo "Usage: harbor openai <command>"
        echo
        echo "Commands:"
        echo "  harbor openai keys [ls|rm|add]   - Get/set the API Keys for the OpenAI-compatible APIs."
        echo "  harbor openai urls [ls|rm|add]   - Get/set the API URLs for the OpenAI-compatible APIs."
        ;;
    *)
        return 1
        ;;
    esac
}

run_webui_command() {
    case "$1" in
    secret)
        shift
        env_manager_alias webui.secret "$@"
        ;;
    name)
        shift
        env_manager_alias webui.name "$@"
        ;;
    log)
        shift
        env_manager_alias webui.log.level "$@"
        ;;
    version)
        shift
        env_manager_alias webui.version "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not WebUI CLI, but a Harbor CLI to manage WebUI service."
        echo
        echo "Usage: harbor webui <command>"
        echo
        echo "Commands:"
        echo "  harbor webui secret [secret]   - Get/set WebUI JWT Secret"
        echo "  harbor webui name [name]       - Get/set the name WebUI will present"
        echo "  harbor webui log [level]       - Get/set WebUI log level"
        echo "  harbor webui version [version] - Get/set WebUI version docker tag"
        return 1
        ;;
    *)
        return 1
        ;;
    esac
}

run_tabbyapi_command() {
    update_model_spec() {
        local spec=""
        local current_model=$(env_manager get tabbyapi.model)

        if [ -n "$current_model" ]; then
            spec=$(hf_spec_2_folder_spec $current_model)
        fi

        env_manager set tabbyapi.model.specifier "$spec"
    }

    case "$1" in
    model)
        shift
        env_manager_alias tabbyapi.model --on-set update_model_spec "$@"
        ;;
    args)
        shift
        env_manager_alias tabbyapi.extra.args "$@"
        ;;
    apidoc)
        shift
        if service_url=$(get_url tabbyapi 2>&1); then
            sys_open "$service_url/docs"
        else
            log_error "Failed to get service URL for tabbyapi: $service_url"
            exit 1
        fi
        ;;
    -h | --help | help)
        echo "Please note that this is not TabbyAPI CLI, but a Harbor CLI to manage TabbyAPI service."
        echo "Access TabbyAPI own CLI by running 'harbor exec tabbyapi' when it's running."
        echo
        echo "Usage: harbor tabbyapi <command>"
        echo
        echo "Commands:"
        echo "  harbor tabbyapi model [user/repo]   - Get or set the TabbyAPI model repository to run"
        echo "  harbor tabbyapi args [args]         - Get or set extra args to pass to the TabbyAPI CLI"
        echo "  harbor tabbyapi apidoc              - Open TabbyAPI built-in API documentation"
        ;;
    *)
        return 1
        ;;
    esac
}

run_parllama_command() {
    $(compose_with_options "parllama") run --rm -it --entrypoint bash parllama -c "uvx parllama"
}

run_oterm_command() {
    $(compose_with_options "oterm") run --rm -it oterm
}

run_plandex_command() {
    case "$1" in
    health)
        shift
        execute_and_process "get_url plandex-server" "curl {{output}}/health" "No plandexserver URL:"
        ;;
    pwd)
        shift
        echo $original_dir
        ;;
    *)
        $(compose_with_options "plandex") run --rm -v "$original_dir:/app/context" --workdir "/app/context" -it --entrypoint "plandex" plandex "$@"
        ;;
    esac
}

run_mistralrs_command() {
    update_model_spec() {
        local spec=""
        local current_model=$(env_manager get mistralrs.model)
        local current_type=$(env_manager get mistralrs.model_type)
        local current_arch=$(env_manager get mistralrs.model_arch)
        local current_isq=$(env_manager get mistralrs.isq)

        if [ -n "$current_isq" ]; then
            spec="--isq $current_isq"
        fi

        if [ -n "$current_type" ]; then
            spec="$spec $current_type"
        fi

        if [ -n "$current_model" ]; then
            spec="$spec -m $current_model"
        fi

        if [ -n "$current_arch" ]; then
            spec="$spec -a $current_arch"
        fi

        env_manager set mistralrs.model.specifier "$spec"
    }

    case "$1" in
    health)
        shift
        execute_and_process "get_url mistralrs" "curl {{output}}/health" "No mistralrs URL:"
        ;;
    docs)
        shift
        execute_and_process "get_url mistralrs" "sys_open {{output}}/docs" "No mistralrs URL:"
        ;;
    args)
        shift
        env_manager_alias mistralrs.extra.args "$@"
        ;;
    model)
        shift
        env_manager_alias mistralrs.model --on-set update_model_spec "$@"
        ;;
    type)
        shift
        env_manager_alias mistralrs.model_type --on-set update_model_spec "$@"
        ;;
    arch)
        shift
        env_manager_alias mistralrs.model_arch --on-set update_model_spec "$@"
        ;;
    isq)
        shift
        env_manager_alias mistralrs.isq --on-set update_model_spec "$@"
        ;;
    version)
        shift
        env_manager_alias mistralrs.version "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not mistral.rs CLI, but a Harbor CLI to manage mistral.rs service."
        echo "Access mistral.rs own CLI by running 'harbor exec mistralrs' when it's running."
        echo
        echo "Usage: harbor mistralrs <command>"
        echo
        echo "Commands:"
        echo "  harbor mistralrs health            - Check the health of the mistral.rs service"
        echo "  harbor mistralrs docs              - Open mistral.rs built-in API documentation"
        echo "  harbor mistralrs version [version] - Get or set mistral.rs version (0.3, 0.4, etc.)"
        echo "  harbor mistralrs args [args]       - Get or set extra args to pass to the mistral.rs CLI"
        echo "  harbor mistralrs model [user/repo] - Get or set the mistral.rs model repository to run"
        echo "  harbor mistralrs type [type]       - Get or set the mistral.rs model type"
        echo "  harbor mistralrs arch [arch]       - Get or set the mistral.rs model architecture"
        echo "  harbor mistralrs isq [isq]         - Get or set the mistral.rs model ISQ"
        ;;
    *)
        $(compose_with_options "mistralrs") run --rm mistralrs "$@"
        ;;
    esac
}

run_opint_command() {
    update_cmd() {
        local cmd=""
        local current_model=$(env_manager get opint.model)
        local current_args=$(env_manager get opint.extra.args)

        if [ -n "$current_model" ]; then
            cmd="--model $current_model"
        fi

        if [ -n "$current_args" ]; then
            cmd="$cmd $current_args"
        fi

        env_manager set opint.cmd "$cmd"
    }

    clear_cmd_srcs() {
        env_manager set opint.model ""
        env_manager set opint.args ""
    }

    case "$1" in
    backend)
        shift
        env_manager_alias opint.backend "$@"
        ;;
    profiles | --profiles | -p)
        shift
        execute_and_process "env_manager get opint.config.path" "sys_open {{output}}/profiles" "No opint.config.path set"
        ;;
    models | --local_models)
        shift
        execute_and_process "env_manager get opint.config.path" "sys_open {{output}}/models" "No opint.config.path set"
        ;;
    pwd)
        shift
        echo "$original_dir"
        ;;
    model)
        shift
        env_manager_alias opint.model --on-set update_cmd "$@"
        ;;
    args)
        shift
        env_manager_alias opint.extra.args --on-set update_cmd "$@"
        ;;
    cmd)
        shift
        env_manager_alias opint.cmd "$@"
        ;;
    -os | --os)
        shift
        echo "Harbor does not support Open Interpreter OS mode".
        ;;
    *)
        # Allow permanent override of the target backend
        local services=$(env_manager get opint.backend)

        if [ -z "$services" ]; then
            services=$(get_active_services)
        fi

        # Mount the current directory and set it as the working directory
        $(compose_with_options "$services" "opint") run -v "$original_dir:$original_dir" --workdir "$original_dir" opint "$@"
        ;;
    esac
}

run_cmdh_command() {
    case "$1" in
    model)
        shift
        env_manager_alias cmdh.model "$@"
        return 0
        ;;
    host)
        shift
        env_manager_alias cmdh.llm.host "$@"
        return 0
        ;;
    key)
        shift
        env_manager_alias cmdh.llm.key "$@"
        return 0
        ;;
    url)
        shift
        env_manager_alias cmdh.llm.url "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not cmdh CLI, but a Harbor CLI to manage cmdh service."
        echo "Access cmdh own CLI by running 'harbor exec cmdh' when it's running."
        echo
        echo "Usage: harbor cmdh <command>"
        echo
        echo "Commands:"
        echo "  harbor cmdh model [user/repo]    - Get or set the cmdh model repository to run"
        echo "  harbor cmdh host [ollama|OpenAI] - Get or set the cmdh LLM host"
        echo "  harbor cmdh key [key]            - Get or set the cmdh OpenAI LLM key"
        echo "  harbor cmdh url [url]            - Get or set the cmdh OpenAI LLM URL"
        ;;
    esac

    local services=$(get_active_services)

    # Mount the current directory and set it as the working directory
    $(compose_with_options $services "cmdh") run \
        --rm \
        -e "TERM=xterm-256color" \
        --name $default_container_prefix.cmdh-cli \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        cmdh "$*"
}

run_harbor_how_command() {
    local services=$(get_active_services)

    local tty_opt=""
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        tty_opt="-T"
    fi

    log_debug "Active services: $services"

    local prompt_file
    prompt_file=$(mktemp "${TMPDIR:-/tmp}/harbor-how.XXXXXX")
    trap "rm -f '$prompt_file'" EXIT

    local cli_help
    cli_help=$(show_help 2>&1)

    log_debug "Building system prompt"

    cat > "$prompt_file" <<SYSPROMPT
Harbor CLI assistant. Harbor is a containerized LLM toolkit on top of Docker Compose.

One-shot answer — the user cannot reply. Complete but brief. No follow-ups, no filler. Suggest harbor commands when applicable — never run them.

Search /harbor/docs/ and /harbor/harbor.sh with shell commands (grep, cat, ls) to find answers. These are read-only references, not services to operate.

## CLI Reference
$cli_help

## Currently active services
$services

## Documentation
Harbor docs are at /harbor/docs/ and the CLI source is at /harbor/harbor.sh.
SYSPROMPT

    log_debug "Starting mi agent"
    log_info "Thinking..."

    COMPOSE_PROGRESS=quiet \
    $(compose_with_options "$services" "mi" "harbor") run \
        $tty_opt \
        --rm \
        --entrypoint /harbor/harbor-how.sh \
        -v "$prompt_file:/harbor/how.prompt:ro" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        mi -p "$*"
}

run_fabric_command() {
    case "$1" in
    model)
        shift
        env_manager_alias fabric.model "$@"
        return 0
        ;;
    patterns | --patterns)
        shift
        execute_and_process "env_manager get fabric.config.path" "sys_open {{output}}/patterns" "No fabric.config.path set"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not Fabric CLI, but a Harbor CLI to manage Fabric service."
        echo
        echo "Usage: harbor fabric <command>"
        echo
        echo "Commands:"
        echo "  harbor fabric -h|--help|help    - Show this help message"
        echo "  harbor fabric model [user/repo] - Get or set the Fabric model repository to run"
        echo "  harbor fabric patterns          - Open the Fabric patterns directory"
        echo
        echo "To run the Fabric REST API server:"
        echo "  harbor fabric --serve           - Start the REST API server (port 8080)"
        echo "  harbor fabric --serve --serveOllama - Also expose Ollama-compatible endpoints"
        echo
        echo "Fabric CLI Help:"
        ;;
    esac

    local services=$(get_active_services)

    # Fabric has some funky TTY handling
    # Container hangs for specific flags
    # We have to explicitly remove -T for them to run
    local tty_flag="-T"
    local skip_tty=("-l" "--listpatterns" "-L" "--listmodels" "-x" "--listcontexts" "-X" "--listsessions" "--setup" "--liststrategies" "--listvendors" "--listextensions" "--serve" "--serveOllama")

    for arg in "$@"; do
        for skip_arg in "${skip_tty[@]}"; do
            if [[ "$skip_arg" == "$arg" ]]; then
                tty_flag=""
                break
            fi
        done
    done

    # To allow using preferred pipe pattern for fabric
    $(compose_with_options $services "fabric") run \
        --rm \
        $tty_flag \
        --name $default_container_prefix.fabric \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        fabric "$@"
}

run_parler_command() {
    case "$1" in
    model)
        shift
        env_manager_alias parler.model "$@"
        ;;
    voice)
        shift
        env_manager_alias parler.voice "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not Parler CLI, but a Harbor CLI to manage Parler service."
        echo
        echo "Usage: harbor parler <command>"
        echo
        echo "Commands:"
        echo "  harbor parler -h|--help|help - Show this help message"
        ;;
    *)
        return 1
        ;;
    esac
}

run_airllm_command() {
    case "$1" in
    model)
        shift
        env_manager_alias airllm.model "$@"
        ;;
    ctx)
        shift
        env_manager_alias airllm.ctx.len "$@"
        ;;
    compression)
        shift
        env_manager_alias airllm.compression "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not AirLLM CLI, but a Harbor CLI to manage AirLLM service."
        echo
        echo "Usage: harbor airllm <command>"
        echo
        echo "Commands:"
        echo "  harbor airllm model [user/repo]            - Get or set model to run"
        echo "  harbor airllm ctx [len]                    - Get or set context length for AirLLM"
        echo "  harbor airllm compression [4bit|8bit|none] - Get or set compression level for AirLLM"
        ;;
    *)
        return 1
        ;;
    esac
}

run_txtairag_command() {
    case "$1" in
    model)
        shift
        env_manager_alias txtai.rag.model "$@"
        ;;
    embeddings)
        shift
        env_manager_alias txtai.rag.embeddings "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not txtai rag CLI, but a Harbor CLI to manage txtai rag service."
        echo
        echo "Usage: harbor txtai rag <command>"
        echo
        echo "Commands:"
        echo "  harbor txtai rag model [user/repo] - Get or set the txtai rag model repository to run"
        echo "  harbor txtai rag embeddings [path] - Get or set the path to the embeddings file"
        ;;
    *)
        return 1
        ;;
    esac
}

run_txtai_command() {
    case "$1" in
    rag)
        shift
        run_txtairag_command "$@"
        ;;
    cache)
        shift
        env_manager_alias txtai.cache "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not txtai CLI, but a Harbor CLI to manage txtai service."
        echo
        echo "Usage: harbor txtai <command>"
        echo
        echo "Commands:"
        echo "  harbor txtai cache - Get/set the location of global txtai cache"
        echo "  harbor txtai rag   - Run commands related to txtai rag application"
        ;;
    *)
        return 1
        ;;
    esac
}

run_aider_command() {
    case "$1" in
    model)
        shift
        env_manager_alias aider.model "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not Aider CLI, but a Harbor CLI to manage Aider service."
        echo
        echo "Usage: harbor aider <command>"
        echo
        echo "Commands:"
        echo "  harbor aider model [user/repo] - Get or set the Aider model repository to run"
        ;;
    esac

    local services

    services=$(get_active_services)

    # To allow using preferred pipe pattern for fabric
    $(compose_with_options $services "aider") run \
        -it \
        --rm \
        --service-ports \
        -e "TERM=xterm-256color" \
        -e "PYTHONUNBUFFERED=1" \
        -e "PYTHONIOENCODING=utf-8" \
        -v "$original_dir:/home/appuser/workspace" \
        --workdir "/home/appuser/workspace" \
        aider "$@"
}

run_nanobot_command() {
    case "$1" in
    model)
        shift
        env_manager_alias nanobot.model "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not nanobot CLI, but a Harbor CLI to manage nanobot service."
        echo
        echo "Usage: harbor nanobot <command>"
        echo
        echo "Commands:"
        echo "  harbor nanobot model [model] - Get or set the nanobot model"
        ;;
    esac

    local services
    services=$(get_active_services)

    $(compose_with_options $services "nanobot") run \
        -it \
        --rm \
        --service-ports \
        -e "TERM=xterm-256color" \
        nanobot "$@"
}

run_chatui_command() {
    case "$1" in
    version)
        shift
        env_manager_alias chatui.version "$@"
        ;;
    model)
        shift
        env_manager_alias chatui.ollama.model "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not ChatUI CLI, but a Harbor CLI to manage ChatUI service."
        echo
        echo "Usage: harbor chatui <command>"
        echo
        echo "Commands:"
        echo "  harbor chatui version [version] - Get or set the ChatUI version docker tag"
        echo "  harbor chatui model [id]        - Get or set the Ollama model to target"
        ;;
    *)
        return 1
        ;;
    esac
}

run_comfyui_workspace_command() {
    case "$1" in
    open)
        shift
        sys_open "$harbor_home/services/comfyui/workspace"
        ;;
    sync)
        shift
        log_info "Cleaning up ComfyUI environment..."
        run_exec comfyui rm -rf /workspace/environments/python/comfyui
        log_info "Syncing installed custom nodes to persistent storage..."
        run_exec comfyui venv-sync comfyui
        ;;
    clear)
        shift
        log_info "Cleaning up ComfyUI workspace..."
        run_gum confirm "This operation will delete all stored ComfyUI configuration. Continue?" && run_exec comfyui rm -rf /workspace/* || echo "Cleanup aborted."
        log_info "Restart Harbor to re-init Comfy UI"
        ;;
    *)
        return 1
        ;;
    esac
}

run_comfyui_command() {
    case "$1" in
    version)
        shift
        env_manager_alias comfyui.version "$@"
        ;;
    user)
        shift
        env_manager_alias comfyui.user "$@"
        ;;
    password)
        shift
        env_manager_alias comfyui.password "$@"
        ;;
    auth)
        shift
        env_manager_alias comfyui.auth "$@"
        ;;
    workspace)
        shift
        run_comfyui_workspace_command "$@"
        ;;
    output)
        shift
        sys_open "$harbor_home/services/comfyui/workspace/ComfyUI/output"
        ;;
    -h | --help | help)
        echo "Please note that this is not ComfyUI CLI, but a Harbor CLI to manage ComfyUI service."
        echo
        echo "Usage: harbor comfyui <command>"
        echo
        echo "Commands:"
        echo "  harbor comfyui version [version]   - Get or set the ComfyUI version docker tag"
        echo "  harbor comfyui user [username]     - Get or set the ComfyUI username"
        echo "  harbor comfyui password [password] - Get or set the ComfyUI password"
        echo "  harbor comfyui auth [true|false]   - Enable/disable ComfyUI authentication"
        echo "  harbor comfyui workspace sync    - Sync installed custom nodes to persistent storage"
        echo "  harbor comfyui workspace open    - Open folder containing ComfyUI workspace in the File Manager"
        echo "  harbor comfyui workspace clear   - Clear ComfyUI workspace, including all configurations and models"
        echo "  harbor comfyui output             - Open folder containing ComfyUI output in the File Manager"
        ;;
    *)
        return 1
        ;;
    esac
}

run_aichat_command() {
    case "$1" in
    model)
        shift
        env_manager_alias aichat.model "$@"
        return 0
        ;;
    workspace)
        shift
        execute_and_process "env_manager get aichat.config.path" "sys_open {{output}}" "No aichat.config.path set"
        ;;
    -h | --help | help)
        echo "Please note that this is not aichat CLI, but a Harbor CLI to manage aichat service."
        echo
        echo "Usage: harbor aichat <command>"
        echo
        echo "Commands:"
        echo "  harbor aichat model [model] - Get or set the model to run"
        echo "  harbor aichat workspace     - Open the aichat workspace directory"
        echo
        echo "Original CLI help:"
        ;;
    esac

    local services=$(get_active_services)

    $(compose_with_options $services "aichat") run \
        --rm \
        --name harbor.aichat \
        --service-ports \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        aichat "$@"
}

run_ollama_command() {
    update_ollama_env() {
        harbor env ollama OLLAMA_CONTEXT_LENGTH $(harbor config get ollama.context_length)
    }

    case "$1" in
    ctx)
        shift
        env_manager_alias ollama.context_length --on-set update_ollama_env "$@"
        return 0
        ;;
    esac

    local services=$(get_active_services)
    local ollama_host=$(env_manager get ollama.internal.url)

    if ! is_service_running "ollama"; then
        log_debug "Ollama is not running, launching..."
        run_up --no-defaults ollama
    else
        log_debug "Ollama already running"
    fi

    $(compose_with_options $services "ollama") run \
        --rm \
        -e "OLLAMA_HOST=$ollama_host" \
        --name harbor.ollama-cli-$RANDOM \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        ollama "$@"
}

run_omnichain_command() {
    case "$1" in
    workspace)
        shift
        execute_and_process "env_manager get omnichain.workspace" "sys_open {{output}}" "No omnichain.workspace set"
        ;;
    -h | --help | help)
        echo "Please note that this is not omnichain CLI, but a Harbor CLI to manage omnichain service."
        echo
        echo "Usage: harbor omnichain <command>"
        echo
        echo "Commands:"
        echo "  harbor omnichain workspace     - Open the omnichain workspace directory"
        ;;
    *)
        return 1
        ;;
    esac
}

run_bench_command() {
    case "$1" in
    results)
        shift
        execute_and_process "env_manager get bench.results" "sys_open {{output}}" "No bench.results set"
        return 0
        ;;
    tasks)
        shift
        env_manager_alias bench.tasks "$@"
        return 0
        ;;
    debug)
        shift
        env_manager_alias bench.debug "$@"
        return 0
        ;;
    model)
        shift
        env_manager_alias bench.model "$@"
        return 0
        ;;
    api)
        shift
        env_manager_alias bench.api "$@"
        return 0
        ;;
    key)
        shift
        env_manager_alias bench.api_key "$@"
        return 0
        ;;
    judge)
        shift
        env_manager_alias bench.judge "$@"
        return 0
        ;;
    judge_api)
        shift
        env_manager_alias bench.judge_api "$@"
        return 0
        ;;
    judge_key)
        shift
        env_manager_alias bench.judge_api_key "$@"
        return 0
        ;;
    judge_prompt)
        shift
        env_manager_alias bench.judge_prompt "$@"
        return 0
        ;;
    judge_tokens)
        shift
        env_manager_alias bench.judge_max_tokens "$@"
        return 0
        ;;
    variants)
        shift
        env_manager_alias bench.variants "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Usage: harbor bench <command>"
        echo
        echo "Commands:"
        echo "  harbor bench run - runs the benchmark"
        echo "  harbor bench results       - Open the directory containing benchmark results"
        echo "  harbor bench tasks [tasks] - Get or set the path to tasks.yml to run in the benchmark"
        echo "  harbor bench model [model] - Get or set the model to run in the benchmark"
        echo "  harbor bench api [url]   - Get or set the API URL to use in the benchmark"
        echo "  harbor bench key [key]   - Get or set the API key to use in the benchmark"
        echo "  harbor bench judge [url] - Get or set the judge URL to use in the benchmark"
        echo "  harbor bench judge_api [url] - Get or set the judge API URL to use in the benchmark"
        echo "  harbor bench judge_key [key] - Get or set the judge API key to use in the benchmark"
        echo "  harbor bench judge_prompt [prompt] - Get or set the judge prompt to use in the benchmark"
        echo "  harbor bench variants [variants] - Get or set the variants of LLM params that bench will run"
        echo "  harbor bench debug [true]  - Enable or disable debug mode in the benchmark"
        return 0
        ;;
    run)
        shift
        local services=$(get_active_services)
        $(compose_with_options $services "bench") run --rm "bench" "$@"
        ;;
    *)
        return 1
        ;;
    esac
}

run_lm_eval_command() {
    update_model_spec() {
        local current_model=$(env_manager_dict lmeval.model.args get model)

        # If model is present, propagate to env var
        if [ -n "$current_model" ]; then
            env_manager set lmeval.model.specifier "$current_model"
        fi
    }

    case "$1" in
    results)
        shift
        execute_and_process "env_manager get lmeval.results" "sys_open {{output}}" "No lmeval.results set"
        return 0
        ;;
    cache)
        shift
        execute_and_process "env_manager get lmeval.cache" "sys_open {{output}}" "No lmeval.cache set"
        return 0
        ;;
    type)
        shift
        env_manager_alias lmeval.type "$@"
        return 0
        ;;
    model)
        shift
        env_manager_dict_alias lmeval.model.args model --on-set update_model_spec "$@"
        return 0
        ;;
    api)
        shift
        env_manager_dict_alias lmeval.model.args base_url "$@"
        return 0
        ;;
    args)
        shift
        env_manager_dict lmeval.model.args "$@"
        return 0
        ;;
    extra)
        shift
        env_manager_alias lmeval.extra.args "$@"
        return 0
        ;;
    -h | --help)
        echo "Please note that this is not lm_eval CLI, but a Harbor CLI to manage lm_eval service."
        echo
        echo "Usage: harbor [lmeval|lm_eval] <command>"
        echo
        echo "Commands:"
        echo "  harbor lmeval results - Open the directory containing lm_eval results"
        echo "  harbor lmeval cache   - Open the directory containing lm_eval cache"
        echo "  harbor lmeval type    - Get set --model to pass to the lm_eval CLI"
        echo "  harbor lmeval model   - Alias for 'harbor lmeval args get|set model'"
        echo "  harbor lmeval api     - Alias for 'harbor lmeval args get|set base_url'"
        echo "  harbor lmeval args    - Get or set individual --model_args to pass to the lm_eval CLI"
        echo "  harbor lmeval extra   - Get or set extra args to pass to the lm_eval CLI"
        echo
        echo "Original CLI help:"
        ;;
    esac

    local services=$(get_active_services)

    $(compose_with_options $services "lmeval") run \
        --rm \
        --name harbor.lmeval \
        --service-ports \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        lmeval "$@"
}

run_sglang_command() {
    case "$1" in
    model)
        shift
        env_manager_alias sglang.model "$@"
        return 0
        ;;
    args)
        shift
        env_manager_alias sglang.extra.args "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not sglang CLI, but a Harbor CLI to manage sglang service."
        echo
        echo "Usage: harbor sglang <command>"
        echo
        echo "Commands:"
        echo "  harbor sglang model [user/repo] - Get or set the sglang model repository to run"
        echo "  harbor sglang args [args]       - Get or set extra args to pass to the sglang CLI"
        ;;
    esac
}

run_jupyter_command() {
    case "$1" in
    workspace)
        shift
        execute_and_process "env_manager get jupyter.workspace" "sys_open {{output}}" "No jupyter.workspace set"
        ;;
    image)
        shift
        env_manager_alias jupyter.image "$@"
        ;;
    deps)
        shift
        env_manager_arr jupyter.extra.deps "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not Jupyter CLI, but a Harbor CLI to manage Jupyter service."
        echo
        echo "Usage: harbor jupyter <command>"
        echo
        echo "Commands:"
        echo "  harbor jupyter workspace     - Open the Jupyter workspace directory"
        echo "  harbor jupyter image [image] - Get or set the Jupyter image to run"
        echo "  harbor jupyter deps [deps]   - Manage extra dependencies to install in the Jupyter image"
        ;;
    *)
        return 1
        ;;
    esac
}

run_ol1_command() {
    case "$1" in
    model)
        shift
        env_manager_alias ol1.model "$@"
        return 0
        ;;
    args)
        shift
        env_manager_dict ol1.args "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not OL1 CLI, but a Harbor CLI to manage OL1 service."
        echo
        echo "Usage: harbor ol1 <command>"
        echo
        echo "Commands:"
        echo "  harbor ol1 model [user/repo] - Get or set the OL1 model repository to run"
        ;;
    esac
}

run_ktransformers_command() {
    case "$1" in
    model)
        shift
        env_manager_alias ktransformers.model "$@"
        return 0
        ;;
    gguf)
        shift
        env_manager_dict ktransformers.gguf "$@"
        return 0
        ;;
    version)
        shift
        env_manager_alias ktransformers.version "$@"
        return 0
        ;;
    image)
        shift
        env_manager_alias ktransformers.image "$@"
        return 0
        ;;
    args)
        shift
        env_manager_alias ktransformers.args "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not KTransformers CLI, but a Harbor CLI to manage KTransformers service."
        echo
        echo "Usage: harbor ktransformers <command>"
        echo
        echo "Commands:"
        echo "  harbor ktransformers model [user/repo] - Get or set --model_path for KTransformers"
        echo "  harbor ktransformers gguf [args]       - Get or set --gguf_path for KTransformers"
        echo "  harbor ktransformers version [version] - Get or set KTransformers version"
        echo "  harbor ktransformers image [image]     - Get or set KTransformers image"
        echo "  harbor ktransformers args [args]       - Get or set extra args to pass to KTransformers"
        ;;
    esac
}

run_boost_klmbr_command() {
    case "$1" in
    percentage)
        shift
        env_manager_alias boost.klmbr.percentage "$@"
        ;;
    mods)
        shift
        env_manager_arr boost.klmbr.mods "$@"
        ;;
    strat)
        shift
        env_manager_alias boost.klmbr.strat "$@"
        ;;
    strat_params)
        shift
        env_manager_dict boost.klmbr.strat_params "$@"
        ;;
    -h | --help | help)
        echo "Usage: harbor boost klmbr <command>"
        echo
        echo "Commands:"
        echo "  harbor boost klmbr percentage [percentage] - Get or set the klmbr percentage parameter"
        echo "  harbor boost klmbr mods [mods]             - Get or set the klmbr mods parameter"
        echo "  harbor boost klmbr strat [strat]           - Get or set the klmbr strat parameter"
        echo "  harbor boost klmbr strat_params [params]   - Get or set the klmbr strat_params parameter"
        ;;
    esac
}

run_boost_rcn_command() {
    case "$1" in
    strat)
        shift
        env_manager_alias boost.rcn.strat "$@"
        ;;
    strat_params)
        shift
        env_manager_dict boost.rcn.strat_params "$@"
        ;;
    -h | --help | help)
        echo "Usage: harbor boost rcn <command>"
        echo
        echo "Commands:"
        echo "  harbor boost rcn strat [strat]           - Get or set the rcn strat parameter"
        echo "  harbor boost rcn strat_params [params]   - Get or set the rcn strat_params parameter"
        ;;
    esac
}

run_boost_g1_command() {
    case "$1" in
    strat)
        shift
        env_manager_alias boost.g1.strat "$@"
        ;;
    strat_params)
        shift
        env_manager_dict boost.g1.strat_params "$@"
        ;;
    max_steps)
        shift
        env_manager_alias boost.g1.max_steps "$@"
        ;;
    -h | --help | help)
        echo "Usage: harbor boost g1 <command>"
        echo
        echo "Commands:"
        echo "  harbor boost g1 strat [strat]           - Get or set the g1 strat parameter"
        echo "  harbor boost g1 strat_params [params]   - Get or set the g1 strat_params parameter"
        ;;
    esac
}

run_boost_r0_module() {
    case "$1" in
    thoughts)
        shift
        env_manager_alias boost.r0.thoughts "$@"
        ;;
    esac
}

run_boost_command() {
    case "$1" in
    urls)
        shift
        env_manager_arr boost.openai.urls "$@"
        ;;
    keys)
        shift
        env_manager_arr boost.openai.keys "$@"
        ;;
    modules)
        shift
        env_manager_arr boost.modules "$@"
        ;;
    klmbr)
        shift
        run_boost_klmbr_command "$@"
        ;;
    rcn)
        shift
        run_boost_rcn_command "$@"
        ;;
    g1)
        shift
        run_boost_g1_command "$@"
        ;;
    r0)
        shift
        run_boost_r0_command "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not Boost CLI, but a Harbor CLI to manage Boost service."
        echo
        echo "Usage: harbor boost <command>"
        echo
        echo "Commands:"
        echo "  harbor boost urls [urls] - Manage OpenAI API URLs to boost"
        echo "  harbor boost keys [keys] - Manage OpenAI API keys to boost"
        echo "  harbor boost klmbr       - Manage klmbr module"
        echo "  harbor boost rcn         - Manage rcn module"
        echo "  harbor boost g1          - Manage g1 module"
        echo "  harbor boost r0          - Manage r0 module"
        ;;
    esac
}

run_langflow_command() {
    case "$1" in
    ui | open)
        shift
        local port=${HARBOR_LANGFLOW_HOST_PORT:-7860}
        local url="http://localhost:$port"
        if sys_open "$url"; then
            log_info "Opened Langflow UI at $url"
        else
            log_error "Failed to open Langflow UI. Try visiting $url manually."
            return 1
        fi
        ;;
    url)
        shift
        local port=${HARBOR_LANGFLOW_HOST_PORT:-7860}
        echo "http://localhost:$port"
        ;;
    version)
        shift
        env_manager_alias langflow.version "$@"
        ;;
    auth)
        shift
        case "$1" in
        username)
            shift
            env_manager_alias langflow.superuser "$@"
            ;;
        password)
            shift
            env_manager_alias langflow.password "$@"
            ;;
        autologin)
            shift
            env_manager_alias langflow.auto_login "$@"
            ;;
        *)
            echo "Usage: harbor langflow auth {username|password|autologin}"
            return 1
            ;;
        esac
        ;;
    workspace)
        shift
        execute_and_process "env_manager get langflow.data" "sys_open {{output}}" "No langflow.data set"
        ;;
    ui)
        shift
        if service_url=$(get_url langflow 2>&1); then
            sys_open "$service_url"
        else
            log_error "Failed to get service URL for langflow: $service_url"
            exit 1
        fi
        ;;
    -h | --help | help)
        echo "Langflow - LangChain Flow UI"
        echo
        echo "Langflow provides a visual way to build and prototype LangChain applications."
        echo
        echo "Usage: harbor langflow <command>"
        echo
        echo "Commands:"
        echo "  version [version]     - Get or set Langflow version"
        echo "  auth username [user]  - Get or set admin username"
        echo "  auth password [pass]  - Get or set admin password"
        echo "  auth autologin [bool] - Enable/disable auto login"
        echo "  workspace             - Open Langflow workspace directory"
        echo "  ui                    - Open Langflow UI in browser"
        echo
        echo "Quick Start:"
        echo "  harbor up langflow               - Start Langflow"
        echo "  harbor up langflow langflow-db   - Start with PostgreSQL"
        echo "  harbor open langflow             - Open the UI"
        echo
        echo "Default Configuration:"
        echo "  Admin User: admin@admin.com"
        echo "  Password:   admin"
        echo "  Port:      7860"
        echo
        echo "Database Options:"
        echo "  SQLite (default) - No additional configuration needed"
        echo "  PostgreSQL       - Start with 'harbor up langflow langflow-db'"
        ;;
    *)
        return 1
        ;;
    esac
}

run_photoprism_command() {
    case "$1" in
    model)
        shift
        env_manager_alias photoprism.vision.model "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Usage: harbor photoprism <command>"
        echo
        echo "Harbor Commands:"
        echo "  harbor photoprism model [model]  - Get or set the vision model for Ollama integration"
        echo
        echo "PhotoPrism CLI Commands (run inside container):"
        echo "  harbor photoprism vision ls                      - List configured vision models"
        echo "  harbor photoprism vision run -m caption          - Run caption generation"
        echo "  harbor photoprism vision run -m labels           - Run label generation"
        echo "  harbor photoprism passwd <user>                  - Reset user password"
        echo "  harbor photoprism users ls                       - List users"
        echo
        echo "See: https://docs.photoprism.app/user-guide/ai/cli/"
        return 0
        ;;
    esac

    local services=$(get_active_services)

    if ! is_service_running "photoprism"; then
        log_error "PhotoPrism is not running. Start it with 'harbor up photoprism'"
        return 1
    fi

    $(compose_with_options $services "photoprism") exec \
        photoprism \
        photoprism "$@"
}

run_openhands_command() {
    local services=$(get_active_services)

    $(compose_with_options $services "openhands") run \
        --rm \
        --name $default_container_prefix.openhands \
        --service-ports \
        -e "TERM=xterm-256color" \
        -e "WORKSPACE_MOUNT_PATH=$original_dir" \
        -v "$original_dir:/opt/workspace_base" \
        openhands "$@"
}

run_stt_command() {
    case "$1" in
    model)
        shift
        env_manager_alias stt.model "$@"
        ;;
    version)
        shift
        env_manager_alias stt.version "$@"
        ;;
    -h | --help | help)
        echo "Usage: harbor stt <command>"
        echo
        echo "Commands:"
        echo "  harbor stt model [user/repo] - Get or set the STT model to run"
        echo "  harbor stt version [version] - Get or set the STT docker tag"
        ;;
    *)
        return 1
        ;;
    esac
}

run_speaches_command() {
    case "$1" in
    stt_model)
        shift
        env_manager_alias speaches.stt.model "$@"
        ;;
    tts_model)
        shift
        env_manager_alias speaches.tts.model "$@"
        ;;
    tts_voice)
        shift
        env_manager_alias speaches.tts.voice "$@"
        ;;
    version)
        shift
        env_manager_alias speaches.version "$@"
        ;;
    -h | --help | help)
        echo "Usage: harbor speaches <command>"
        echo
        echo "Commands:"
        echo "  harbor speaches stt_model [user/repo] - Get or set the STT model to run"
        echo "  harbor speaches tts_model [user/repo] - Get or set the TTS model to run"
        echo "  harbor speaches tts_voice [voice]     - Get or set the TTS voice to use"
        ;;
    *)
        return 1
        ;;
    esac
}

run_nexa_command() {
    case "$1" in
    model)
        shift
        env_manager_alias nexa.model "$@"
        return 0
        ;;
    -h | --help)
        echo "Please note that this is not Nexa CLI, but a Harbor CLI to manage nexa service."
        echo
        echo "Usage: harbor [nexa] <command>"
        echo
        echo "Commands:"
        echo "  harbor nexa model   - Alias for 'harbor lmeval args get|set model'"
        echo
        echo "Original CLI help:"
        ;;
    esac

    local services=$(get_active_services)

    $(compose_with_options $services "nexa") run \
        --rm \
        --name $default_container_prefix.nexa-cli \
        --service-ports \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        nexa "$@"
}

run_repopack_command() {
    local services=$(get_active_services)

    $(compose_with_options $services "repopack") run \
        --rm \
        --name $default_container_prefix.repopack \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        repopack "$@"
}

run_k6_command() {
    local services=$(get_active_services)
    echo "Active services: $services"

    # Check if the specified service is running
    if ! echo "$services" | grep -q "k6"; then
        log_debug "K6 backend stopped, launching..."
        harbor up --no-defaults k6
    else
        log_debug "K6 backend already running."
    fi

    log_info "--------------------------------------"
    log_info "${c_y}🔗 Harbor K6: ${c_b}$(get_url k6-grafana)${c_nc}"
    log_info "--------------------------------------"

    $(compose_with_options --no-defaults "k6") run \
        --rm \
        -it \
        --user "$(id -u):$(id -g)" \
        --name $default_container_prefix.k6-cli-$RANDOM \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        k6 run "$@"
}

run_promptfoo_eval() {
    local eval_name="$1"
    local other_args="${@:2}"
    local eval_path="$(harbor home)/promptfoo/evals/$eval_name"

    log_debug "Running promptfoo eval: $eval_name"
    pushd "$eval_path" || {
        log_error "Failed to change directory to $eval_path"
        return 1
    }

    trap 'popd >/dev/null; exit 130' INT
    harbor pf eval $other_args
    trap - INT
    popd >/dev/null
}

run_promptfoo_command() {
    local services=$(get_active_services)
    log_debug "Active services: $services"

    local tty_opt="-it"
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        tty_opt="-T"
    fi

    # Check if the specified service is running
    if ! echo "$services" | grep -q "promptfoo"; then
        log_debug "Promptfoo backend stopped, launching..."
        run_up --no-defaults promptfoo || return $?
    else
        log_debug "Promptfoo backend already running."
    fi

    case "$1" in
    view | open | o)
        shift
        run_open promptfoo
        ;;
    esac

    # Run promptfoo CLI, handle Ctrl+C/Ctrl+D gracefully
    trap 'echo; log_info "Promptfoo CLI interrupted."; exit 130' INT
    trap 'echo; log_info "Promptfoo CLI terminated."; exit 130' TERM

    $(compose_with_options $services "promptfoo") run \
        $tty_opt \
        --rm \
        --name $default_container_prefix.promptfoo-cli-$RANDOM \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        --entrypoint promptfoo \
        promptfoo "$@"
    local status=$?

    trap - INT TERM
    return $status
}

run_webtop_command() {
    local services=$(get_active_services)
    local is_running=false

    if echo "$services" | grep -q "webtop"; then
        is_running=true
    fi

    case "$1" in
    reset)
        shift
        # Just in case
        run_down webtop
        # Cleanup data directory
        local data_dir=$(env_manager get webtop.workspace)
        log_info "Deleting Webtop workspace at '$data_dir'"
        rm -rf $data_dir
        return 0
        ;;
    esac

    if [ "$is_running" = true ]; then
        log_error "Webtop is already running, use 'harbor exec webtop' to interact with it."
        return 1
    fi

    $(compose_with_options $services "webtop") run \
        --rm \
        --service-ports \
        --name $default_container_prefix.webtop-cli-$RANDOM \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        webtop with-contenv "$@"
}

run_kobold_command() {
    case "$1" in
    model)
        shift
        env_manager_alias kobold.model "$@"
        ;;
    args)
        shift
        env_manager_alias kobold.args "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not Kobold CLI, but a Harbor CLI to manage Kobold service."
        echo
        echo "Usage: harbor kobold <command>"
        echo
        echo "Commands:"
        echo "  harbor kobold model [user/repo] - Get or set the Kobold model repository to run"
        ;;
    *)
        return 1
        ;;
    esac
}

run_morphic_command() {
    case "$1" in
    model)
        shift
        # harbor env morphic NEXT_PUBLIC_OLLAMA_MODEL "$@"
        env_manager_alias morphic.model "$@"
        ;;
    tool_model)
        shift
        # harbor env morphic NEXT_PUBLIC_OLLAMA_TOOL_CALL_MODEL "$@"
        env_manager_alias morphic.tool_model "$@"
        ;;
    -h | --help | help)
        echo "Please note that this is not Morphic CLI, but a Harbor CLI to manage Morphic service."
        echo
        echo "Usage: harbor morphic <command>"
        echo
        echo "Commands:"
        echo "  harbor morphic model [user/repo] - Get or set the Morphic model repository to run"
        ;;
    *)
        return 1
        ;;
    esac
}

run_gptme_command() {
    case "$1" in
    model)
        shift
        env_manager_alias gptme.model "$@"
        return
        ;;
    -h | --help | help)
        echo "Please note that this is not GPTme CLI, but a Harbor CLI to manage GPTme service."
        echo
        echo "Usage: harbor gptme <command>"
        echo
        echo "Commands:"
        echo "  harbor gptme model [user/repo] - Get or set the GPTme model repository to run"
        ;;
    esac

    local services=$(get_active_services)
    local model_id=$(env_manager get gptme.model)
    local model_spec="local/$model_id"

    $(compose_with_options $services "gptme") run \
        --rm \
        --name harbor.gptme-cli-$RANDOM \
        --service-ports \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        gptme -m $model_spec "$@"
}

run_hermes_command() {
    case "$1" in
    version)
        shift
        env_manager_alias hermes.version "$@"
        return 0
        ;;
    api_key)
        shift
        env_manager_alias hermes.api_key "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Usage: harbor hermes <command>"
        echo
        echo "Harbor Commands:"
        echo "  harbor hermes version [version] - Get or set the Hermes Agent version"
        echo "  harbor hermes api_key [key]     - Get or set the Hermes Agent API key"
        echo "  harbor hermes ...               - Any other Hermes CLI command (proxied to container)"
        echo
        ;;
    esac

    local services=$(get_active_services)

    $(compose_with_options $services "hermes") exec \
        hermes \
        hermes "$@"
}

run_mcp_command() {
    case "$1" in
    inspector)
        shift
        run_av_tools npx @modelcontextprotocol/inspector "$@"
        return 0
        ;;
    esac
}

run_openfang_command() {
    case "$1" in
    model)
        shift
        env_manager_alias openfang.model "$@"
        return 0
        ;;
    provider)
        shift
        env_manager_alias openfang.model.provider "$@"
        return 0
        ;;
    -h | --help | help)
        echo "Please note that this is not OpenFang CLI, but a Harbor CLI to manage OpenFang service."
        echo
        echo "Usage: harbor openfang <command>"
        echo
        echo "Commands:"
        echo "  harbor openfang model [model]       - Get or set the OpenFang model"
        echo "  harbor openfang provider [provider]  - Get or set the OpenFang model provider"
        return 0
        ;;
    esac

    local services
    services=$(get_active_services)

    $(compose_with_options $services "openfang") exec \
        openfang \
        openfang "$@"
}

run_modularmax_command() {
    case "$1" in
    model)
        shift
        env_manager_alias modularmax.model "$@"
        return 0
        ;;
    args)
        shift
        env_manager_alias modularmax.extra_args "$@"
        return 0
        ;;
    help | -h | --help)
        echo "Please note that this is not ModularMax CLI, but a Harbor CLI to manage ModularMax service."
        echo
        echo "Usage: harbor modularmax <command>"
        echo
        echo "Commands:"
        echo "  harbor modularmax model [user/repo] - Get or set the ModularMax model repository to run"
        echo "  harbor modularmax args [args]       - Get or set extra args to pass to the ModularMax CLI"
        ;;
    esac
}

# ========================================================================
# == Main script
# ========================================================================

# Globals
version="0.4.19"
harbor_repo_url="https://github.com/av/harbor.git"
harbor_release_url="https://api.github.com/repos/av/harbor/releases/latest"
delimiter="|"
scramble_exit_code=42
# Portable readlink -f: resolve symlinks on both GNU (Linux) and BSD (macOS).
# macOS BSD readlink does not support -f; this loop manually chases symlinks.
_resolve_symlink() {
    local target="$1"
    while [ -L "$target" ]; do
        local dir link
        dir=$(dirname "$target")
        link=$(readlink "$target")
        # If the link is relative, resolve it against the directory of the symlink
        if [[ "$link" != /* ]]; then
            target="$dir/$link"
        else
            target="$link"
        fi
    done
    # Canonicalize the directory path (cd -P resolves remaining .. and symlinked dirs)
    local dir
    dir=$(cd -P "$(dirname "$target")" && pwd)
    printf '%s/%s\n' "$dir" "$(basename "$target")"
}

# Portable realpath: canonicalize a path without requiring GNU coreutils.
# macOS only ships realpath from Ventura (13.0)+; this works everywhere.
_portable_realpath() {
    local target="$1"
    if [[ -d "$target" ]]; then
        (cd -P "$target" && pwd)
    elif [[ -e "$target" ]]; then
        local dir base
        dir=$(cd -P "$(dirname "$target")" && pwd)
        base=$(basename "$target")
        printf '%s/%s\n' "$dir" "$base"
    else
        # Path doesn't exist yet — canonicalize the parent and append
        local dir base
        dir=$(cd -P "$(dirname "$target")" 2>/dev/null && pwd) || {
            printf '%s\n' "$target"
            return 1
        }
        base=$(basename "$target")
        printf '%s/%s\n' "$dir" "$base"
    fi
}

harbor_home=${HARBOR_HOME:-$(dirname "$(_resolve_symlink "${BASH_SOURCE[0]}")")}  # harbor-lint disable=HARBOR003
profiles_dir="$harbor_home/profiles"
default_profile="$profiles_dir/default.env"
default_current_env="$harbor_home/.env"
default_gum_image="ghcr.io/charmbracelet/gum"

export HARBOR_COMPOSE_CACHE="__harbor_$$.yml"
trap 'rm -f "$harbor_home/$HARBOR_COMPOSE_CACHE" 2>/dev/null' EXIT

# Desired compose version
desired_compose_major="2"
desired_compose_minor="23"
desired_compose_patch="1"

original_dir=$PWD
cd "$harbor_home" || exit

# Set color variables
set_colors
# Initialize the log levels
set_default_log_levels

# Commands that do not need .env or Docker — let them run even on a
# broken / fresh install where ensure_env_file would fail.
case "$1" in
    help|--help|-h)
        show_help
        exit 0
        ;;
    version|--version|-v)
        show_version
        exit 0
        ;;
    home)
        echo "$harbor_home"
        exit 0
        ;;
    completion)
        shift
        run_completion_command "$@"
        exit 0
        ;;
esac

# Config
if ! ensure_env_file; then
    exit 1
fi
# Current user ID - FS + UIDs for containers (where applicable)
env_manager --silent set user.id "$(id -u)"
env_manager --silent set group.id "$(id -g)"
env_manager --silent set home.volume "$harbor_home"
# Auto-generate admin passwords on first run; preserved across invocations so
# users can read them back via `harbor config get <key>`.
if [ -z "$(env_manager --silent get beszel.user.password)" ]; then
    env_manager --silent set beszel.user.password "$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | dd bs=1 count=16 2>/dev/null)"
fi
if [ -z "$(env_manager --silent get unsloth-studio.password)" ]; then
    env_manager --silent set unsloth-studio.password "$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | dd bs=1 count=16 2>/dev/null)"
fi
default_options=($(env_manager get services.default | tr ';' ' '))
default_tunnels=($(env_manager get services.tunnels | tr ';' ' '))
default_capabilities=($(env_manager get capabilities.default | tr ';' ' '))
default_auto_capabilities=$(env_manager get capabilities.autodetect)
default_open=$(env_manager get ui.main)
default_autoopen=$(env_manager get ui.autoopen)
default_container_prefix=$(env_manager get container.prefix)
default_log_level=$(env_manager get log.level)
default_history_file=$(env_manager get history.file)
default_history_size=$(env_manager get history.size)
default_legacy_cli=${HARBOR_LEGACY_CLI:-$(env_manager get legacy.cli)}
default_routine_runtime=$(env_manager get routine.runtime)

run_volumes_command() {
    case "$1" in
    --help | -h)
        echo "Harbor custom volume mounts"
        echo
        echo "Manage custom host volume mounts for Harbor services."
        echo "Volumes are injected into containers at startup."
        echo
        echo "Usage:"
        echo "  harbor volumes ls                  - Show all services with custom volumes"
        echo "  harbor volumes ls <service>        - Show volumes for a specific service"
        echo "  harbor volumes add <svc> <src>:<dest> - Add a volume mount"
        echo "  harbor volumes rm <service> <index> - Remove a volume by index"
        echo "  harbor volumes clear <service>     - Remove all custom volumes for a service"
        echo
        echo "Examples:"
        echo "  harbor volumes add ollama /data/models:/root/.ollama"
        echo "  harbor volumes add ollama /certs/ca.pem:/etc/ssl/certs/ca.pem"
        echo "  harbor volumes ls ollama"
        echo "  harbor volumes rm ollama 0"
        return 0
        ;;
    ls | list | "")
        if [ -n "$2" ]; then
            env_manager_arr "$2.volumes" ls
        else
            local found=false
            local env_file="$harbor_home/.env"
            grep "^HARBOR_.*_VOLUMES=" "$env_file" | while IFS='=' read -r key value; do
                value="${value#\"}"
                value="${value%\"}"
                if [ -n "$value" ]; then
                    found=true
                    local svc_upper="${key#HARBOR_}"
                    svc_upper="${svc_upper%_VOLUMES}"
                    local svc_lower
                    svc_lower=$(harbor_lower "$svc_upper" | tr '_' '-')
                    echo "$svc_lower:"
                    echo "$value" | tr ';' '\n' | while read -r vol; do
                        echo "  $vol"
                    done
                fi
            done
            if ! grep "^HARBOR_.*_VOLUMES=" "$env_file" 2>/dev/null | grep -qvE '=""$|="$|=$'; then
                log_info "No custom volumes configured"
            fi
        fi
        ;;
    add)
        local service="$2"
        local volume_spec="$3"
        if [ -z "$service" ] || [ -z "$volume_spec" ]; then
            echo "Usage: harbor volumes add <service> <source>:<dest>"
            return 1
        fi
        env_manager_arr "$service.volumes" add "$volume_spec"
        ;;
    rm | remove)
        local service="$2"
        local index="$3"
        if [ -z "$service" ]; then
            echo "Usage: harbor volumes rm <service> <index>"
            return 1
        fi
        env_manager_arr "$service.volumes" rm "$index"
        ;;
    clear)
        local service="$2"
        if [ -z "$service" ]; then
            echo "Usage: harbor volumes clear <service>"
            return 1
        fi
        env_manager_arr "$service.volumes" clear
        ;;
    *)
        run_volumes_command --help
        ;;
    esac
}

run_skills_command() {
    local skills_dir="$harbor_home/skills"

    # Extract description from SKILL.md frontmatter.
    # Handles ```skill wrapper, single-line and multi-line YAML descriptions.
    _skill_description() {
        local file="$1"
        local max_chars="${2:-80}"
        local found_start=false
        local in_description=false
        local desc=""

        while IFS= read -r line; do
            # Skip ```skill wrapper lines
            [[ "$line" =~ ^\`\`\` ]] && continue

            if [[ "$found_start" == false ]]; then
                [[ "$line" == "---" ]] && found_start=true
                continue
            fi

            # Second --- closes frontmatter
            [[ "$line" == "---" ]] && break

            # Parse description field
            if [[ "$line" =~ ^description:\ *\>\ *$ ]]; then
                in_description=true
                continue
            elif [[ "$line" =~ ^description:\ +(.*) ]]; then
                desc="${BASH_REMATCH[1]}"
                break
            elif [[ "$in_description" == true ]]; then
                if [[ "$line" =~ ^[a-zA-Z] ]]; then
                    break
                fi
                local trimmed="${line#"${line%%[![:space:]]*}"}"
                if [ -n "$trimmed" ]; then
                    desc="${desc:+$desc }$trimmed"
                fi
            fi
        done < "$file"

        if [ ${#desc} -gt "$max_chars" ]; then
            echo "${desc:0:$max_chars}..."
        else
            echo "$desc"
        fi
    }

    # Strip frontmatter and output content
    _skill_content() {
        local file="$1"
        local found_start=false
        local frontmatter_ended=false

        while IFS= read -r line; do
            if [[ "$frontmatter_ended" == true ]]; then
                echo "$line"
                continue
            fi

            # Skip ```skill wrapper lines
            [[ "$line" =~ ^\`\`\` ]] && continue

            if [[ "$found_start" == false ]]; then
                [[ "$line" == "---" ]] && found_start=true
                continue
            fi

            # Second --- closes frontmatter
            if [[ "$line" == "---" ]]; then
                frontmatter_ended=true
                continue
            fi
        done < "$file"
    }

    case "${1:-list}" in
    --help | -h)
        echo "Harbor skills"
        echo
        echo "Skills ship with the CLI and contain agent-ready documentation:"
        echo "workflow guides, command references, and copy-paste examples."
        echo
        echo "Usage:"
        echo "  harbor skills                    - List available skills"
        echo "  harbor skills list               - List available skills"
        echo "  harbor skills get <name>         - Show a skill"
        echo "  harbor skills get <name> --full  - Show a skill with all reference docs"
        echo "  harbor skills path [name]        - Print skill directory path"
        echo
        echo "Start here (for AI agents):"
        echo "  harbor skills get harbor"
        return 0
        ;;
    list | ls)
        if [ ! -d "$skills_dir" ]; then
            log_error "No skills directory found at $skills_dir"
            return 1
        fi

        local found=false
        for skill_file in "$skills_dir"/*/SKILL.md; do
            [ -f "$skill_file" ] || continue
            found=true
            local skill_name
            skill_name=$(basename "$(dirname "$skill_file")")
            local desc
            desc=$(_skill_description "$skill_file" 75)
            printf "  %-20s %s\n" "$skill_name" "$desc"
        done

        if [ "$found" = false ]; then
            log_info "No skills found in $skills_dir"
        fi
        ;;
    get)
        local skill_name="$2"
        if [ -z "$skill_name" ]; then
            log_error "Usage: harbor skills get <name>"
            return 1
        fi

        local skill_file="$skills_dir/$skill_name/SKILL.md"
        if [ ! -f "$skill_file" ]; then
            log_error "Skill not found: $skill_name"
            echo "Available skills:"
            run_skills_command list
            return 1
        fi

        _skill_content "$skill_file"

        # --full: append references and templates
        if [[ "${3:-}" == "--full" ]]; then
            local refs_dir="$skills_dir/$skill_name/references"
            if [ -d "$refs_dir" ]; then
                for ref_file in "$refs_dir"/*.md; do
                    [ -f "$ref_file" ] || continue
                    echo
                    echo "---"
                    echo
                    cat "$ref_file"
                done
            fi

            local templates_dir="$skills_dir/$skill_name/templates"
            if [ -d "$templates_dir" ]; then
                for tmpl_file in "$templates_dir"/*; do
                    [ -f "$tmpl_file" ] || continue
                    echo
                    echo "---"
                    echo
                    cat "$tmpl_file"
                done
            fi
        fi
        ;;
    path)
        local skill_name="$2"
        if [ -z "$skill_name" ]; then
            echo "$skills_dir"
        else
            local skill_path="$skills_dir/$skill_name"
            if [ ! -d "$skill_path" ]; then
                log_error "Skill not found: $skill_name"
                return 1
            fi
            echo "$skill_path"
        fi
        ;;
    *)
        run_skills_command --help
        ;;
    esac
}

main_entrypoint() {
    case "$1" in
    up | u | start | s)
        shift
        run_up "$@"
        ;;
    down | d)
        shift
        run_down "$@"
        ;;
    restart | r)
        shift
        run_restart "$@"
        ;;
    ps)
        shift
        run_ps "$@"
        ;;
    build)
        shift
        run_build "$@"
        ;;
    shell)
        shift
        run_shell "$@"
        ;;
    logs | log | l)
        shift
        run_logs "$@"
        ;;
    pull)
        shift
        run_pull "$@"
        ;;
    exec)
        shift
        run_exec "$@"
        ;;
    run)
        shift
        run_run "$@"
        ;;
    stats)
        shift
        run_stats "$@"
        ;;
    attach)
        shift
        run_attach "$@"
        ;;
    cmd)
        shift
        resolve_compose_command "$@"
        ;;
    help | --help | -h)
        show_help
        ;;
    hf)
        shift
        run_hf_command "$@"
        ;;
    tokscale)
        shift
        run_tokscale_cli "$@"
        ;;
    models)
        shift
        run_models_command "$@"
        ;;
    defaults)
        shift
        run_defaults_command "$@"
        ;;
    alias | aliases | a)
        shift
        env_manager_dict aliases "$@"
        ;;
    link | ln)
        shift
        link_cli "$@"
        ;;
    unlink | unln)
        shift
        unlink_cli "$@"
        ;;
    open | o)
        shift
        run_open "$@"
        ;;
    launch)
        shift
        run_launch_command "$@"
        ;;
    url)
        shift
        get_url "$@"
        ;;
    qr)
        shift
        print_service_qr "$@"
        ;;
    list | ls)
        shift
        get_services "$@"
        ;;
    version | --version | -v)
        shift
        show_version
        ;;
    smi)
        shift
        smi
        ;;
    top)
        shift
        nvidia_top
        ;;
    dive)
        shift
        run_dive "$@"
        ;;
    eject)
        shift
        eject "$@"
        ;;
    ollama)
        shift
        run_ollama_command "$@"
        ;;
    llamacpp)
        shift
        run_llamacpp_command "$@"
        ;;
    ikllamacpp)
        shift
        run_ikllamacpp_command "$@"
        ;;
    tgi)
        shift
        run_tgi_command "$@"
        ;;
    litellm)
        shift
        run_litellm_command "$@"
        ;;
    vllm)
        shift
        run_vllm_command "$@"
        ;;
    dmr)
        shift
        run_dmr_command "$@"
        ;;
    mlx)
        shift
        run_mlx_command "$@"
        ;;
    omlx)
        shift
        run_omlx_command "$@"
        ;;
    aphrodite)
        shift
        run_aphrodite_command "$@"
        ;;
    openai)
        shift
        run_open_ai_command "$@"
        ;;
    opencode)
        shift
        run_opencode_command "$@"
        ;;
    facts)
        shift
        run_facts_command "$@"
        ;;
    mi)
        shift
        run_mi_command "$@"
        ;;
    npcsh)
        shift
        run_npcsh_command "$@"
        ;;
    webui)
        shift
        run_webui_command "$@"
        ;;
    tabbyapi)
        shift
        run_tabbyapi_command "$@"
        ;;
    parllama)
        shift
        run_parllama_command "$@"
        ;;
    oterm)
        shift
        run_oterm_command "$@"
        ;;
    plandex | pdx)
        shift
        run_plandex_command "$@"
        ;;
    mistralrs)
        shift
        run_mistralrs_command "$@"
        ;;
    interpreter | opint)
        shift
        run_opint_command "$@"
        ;;
    cfd | cloudflared)
        shift
        $(compose_with_options "cfd") run cfd "$@"
        ;;
    cmdh)
        shift
        run_cmdh_command "$@"
        ;;
    fabric)
        shift
        run_fabric_command "$@"
        ;;
    parler)
        shift
        run_parler_command "$@"
        ;;
    photoprism)
        shift
        run_photoprism_command "$@"
        ;;
    airllm)
        shift
        run_airllm_command "$@"
        ;;
    txtai)
        shift
        run_txtai_command "$@"
        ;;
    aider)
        shift
        run_aider_command "$@"
        ;;
    nanobot)
        shift
        run_nanobot_command "$@"
        ;;
    chatui)
        shift
        run_chatui_command "$@"
        ;;
    comfyui)
        shift
        run_comfyui_command "$@"
        ;;
    aichat)
        shift
        run_aichat_command "$@"
        ;;
    omnichain)
        shift
        run_omnichain_command "$@"
        ;;
    lmeval | lm_eval)
        shift
        run_lm_eval_command "$@"
        ;;
    sglang)
        shift
        run_sglang_command "$@"
        ;;
    jupyter)
        shift
        run_jupyter_command "$@"
        ;;
    ol1)
        shift
        run_ol1_command "$@"
        ;;
    ktransformers)
        shift
        run_ktransformers_command "$@"
        ;;
    openhands | oh)
        shift
        run_openhands_command "$@"
        ;;
    stt)
        shift
        run_stt_command "$@"
        ;;
    speaches)
        shift
        run_speaches_command "$@"
        ;;
    boost)
        shift
        run_boost_command "$@"
        ;;
    nexa)
        shift
        run_nexa_command "$@"
        ;;
    repopack)
        shift
        run_repopack_command "$@"
        ;;
    k6)
        shift
        run_k6_command "$@"
        ;;
    promptfoo | pf)
        shift
        run_promptfoo_command "$@"
        ;;
    webtop)
        shift
        run_webtop_command "$@"
        ;;
    langflow)
        shift
        run_langflow_command "$@"
        ;;
    kobold)
        shift
        run_kobold_command "$@"
        ;;
    morphic)
        shift
        run_morphic_command "$@"
        ;;
    gptme)
        shift
        run_gptme_command "$@"
        ;;
    hermes)
        shift
        run_hermes_command "$@"
        ;;
    mcp)
        shift
        run_mcp_command "$@"
        ;;
    migrate)
        shift
        run_migrate_command "$@"
        ;;
    modularmax)
        shift
        run_modularmax_command "$@"
        ;;
    openfang)
        shift
        run_openfang_command "$@"
        ;;
    tunnel | t)
        shift
        establish_tunnel "$@"
        ;;
    tunnels)
        shift
        env_manager_arr services.tunnels "$@"
        ;;
    config)
        shift
        env_manager "$@"
        ;;
    profile | profiles | p)
        shift
        run_profile_command "$@"
        ;;
    gum)
        shift
        run_gum "$@"
        ;;
    fixfs)
        shift
        run_fixfs "$@"
        ;;
    info)
        shift
        sys_info
        ;;
    update)
        shift
        update_harbor "$@"
        ;;
    how)
        shift
        run_harbor_how_command "$@"
        ;;
    find)
        shift
        run_harbor_find "$@"
        ;;
    home)
        shift
        echo "$harbor_home"
        ;;
    vscode)
        shift
        open_home_code
        ;;
    doctor)
        shift
        run_harbor_doctor "$@"
        ;;
    bench)
        shift
        run_bench_command "$@"
        ;;
    history | h)
        shift
        run_history "$@"
        ;;
    size)
        shift
        run_harbor_size "$@"
        ;;
    env)
        shift
        run_harbor_env "$@"
        ;;
    dev)
        shift
        run_harbor_dev "$@"
        ;;
    tools)
        shift
        run_harbor_tools "$@"
        ;;
    eval)
        shift
        run_promptfoo_eval "$@"
        ;;
    routine)
        shift
        run_routine "$@"
        ;;
    volumes)
        shift
        run_volumes_command "$@"
        ;;
    skills)
        shift
        run_skills_command "$@"
        ;;
    completion)
        shift
        run_completion_command "$@"
        ;;
    *)
        return $scramble_exit_code
        ;;
    esac
}

check_migration_needed() {
    # Skip check for certain commands that don't need migration check
    local skip_commands="migrate|help|--help|-h|version|--version|-v"
    if [[ "$1" =~ ^($skip_commands)$ ]]; then
        return 0
    fi

    # Check if services directory exists and is populated
    if [ -d "$harbor_home/services" ]; then
        # Check if services directory has content
        if [ -n "$(ls -A "$harbor_home/services" 2>/dev/null)" ]; then
            # Services directory exists and has content, assume migrated
            return 0
        fi
    fi

    # Check for service directories at root (excluding known infrastructure dirs)
    local has_old_structure=false
    local exclude_pattern="^(app|docs|routines|scripts|profiles|shared|harbor|tools|skills|services|node_modules|dist|\..*)$"

    while IFS= read -r dir; do
        local basename=$(basename "$dir")
        if [[ ! "$basename" =~ $exclude_pattern ]]; then
            # Check if this looks like a service directory (has corresponding compose file)
            if [ -f "$harbor_home/compose.$basename.yml" ] || [ -f "$harbor_home/compose.$basename.ts" ]; then
                has_old_structure=true
                break
            fi
        fi
    done < <(find "$harbor_home" -maxdepth 1 -type d 2>/dev/null)

    # Check for compose files at root (excluding base compose.yml)
    if [ "$has_old_structure" = false ]; then
        if ls "$harbor_home"/compose.*.yml "$harbor_home"/compose.*.ts 2>/dev/null | grep -v "^$harbor_home/compose.yml$" >/dev/null; then
            has_old_structure=true
        fi
    fi

    if [ "$has_old_structure" = true ]; then
        echo ""
        echo "╔════════════════════════════════════════════════════════════╗"
        echo "║                  🔄 MIGRATION REQUIRED                     ║"
        echo "╚════════════════════════════════════════════════════════════╝"
        echo ""
        echo "Harbor 0.4.0 introduces a new directory structure."
        echo "Your installation needs to be migrated to continue."
        echo ""
        echo "What changed:"
        echo "  • Service files moved to services/ directory"
        echo "  • Cleaner root directory structure"
        echo "  • Better organization and maintainability"
        echo ""
        echo "To migrate your installation:"
        echo "  1. Review changes: ${c_g}harbor migrate --dry-run${c_nc}"
        echo "  2. Run migration:  ${c_g}harbor migrate${c_nc}"
        echo "  3. Learn more:     ${c_g}docs/0.4.0-Migration-Guide.md${c_nc}"
        echo ""
        echo "The migration is safe and includes automatic backups."
        echo ""

        # Don't exit, just warn for now to allow migrate command to run
        return 0
    fi

    return 0
}

# Check if migration is needed (but don't block execution)
check_migration_needed "$1"

# Call the main logic with argument swapping
if swap_and_retry main_entrypoint "$@"; then
    exit_code=0
else
    exit_code=$?
fi

if [ $exit_code -eq 0 ]; then
    exit 0
fi

if [ $exit_code -ne $scramble_exit_code ]; then
    exit $exit_code
fi

if [ $# -eq 0 ]; then
    show_help
else
    suggestion=$(suggest_command "$1")
    log_error "Unknown command: $1"
    if [ -n "$suggestion" ]; then
        log_info "Did you mean: ${c_g}harbor ${suggestion}${c_nc}?"
    elif service_compose_exists "$1"; then
        log_info "'$1' is a service. To start it: ${c_g}harbor up $1${c_nc}"
    else
        local svc_suggestion
        svc_suggestion=$(_suggest_service "$1")
        if [ -n "$svc_suggestion" ]; then
            log_info "Did you mean the service: ${c_g}harbor up $svc_suggestion${c_nc}?"
        fi
    fi
    log_info "Run 'harbor help' for a list of commands."
fi

exit 1
