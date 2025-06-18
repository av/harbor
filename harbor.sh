#!/usr/bin/env bash

set -eo pipefail

# ========================================================================
# == Functions
# ========================================================================

show_version() {
    echo "Harbor CLI version: $version"
}

show_help() {
    show_version
    echo "Usage: $0 <command> [options]"
    echo
    echo "Compose Setup Commands:"
    echo "  up|u [handle(s)]        - Start the service(s)"
    echo "    up --tail             - Start and tail the logs"
    echo "    up --open             - Start and open in the browser"
    echo "  down|d                  - Stop and remove the containers"
    echo "  restart|r [handle]      - Down then up"
    echo "  ps                      - List the running containers"
    echo "  logs|l <handle>         - View the logs of the containers"
    echo "  exec <handle> [command] - Execute a command in a running service"
    echo "  pull <handle>           - Pull the latest images"
    echo "  dive <handle>           - Run the Dive CLI to inspect Docker images"
    echo "  run <alias>             - Run a command defined as an alias"
    echo "  run <handle> [command]  - Run a one-off command in a service container"
    echo "  shell <handle>          - Load shell in the given service main container"
    echo "  build <handle>          - Build the given service"
    echo "  stats                   - Show resource usage statistics"
    echo "  cmd <handle>            - Print the docker compose command"
    echo
    echo "Setup Management Commands:"
    echo "  webui     - Configure Open WebUI Service"
    echo "  llamacpp  - Configure llamacpp service"
    echo "  tgi       - Configure text-generation-inference service"
    echo "  litellm   - Configure LiteLLM service"
    echo "  langflow  - Configure Langflow UI Service"
    echo "  openai    - Configure OpenAI API keys and URLs"
    echo "  vllm      - Configure VLLM service"
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
    echo
    echo "Service CLIs:"
    echo "  ollama     - Run Ollama CLI (docker). Service should be running."
    echo "  aider             - Launch Aider CLI"
    echo "  aichat            - Run aichat CLI"
    echo "  interpreter|opint - Launch Open Interpreter CLI"
    echo "  fabric            - Run Fabric CLI"
    echo "  plandex           - Launch Plandex CLI"
    echo "  cmdh              - Run cmdh CLI"
    echo "  parllama          - Launch Parllama - TUI for chatting with Ollama models"
    echo "  bench             - Run and manage Harbor Bench"
    echo "  openhands|oh      - Run OpenHands service"
    echo "  repopack          - Run the Repopack CLI"
    echo "  nexa              - Run the Nexa CLI, configure the service"
    echo "  gptme             - Run gptme CLI, configure the service"
    echo "  hf                - Run the Harbor's Hugging Face CLI. Expanded with a few additional commands."
    echo "    hf dl           - HuggingFaceModelDownloader CLI"
    echo "    hf parse-url    - Parse file URL from Hugging Face"
    echo "    hf token        - Get/set the Hugging Face Hub token"
    echo "    hf cache        - Get/set the path to Hugging Face cache"
    echo "    hf find <query> - Open HF Hub with a query (trending by default)"
    echo "    hf path <spec>  - Print a folder in HF cache for a given model spec"
    echo "    hf *            - Anything else is passed to the official Hugging Face CLI"
    echo "  k6                - Run K6 CLI"
    echo
    echo "Harbor CLI Commands:"
    echo "  open <handle>                 - Open a service in the default browser"
    echo
    echo "  url <handle>                  - Get the URL for a service"
    echo "    url <handle>                         - Url on the local host"
    echo "    url [-a|--adressable|--lan] <handle> - (supposed) LAN URL"
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
    echo "    config set <field> <value>  - Get a specific config value"
    echo "    config reset                - Reset Harbor configuration to default .env"
    echo "    config update               - Merge upstream config changes from default .env"
    echo
    echo "  env <service> [key] [value]   - Manage override.env variables for a service"
    echo "    env <service>               - List all variables for a service"
    echo "    env <service> <key>         - Get a specific variable for a service"
    echo "    env <service> <key> <value> - Set a specific variable for a service"
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
    echo "  find <file>           - Find a file in the caches visible to Harbor"
    echo "  ls|list [--active|-a] - List available/active Harbor services"
    echo "  ln|link [--short]     - Create a symlink to the CLI, --short for 'h' link"
    echo "  unlink                - Remove CLI symlinks"
    echo "  eject                 - Eject the Compose configuration, accepts same options as 'up'"
    echo "  help|--help|-h        - Show this help message"
    echo "  version|--version|-v  - Show the CLI version"
    echo "  gum                   - Run the Gum terminal commands"
    echo "  update [-l|--latest]  - Update Harbor. --latest for the dev version"
    echo "  info                  - Show system information for debug/issues"
    echo "  doctor                - Tiny troubleshooting script"
    echo "  how                   - Ask questions about Harbor CLI, uses cmdh under the hood"
    echo "  smi                   - Show NVIDIA GPU information"
    echo "  top                   - Run nvtop to monitor GPU usage"
    echo "  size                  - Print the size of caches Harbor is aware of"
    echo
    echo "Harbor Workspace Commands:"
    echo "  home    - Show path to the Harbor workspace"
    echo "  vscode  - Open Harbor Workspace in VS Code"
    echo "  fixfs   - Fix file system ACLs for service volumes"
}

run_harbor_doctor() {
    log_info "Running Harbor Doctor..."
    has_errors=false

    # Check if Docker is installed and running
    if command -v docker &>/dev/null && docker info &>/dev/null; then
        log_info "${ok} Docker is installed and running"
    else
        log_error "${nok} Docker is not installed or not running. Please install or start Docker."
        has_errors=true
    fi

    # Check if Docker Compose (v2) is installed
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
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

    # Check if the Harbor workspace directory exists
    if [ -d "$harbor_home" ]; then
        log_info "${ok} Harbor home: $harbor_home"
    else
        log_error "${nok} Harbor home does not exist or is not reachable."
        has_errors=true
    fi

    # Check if the default profile file exists and is readable
    if [ -f $default_profile ] && [ -r $default_profile ]; then
        log_info "${ok} Default profile exists and is readable"
    else
        log_error "${nok} Default profile is missing or not readable. Please ensure it exists and has the correct permissions."
        has_errors=true
    fi

    # Check if the .env file exists and is readable
    if [ -f ".env" ] && [ -r ".env" ]; then
        log_info "${ok} Current profile (.env) exists and is readable"
    else
        log_error "${nok} Current profile (.env) is missing or not readable. Please ensure it exists and has the correct permissions."
        has_errors=true
    fi

    # Check if CLI is linked
    if [ -L "$(eval echo "$(env_manager get cli.path)")/$(env_manager get cli.name)" ]; then
        log_info "${ok} CLI is linked"
    else
        log_error "${nok} CLI is not linked. Run 'harbor link' to create a symlink."
        has_errors=true
    fi

    if has_nvidia; then
        log_info "${ok} NVIDIA GPU is available"
    else
        log_warn "${nok} NVIDIA GPU is not available. NVIDIA GPU support may not work."
    fi

    # Check if nvidia-container-toolkit is installed
    if has_nvidia_ctk; then
        log_info "${ok} NVIDIA Container Toolkit is installed"
    else
        log_warn "${nok} NVIDIA Container Toolkit is not installed. NVIDIA GPU support may not work."
    fi

    # Check if rocm is installed
    if has_rocm; then
        log_info "${ok} ROCm is installed"
    else
	log_warn "${nok} ROCm in not installed. AMD GPU support may not work."
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
    command -v nvidia-container-toolkit &>/dev/null
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

# [v12.0] A new critical helper for platform detection.
has_apple_silicon_gpu() {
    [[ "$(uname)" == "Darwin" && "$(uname -m)" == "arm64" ]]
}

# [v12.0] Utility to check if a native configuration contract exists.
has_native_config() {
    [[ -f "$harbor_home/$1/${1}_native.yml" ]]
}

# [v14.1] Loads native configuration using local Deno if available, otherwise falls back to Docker.
_harbor_load_native_config() {
    local service_handle="$1"
    local config_file="$harbor_home/$service_handle/${service_handle}_native.yml"
    if [[ ! -f "$config_file" ]]; then
        # Fail silently with an error code. The calling function can decide if this is a warning.
        return 1
    fi

    local output
    local exit_code

    # Per user request, try local 'deno' first for performance, then fallback to Docker for robustness.
    if command -v deno &>/dev/null; then
        log_debug "Using host 'deno' to load config for '${service_handle}'."
        # The `2>&1` redirects stderr to stdout, so we capture everything in the 'output' variable.
        output=$(deno run -A "$harbor_home/routines/loadNativeConfig.js" "$config_file" 2>&1)
        exit_code=$?
    else
        log_debug "Host 'deno' not found. Using Docker fallback to load config for '${service_handle}'."
        output=$(docker run --rm \
            -v "$harbor_home:$harbor_home" \
            -w "$harbor_home" \
            denoland/deno:distroless \
            run -A "$harbor_home/routines/loadNativeConfig.js" "$config_file" 2>&1)
        exit_code=$?
    fi

    # Check if the Deno script (either local or containerized) failed or produced no output.
    if [[ $exit_code -ne 0 || -z "$output" ]]; then
        log_error "Failed to load native config for '${service_handle}'. Parser output:"
        # Log the captured output, indented for readability. This gives the user the exact error from Deno.
        echo "$output" | sed 's/^/  /' >&2
        return 1
    fi

    # Return the raw output string for the caller to `eval`. This is part of the "Scoped Eval Loader" pattern.
    echo "$output"
}

# [v12.0] Determines configured execution preference (native or container).
# This is the canonical source of user *intent*.
_harbor_get_configured_execution_preference() {
    local service_handle="$1"
    if "${_SKIP_NATIVE:-false}"; then echo "CONTAINER"; return 0; fi
    if ! has_native_config "$service_handle"; then echo "CONTAINER"; return 0; fi
    local service_pref; service_pref=$(env_manager --silent get "${service_handle}.execution_preference")
    if [[ "$service_pref" == "native" ]]; then echo "NATIVE"; return 0; fi
    if [[ "$service_pref" == "container" ]]; then echo "CONTAINER"; return 0; fi
    local global_pref; global_pref=$(env_manager --silent get execution.preference)
    if [[ "$global_pref" == "native" ]]; then echo "NATIVE"; return 0; fi
    if [[ "$global_pref" == "container" ]]; then echo "CONTAINER"; return 0; fi
    local config_vars; config_vars=$(_harbor_load_native_config "$service_handle")
    if [[ -z "$config_vars" ]]; then echo "CONTAINER"; return 0; fi
    eval "$config_vars"
    if has_apple_silicon_gpu && [[ "${NATIVE_REQUIRES_GPU:-false}" == "true" ]]; then
        echo "NATIVE"; return 0
    fi
    echo "CONTAINER"; return 0
}

# [v12.0] Determines live runtime state by probing the system.
# This is the canonical source of system *state*.
_harbor_get_running_service_runtime() {
    local service_handle="$1"
    if has_native_config "$service_handle"; then
        local config_vars; config_vars=$(_harbor_load_native_config "$service_handle")
        if [[ -n "$config_vars" ]]; then
            eval "$config_vars"
            if [[ -n "$NATIVE_DAEMON_COMMAND" ]] && pgrep -f "$NATIVE_DAEMON_COMMAND" >/dev/null 2>&1; then
                echo "NATIVE"; return 0
            fi
        fi
    fi
    if docker compose ps --services --filter "status=running" | grep -q "^${service_handle}$"; then
        echo "CONTAINER"; return 0
    fi
    echo ""
}

# [v15.1 CORE] Builds a comprehensive "context object" for a given service.
# This function is a cornerstone of the hybrid system. It queries all configuration
# sources (.env file, _native.yml contract) and live system state (docker ps, pgrep)
# to produce a single, evaluatable string of Bash variables. Downstream functions
# can then `eval` this context to get a complete, consistent view of a service.
#
# DESIGN: This "Context Object" pattern adheres to the DRY principle. Instead of
# each function making multiple calls to different helpers, they make one call to
# this function, simplifying their logic immensely. The use of namespacing during
# eval prevents variable collisions.
#
# @param {string} service_handle The service to build context for.
# @return {string} A string of semicolon-separated `local` variable assignments.
_harbor_build_service_context() {
    local service_handle="$1"
    local context_string=""

    # --- Static Handle and Eligibility ---
    context_string+="local HANDLE='$service_handle';"
    if ! has_native_config "$service_handle"; then
        context_string+="local IS_ELIGIBLE='false';"
    else
        context_string+="local IS_ELIGIBLE='true';"

        # --- Load Baseline Config from YAML ---
        local static_config; static_config=$(_harbor_load_native_config "$service_handle")
        # Eval into temporary, suffixed variables to avoid collisions
        eval "$(echo "$static_config" | sed 's/local /local _from_yaml_/g')"

        # --- Apply .env Overrides and Build Final Config ---
        # For each native parameter, check for an override in .env. If it exists,
        # use it. Otherwise, use the value from the YAML file.
        local final_executable; final_executable=$(env_manager --silent get "${service_handle}.native.executable" || echo "${_from_yaml_NATIVE_EXECUTABLE:-}")
        context_string+="local NATIVE_EXECUTABLE='$final_executable';"

        local final_daemon_cmd; final_daemon_cmd=$(env_manager --silent get "${service_handle}.native.daemon_command" || echo "${_from_yaml_NATIVE_DAEMON_COMMAND:-}")
        context_string+="local NATIVE_DAEMON_COMMAND='$final_daemon_cmd';"

        local final_port; final_port=$(env_manager --silent get "${service_handle}.native.port" || echo "${_from_yaml_NATIVE_PORT:-}")
        context_string+="local NATIVE_PORT='$final_port';"

        # Pass through non-overridable values directly
        context_string+="local NATIVE_REQUIRES_GPU='${_from_yaml_NATIVE_REQUIRES_GPU:-false}';"
        context_string+="local NATIVE_PROXY_IMAGE='${_from_yaml_NATIVE_PROXY_IMAGE:-}';"
        context_string+="local NATIVE_PROXY_COMMAND='${_from_yaml_NATIVE_PROXY_COMMAND:-}';"
        context_string+="local NATIVE_PROXY_HEALTHCHECK_TEST='${_from_yaml_NATIVE_PROXY_HEALTHCHECK_TEST:-}';"
        context_string+="local -a NATIVE_ENV_VARS_LIST=(${_from_yaml_NATIVE_ENV_VARS_LIST});"
        context_string+="local -a NATIVE_DEPENDS_ON_CONTAINERS=(${_from_yaml_NATIVE_DEPENDS_ON_CONTAINERS});"
        context_string+="local -a NATIVE_ENV_OVERRIDES_ARRAY=(${_from_yaml_NATIVE_ENV_OVERRIDES_ARRAY});"
    fi

    # --- Add Live System State ---
    local preference; preference=$(_harbor_get_configured_execution_preference "$service_handle")
    context_string+="local PREFERENCE='$preference';"
    local runtime; runtime=$(_harbor_get_running_service_runtime "$service_handle")
    context_string+="local RUNTIME='$runtime';"

    echo "$context_string"
}

# [v12.0] A new helper to get a canonical list of all services Harbor knows.
_harbor_get_all_possible_services() {
    local all_services
    # Get all services defined in all possible compose files, in eject mode.
    all_services=$($(compose_with_options --eject-mode "*") config --services)
    # Find all services that have a native contract
    find "$harbor_home" -maxdepth 2 -name "*_native.yml" -print0 2>/dev/null | xargs -0 -I {} basename {} _native.yml | while read -r native_service; do
        all_services+=$'\n'"$native_service"
    done
    # Return a unique, sorted list
    echo "$all_services" | sort -u
}

has_rocm() {
    command -v rocm-smi &>/dev/null
}

has_modern_compose() {
    local compose_version=$(docker compose version --short | sed -e 's/-desktop//')

    # Handle potential empty or invalid version string
    if [ -z "$compose_version" ]; then
        log_debug "Could not detect Docker Compose version"
        return 1
    fi

    # Split version into components, defaulting to 0 if not present
    local major_version=$(echo "$compose_version" | cut -d. -f1 || echo "0")
    local minor_version=$(echo "$compose_version" | cut -d. -f2 || echo "0")
    local patch_version=$(echo "$compose_version" | cut -d. -f3 || echo "0")

    # log_debug "Docker Compose version: $major_version.$minor_version.$patch_version"

    # Compare major version first
    if [ "$major_version" -gt "$desired_compose_major" ]; then
        return 0
    elif [ "$major_version" -lt "$desired_compose_major" ]; then
        log_debug "Major version is less than $desired_compose_major"
        return 1
    fi

    # If major versions are equal, compare minor versions
    if [ "$minor_version" -gt "$desired_compose_minor" ]; then
        return 0
    elif [ "$minor_version" -lt "$desired_compose_minor" ]; then
        log_debug "Minor version is less than $desired_compose_minor"
        return 1
    fi

    # If minor versions are equal, compare patch versions
    if [ "$patch_version" -lt "$desired_compose_patch" ]; then
        log_debug "Patch version is less than $desired_compose_patch"
        return 1
    fi

    return 0
}

# shellcheck disable=SC2034
__anchor_fns=true

resolve_compose_files() {
    # Find all .yml files in the specified base directory,
    # but do not go into subdirectories
    find "$base_dir" -maxdepth 1 -name "*.yml" |
        # For each file, count the number of dots in the filename
        # and prepend this count to the filename
        awk -F. '{print NF-1, $0}' |
        # Sort the files based on the
        # number of dots, in ascending order
        sort -n |
        # Remove the dot count, leaving
        # just the sorted filenames
        cut -d' ' -f2-
}

run_routine() {
    local routine_name="$1"

    if [ -z "$routine_name" ]; then
        log_error "run_routine requires a routine name"
        return 1
    fi

    local routine_path="$harbor_home/routines/$routine_name.js"

    if [ ! -f $routine_path ]; then
        log_error "Routine '$routine_name' not identified"
        return 1
    fi

    shift

    log_debug "Running routine: $routine_name"
    docker run --rm \
        -v "$harbor_home:$harbor_home" \
        -v harbor-deno-cache:/deno-dir:rw \
        -w "$harbor_home" \
        -e "HARBOR_LOG_LEVEL=$default_log_level" \
        denoland/deno:distroless \
        run -A --unstable-sloppy-imports \
        $routine_path "$@"
}

routine_compose_with_options() {
    local options=("${default_options[@]}" "${default_capabilities[@]}")

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

        if has_apple_silicon_gpu; then
            options+=("apple-silicon-gpu")
        fi
    fi

    run_routine mergeComposeFiles "$@" "${options[@]}"
}

# -----------------------------------------------------------------------------
# v12.0 CORE: Context-Aware Composition Engine (Planner/Executor Model)
# -----------------------------------------------------------------------------

# [v12.0 HELPER] Generates the transient environment file for C->N configuration.
__compose_generate_transient_env_file() {
    local -a native_targets=("${@}")
    local temp_file; temp_file=$(mktemp)
    for service_handle in "${native_targets[@]}"; do
        local context; context=$(_harbor_build_service_context "$service_handle")
        eval "$context"
        if [[ ${#NATIVE_ENV_OVERRIDES_ARRAY[@]} -gt 0 ]]; then
            for override in "${NATIVE_ENV_OVERRIDES_ARRAY[@]}"; do
                local final_override; final_override=$(echo "$override" | sed "s|{{.native_port}}|${NATIVE_PORT:-}|g")
                echo "$final_override" >> "$temp_file"
            done
        fi
    done
    if [ -s "$temp_file" ]; then echo "$temp_file"; else rm "$temp_file"; echo ""; fi
}

# [v12.0 HELPER] Generates the dynamic proxy docker compose file for C->N dependency.
__compose_generate_proxy_file() {
    local -a native_targets=("${@}")
    local dynamic_compose_file="${harbor_home}/compose.harbor.native-proxy.yml"
    rm -f "$dynamic_compose_file" 2>/dev/null
    local all_proxy_configs=""
    for service_handle in "${native_targets[@]}"; do
        local context; context=$(_harbor_build_service_context "$service_handle")
        eval "$context"
        if [[ "$IS_ELIGIBLE" == "true" && -n "$NATIVE_PROXY_IMAGE" ]]; then
            local proxy_command_templated; proxy_command_templated=$(_run_bash_template "${NATIVE_PROXY_COMMAND}" "${NATIVE_PORT}")
            local proxy_healthcheck_test_templated; proxy_healthcheck_test_templated=$(_run_bash_template "${NATIVE_PROXY_HEALTHCHECK_TEST}" "${NATIVE_PORT}")
            all_proxy_configs+=$(cat <<EOF

  ${service_handle}:
    image: ${NATIVE_PROXY_IMAGE}
    container_name: ${default_container_prefix}.${service_handle}
    command: ${proxy_command_templated}
    ports: ["${NATIVE_PORT}:${NATIVE_PORT}"]
    healthcheck: {test: ${proxy_healthcheck_test_templated}, interval: 2s, timeout: 5s, retries: 30}
    networks: [harbor-network]
EOF
)
        fi
    done
    if [[ -n "$all_proxy_configs" ]]; then
        echo -e "version: '3.8'\nservices:${all_proxy_configs}" > "${dynamic_compose_file}"
        echo "${dynamic_compose_file}"
    else
        echo ""
    fi
}

# [v12.0 PLANNER] The legacy file-discovery loop, adapted to populate an array.
# This respects the original author's logic while integrating into the new model.
# It populates the global _COMPOSITION_FILES array.
__compose_get_static_file_list_legacy() {
    _COMPOSITION_FILES=("$base_dir/compose.yml")
    local -a local_options=("${default_options[@]}" "${default_capabilities[@]}")
    local -a user_args=("$@")

    # This logic block is adapted directly from the original `compose_with_options`
    # to maintain its specific file resolution behavior.
    if [[ " ${user_args[*]} " =~ " --no-defaults " ]]; then
        local_options=()
    fi
    for arg in "${user_args[@]}"; do
        if [[ "$arg" != "--no-defaults" ]]; then
            local_options+=("$arg")
        fi
    done

    if [ "$default_auto_capabilities" = "true" ]; then
        if has_nvidia && has_nvidia_ctk; then local_options+=("nvidia"); fi
        if has_nvidia_cdi; then local_options+=("cdi"); fi
        if has_rocm; then local_options+=("rocm"); fi
        if has_modern_compose; then local_options+=("mdc"); fi
        if has_apple_silicon_gpu; then local_options+=("apple-silicon-gpu"); fi
    fi

    for file in $(resolve_compose_files); do
        if [ -f "$file" ]; then
            local filename; filename=$(basename "$file")
            local match=false
            if [[ $filename == *".x."* ]]; then
                local cross; cross="${filename#compose.x.}"; cross="${cross%.yml}"
                local -a filename_parts; filename_parts=(${cross//./ })
                local all_matched=true
                for part in "${filename_parts[@]}"; do
                    if is_capability "$part"; then
                        if [[ ! " ${local_options[*]} " =~ " ${part} " ]]; then all_matched=false; break; fi
                    else
                        if [[ ! " ${local_options[*]} " =~ " ${part} " ]] && [[ ! " ${local_options[*]} " =~ " * " ]]; then all_matched=false; break; fi
                    fi
                done
                if $all_matched; then _COMPOSITION_FILES+=("$file"); fi
                continue
            fi
            for option in "${local_options[@]}"; do
                if [[ $option == "*" ]]; then
                    if ! is_capability_file "$filename"; then match=true; fi
                    break
                fi
                if [[ $filename == *".$option."* ]]; then match=true; break; fi
            done
            if $match; then _COMPOSITION_FILES+=("$file"); fi
        fi
    done
}

# [v12.0 UNIFIED COMPOSER] The new, primary composition function.
# It orchestrates the Planner/Executor model to produce a final command string.
compose_with_options() {
    local base_dir="$PWD"
    local -g _COMPOSITION_FILES=() # A temporary global array for this transaction.
    local -a args_for_planner=()
    local eject_mode=false

    for arg in "$@"; do
        if [[ "$arg" == "--eject-mode" ]]; then
            eject_mode=true
        else
            args_for_planner+=("$arg")
        fi
    done

    # 1. Plan Part 1: Get static files using the adapted legacy logic.
    __compose_get_static_file_list_legacy "${args_for_planner[@]}"

    # 2. Plan Part 2: Generate dynamic files if not in eject mode.
    if ! $eject_mode; then
        local -a native_targets_in_scope=()
        local services_to_check=("${args_for_planner[@]}")
        # If no services specified, check defaults for native eligibility.
        if [[ ${#services_to_check[@]} -eq 0 || ( ${#services_to_check[@]} -eq 1 && " ${services_to_check[0]} " =~ " --no-defaults " ) ]]; then
           services_to_check=("${default_options[@]}")
        fi

        for service in "${services_to_check[@]}"; do
            if [[ "$service" == --* ]]; then continue; fi
            if [[ "$(_harbor_get_configured_execution_preference "$service")" == "NATIVE" ]]; then
                native_targets_in_scope+=("$service")
            fi
        done

        local unique_native_targets; unique_native_targets=$(echo "${native_targets_in_scope[@]}" | tr ' ' '\n' | sort -u)
        if [[ -n "$unique_native_targets" ]]; then
            local proxy_file_path; proxy_file_path=$(__compose_generate_proxy_file $unique_native_targets)
            if [[ -n "$proxy_file_path" ]]; then
                _COMPOSITION_FILES+=("$proxy_file_path")
            fi
        fi
    fi

    # 3. Execute: Pass the final file list to the Deno high-speed merger.
    local merged_compose_file="$harbor_home/merged.compose.yml"
    printf '%s\n' "${_COMPOSITION_FILES[@]}" | docker run --rm -i \
        -v "$harbor_home:$harbor_home" -v harbor-deno-cache:/deno-dir:rw \
        -w "$harbor_home" denoland/deno:distroless \
        run -A --unstable-sloppy-imports "$harbor_home/routines/mergeComposeFiles.js" \
        --output "$merged_compose_file"

    # 4. Construct Final Command String.
    echo "docker compose -f $merged_compose_file"
}


# [v10.0 CORE] A unified dispatcher to handle all runtime-aware commands.
# This consolidates all the repetitive if/elif/else logic into a single,
# maintainable function, fulfilling the DRY principle.
#
# @param {string} command_name The command to execute (e.g., "logs", "shell")
# @param {string} service_handle The target service
# @param {...string} args The remaining arguments for the command
_dispatch_command() {
    local command_name="$1"
    local service_handle="$2"
    shift 2
    local -a args=("$@")

    if [ -z "$service_handle" ]; then
        log_error "No service handle provided to the '${command_name}' command."
        return 1
    fi

    # Build the service context to get all necessary info.
    local context; context=$(_harbor_build_service_context "$service_handle")
    eval "$context" # Safely evaluates the context into local variables

    # Primary dispatch based on the requested command
    case "$command_name" in
        logs)
            case "$RUNTIME" in
                NATIVE)
                    local log_file="${LOG_DIR}/harbor-${HANDLE}-native.log"
                    if [[ -f "$log_file" ]]; then
                        log_info "Tailing native logs for '${HANDLE}' from: ${log_file}"
                        tail -n 100 -f "$log_file"
                    else
                        log_error "Native log file not found for '${HANDLE}' at ${log_file}."
                    fi
                    ;;
                CONTAINER)
                    $(compose_with_options "$HANDLE") logs -f "$HANDLE" "${args[@]}"
                    ;;
                *)
                    log_error "Service '${HANDLE}' is not running."
                    return 1
                    ;;
            esac
            ;;
        shell)
            case "$RUNTIME" in
                NATIVE)
                    log_error "'shell' command is not applicable to the native process '${HANDLE}'."
                    log_warn "You can open a new terminal on your host to interact with it."
                    return 1
                    ;;
                CONTAINER)
                    $(compose_with_options "$HANDLE") exec "$HANDLE" "${args[0]:-bash}"
                    ;;
                *)
                    log_error "Service '${HANDLE}' is not running."
                    return 1
                    ;;
            esac
            ;;
        exec)
            case "$RUNTIME" in
                NATIVE)
                    log_error "'exec' command is for containers and not applicable to the native process '${HANDLE}'."
                    log_warn "To run a one-off command with the native toolchain, use 'harbor run ${HANDLE} <command...>'."
                    return 1
                    ;;
                CONTAINER)
                    $(compose_with_options "$HANDLE") exec "$HANDLE" "${args[@]}"
                    ;;
                *)
                    log_error "Service '${HANDLE}' is not running."
                    return 1
                    ;;
            esac
            ;;
        *)
            log_error "Unknown command '${command_name}' passed to internal dispatcher."
            return 1
            ;;
    esac
}


is_capability() {
    local capability="$1"
    local capabilities=("nvidia" "mdc" "cdi" "apple-silicon-gpu" "${default_capabilities[@]}")

    for cap in "${capabilities[@]}"; do
        if [ "$cap" = "$capability" ]; then
            return 0
        fi
    done

    return 1
}

is_capability_file() {
    local filename="$1"
    local capabilities=("nvidia" "mdc" "cdi" "apple-silicon-gpu" "${default_capabilities[@]}")

    for cap in "${capabilities[@]}"; do
        if [[ $filename == *".$cap."* ]]; then
            return 0
        fi
    done

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

    local cmd=$(compose_with_options "$@")

    if $is_human; then
        echo "$cmd" | sed "s|-f $harbor_home/|\n - |g"
    else
        echo "$cmd"
    fi
}



# [v16.0] Orchestrator for `harbor up`, supporting hybrid runtimes, composition, and "best effort" startup.
# This is the most complex function in Harbor, responsible for bringing the system to a desired state.
#
# DESIGN: The function operates on the principle of "desired state composition". It calculates the
# full set of services that should be running (a union of what's requested now and what's
# already active) to ensure all dependencies can be resolved. It then uses an optimized "fast path"
# for the common container-only case, and a robust "phased orchestrator" for complex hybrid stacks.
# It explicitly does *not* exit on a container healthcheck failure, adhering to the "best effort"
# requirement, allowing the user to debug a failing container in a partially-up stack.
run_up() {
    local temp_native_env_file=""
    trap 'rm -f "$temp_native_env_file" 2>/dev/null' EXIT

    # 1. Argument Parsing
    local -a up_args=(); local -a services_to_run_args=()
    for arg in "$@"; do
        case "$arg" in --no-defaults|--open|-o|--tail|-t) up_args+=("$arg");; *) services_to_run_args+=("$arg");; esac
    done
    local requested_services=("${services_to_run_args[@]}")
    if [[ ${#requested_services[@]} -eq 0 && ! " ${up_args[*]} " =~ " --no-defaults " ]]; then
        requested_services=("${default_options[@]}")
    fi
    if [[ ${#requested_services[@]} -eq 0 ]]; then
        log_warn "No services specified to start."
        return 0
    fi

    # 2. Determine Final State for full context resolution.
    local already_running; read -r -a already_running <<< "$(get_active_services)"
    local full_context_services_str; full_context_services_str=$(printf '%s\n' "${already_running[@]}" "${requested_services[@]}" | sort -u)
    local -a full_context_services; readarray -t full_context_services < <(echo "$full_context_services_str")

    # 3. Planning Phase
    declare -A execution_plan
    __up_build_plan execution_plan "${full_context_services[@]}"

    # 4. Execution Phase
    local native_targets_str="${execution_plan[native_targets]}"
    if [[ -z "$native_targets_str" ]]; then
        # --- FAST PATH for Container-Only ---
        log_debug "All services are container-based. Using direct startup method."
        local compose_cmd; compose_cmd=$(compose_with_options "${up_args[@]}" "${full_context_services[@]}")
        # Run without `|| exit` for "best effort" startup.
        eval "$compose_cmd up -d --wait ${requested_services[*]}"
    else
        # --- HYBRID PATH for complex stacks ---
        log_debug "Hybrid stack detected. Using phased startup orchestration."
        __up_execute_phase1_foundations execution_plan
        # Determine which of the requested services need their native daemons started now.
        local -a all_native_targets; read -r -a all_native_targets <<< "$native_targets_str"
        local -a requested_native_targets=()
        for service in "${requested_services[@]}"; do
            if [[ " ${all_native_targets[*]} " =~ " ${service} " && ! " ${already_running[*]} " =~ " ${service} " ]]; then
                requested_native_targets+=("$service")
            fi
        done
        if [[ ${#requested_native_targets[@]} -gt 0 ]]; then
            __up_execute_phase2_native execution_plan "${requested_native_targets[@]}"
        fi
        __up_execute_phase3_main execution_plan "${up_args[@]}" "${requested_services[@]}"
    fi

    # 5. Post
    log_debug "Harbor startup command completed."
    local should_open=false; local should_tail=false
    for arg in "${up_args[@]}"; do case "$arg" in --open|-o) should_open=true;; --tail|-t) should_tail=true;; esac; done
    if [ "$default_autoopen" = "true" ] && [[ ${#services_to_run_args[@]} -eq 0 ]]; then run_open "$default_open"; fi
    for service in "${default_tunnels[@]}"; do establish_tunnel "$service"; fi
    if $should_tail; then run_logs "${services_to_run_args[@]}"; fi
    if $should_open; then run_open "${services_to_run_args[@]}"; fi
}

# [v12.0 Helper] Phase 0: Builds the execution plan for run_up.
__up_build_plan() {
    local -n plan_ref=$1 # Pass associative array by reference
    local -a services=("${@:2}")

    local -a native_targets=(); local -a container_targets=(); local -a foundational_containers=()
    for service in "${services[@]}"; do
        local context; context=$(_harbor_build_service_context "$service")
        eval "$context"
        if [[ "$PREFERENCE" == "NATIVE" ]]; then
            native_targets+=("$HANDLE")
            if [[ ${#NATIVE_DEPENDS_ON_CONTAINERS[@]} -gt 0 ]]; then
                foundational_containers+=("${NATIVE_DEPENDS_ON_CONTAINERS[@]}")
            fi
        else
            container_targets+=("$HANDLE")
        fi
    done

    plan_ref[native_targets]=$(echo "${native_targets[@]}")
    plan_ref[container_targets]=$(echo "${container_targets[@]}")
    plan_ref[foundational_containers]=$(echo "${foundational_containers[@]}" | tr ' ' '\n' | sort -u | tr '\n' ' ')
}

# [v12.0 Helper] Phase 1: Executes the foundational container startup.
__up_execute_phase1_foundations() {
    local -n plan_ref=$1
    local foundations="${plan_ref[foundational_containers]}"
    if [[ -n "$foundations" ]]; then
        log_info "Execute Phase 1: Starting foundational container dependencies: $foundations"
        local compose_cmd; compose_cmd=$(compose_with_options $foundations)
        eval "$compose_cmd up -d --wait" || { log_error "Failed to start foundational containers." }
        log_info "Execute Phase 1: Foundational containers are healthy."
    else
        log_debug "Execute Phase 1: No foundational containers to start."
    fi
}

# [v12.0 Helper] Phase 2: Executes the native service startup.
__up_execute_phase2_native() {
    local -n plan_ref=$1
    local natives="${plan_ref[native_targets]}"
    local env_file=""
    if [[ -n "$natives" ]]; then
        log_info "Execute Phase 2: Starting native services and preparing environment: $natives"
        env_file=$(__compose_generate_transient_env_file $natives)
        for service in $natives; do
            # Add explicit error handling for consistency with other phases.
            _harbor_start_native_service "$service" || { log_error "Failed to start native service '${service}'." }
        done
    else
        log_debug "Execute Phase 2: No native services to start."
    fi
    echo "$env_file" # Return path to env file for Phase 3
}

# [v12.1 Helper] Phase 3: Executes the main service startup.
__up_execute_phase3_main() {
    local -n plan_ref=$1
    local temp_native_env_file="$2"

    # All remaining arguments are the services to pass to `docker compose up`.
    # This includes original up_args and the list of services to actually start.
    local -a services_and_args=("${@:3}")

    # The targets for the compose file context are all services in the plan.
    local all_context_targets="${plan_ref[container_targets]} ${plan_ref[native_targets]}"

    # The targets for the `up` command are just the ones passed in.
    local phase3_up_targets_str="${services_and_args[*]}"

    if [[ -n "${phase3_up_targets_str// /}" ]]; then
        log_debug "Execute Phase 3: Bringing up main services: $phase3_up_targets_str"
        # Build compose command with the FULL context, but only run `up` on the specified targets.
        local compose_cmd; compose_cmd=$(compose_with_options $all_context_targets)
        if [[ -n "$temp_native_env_file" ]]; then
            compose_cmd+=" --env-file $temp_native_env_file"
        fi

        # The arguments passed to 'up' are now correctly isolated.
        eval "$compose_cmd up -d --wait ${services_and_args[*]}" || { log_error "Failed to start main services. Check docker logs."; }
        log_info "Execute Phase 3: Main services are running."
    else
        log_debug "Execute Phase 3: No new services to start in this operation."
    fi
}

# [v14.0 HELPER] Expands a list of service handles to include their sub-services.
# A sub-service is defined by the convention `<handle>-<suffix>`.
# This restores a key behavior from the original script in a modular way.
# @param {...string} A list of primary service handles.
# @return {string} A space-separated list of unique, expanded service handles.
_resolve_all_service_targets() {
    local -a initial_targets=("$@")
    local -a final_targets=()
    # Get a canonical list of ALL possible services, not just running ones, to search through.
    local all_services
    all_services=$(_harbor_get_all_possible_services)

    for target in "${initial_targets[@]}"; do
        final_targets+=("$target")
        # Find any service that starts with the target name followed by a hyphen.
        local sub_services
        sub_services=$(echo "$all_services" | grep "^${target}-" || true)
        if [[ -n "$sub_services" ]]; then
            # The result of grep can be multi-line, so we read it into the array.
            while read -r sub; do
                final_targets+=("$sub")
            done <<< "$sub_services"
        fi
    done

    # Return a unique, sorted list of services.
    echo "${final_targets[@]}" | tr ' ' '\n' | sort -u | tr '\n' ' '
}

# [v12.0, rev. v14.0] Orchestrator for `harbor down`, with sub-service regression fix.
run_down() {
    local services_to_stop_args=("$@")
    local dynamic_proxy_file="${harbor_home}/compose.harbor.native-proxy.yml"
    local merged_compose_file="$harbor_home/merged.compose.yml"
    trap 'rm -f "$dynamic_proxy_file" "$merged_compose_file" 2>/dev/null' EXIT

    if [[ ${#services_to_stop_args[@]} -eq 0 ]]; then
        # Global down: stop everything that is running.
        log_info "Stopping all running Harbor services..."
        local all_services; all_services=$(_harbor_get_all_possible_services)
        for service in $all_services; do
            if [[ "$(_harbor_get_running_service_runtime "$service")" == "NATIVE" ]]; then
                _harbor_stop_native_service "$service"
            fi
        done
        $(compose_with_options "*") down --remove-orphans
    else
        # Targeted down, now with sub-service resolution.
        log_info "Resolving service targets and their sub-services..."
        local -a all_targets_to_stop
        # Use the helper to expand the list of services to stop (e.g., 'ollama' becomes 'ollama' and 'ollama-init').
        read -r -a all_targets_to_stop <<< "$(_resolve_all_service_targets "${services_to_stop_args[@]}")"

        log_info "Stopping specified services: ${all_targets_to_stop[*]}"
        for service in "${all_targets_to_stop[@]}"; do
            # First, stop any native processes in the target list.
            if [[ "$(_harbor_get_running_service_runtime "$service")" == "NATIVE" ]]; then
                _harbor_stop_native_service "$service"
            fi
        done

        # Then, bring down all container components for the entire expanded list.
        # This correctly removes main services, sub-services, and any native proxies.
        $(compose_with_options "${all_targets_to_stop[@]}") down --remove-orphans "${all_targets_to_stop[@]}"
    fi
}

run_restart() {
    run_down "$@"
    run_up "$@"
}

run_ps() {
    $(compose_with_options "*") ps
}

# [v12.0] Builds the Docker images for specified services and their sub-services.
# This function is now hybrid-aware. It will intelligently skip building
# services configured for native execution while still building any of their
# container-based dependencies, providing clear feedback to the user.
run_build() {
    local primary_target="$1"
    shift
    local -a build_args=("$@") # Capture any extra docker compose build args

    if [ -z "$primary_target" ]; then
        log_error "Usage: harbor build <service> [docker-compose-build-options]"
        return 1
    fi

    log_info "Analyzing build targets for '${primary_target}'..."

    # 1. Discover all potential targets (primary + sub-services)
    local -a potential_targets=("$primary_target")
    local all_services; all_services=$(_harbor_get_all_possible_services)

    # Find sub-services (e.g., for 'ollama', find 'ollama-init')
    local sub_services; sub_services=$(echo "$all_services" | grep "^${primary_target}-")
    if [[ -n "$sub_services" ]]; then
        # Read sub-services into the array
        mapfile -t -O "${#potential_targets[@]}" potential_targets < <(echo "$sub_services")
        log_debug "Found sub-services to consider: ${sub_services}"
    fi

    # 2. Filter targets based on their execution preference
    local -a services_to_build=()
    for service in "${potential_targets[@]}"; do
        # We only need the preference, not the full context object here.
        local preference; preference=$(_harbor_get_configured_execution_preference "$service")

        if [[ "$preference" == "CONTAINER" ]]; then
            log_debug "Service '${service}' is a container, adding to build list."
            services_to_build+=("$service")
        else
            log_info "Skipping '${service}' as it is configured for NATIVE execution."
        fi
    done

    # 3. Execute the build if there are valid targets
    if [[ ${#services_to_build[@]} -gt 0 ]]; then
        log_info "Building container images for: ${services_to_build[*]}"
        # Note: We pass the full list of services to build to `compose_with_options`
        # so it can resolve any cross-dependencies needed for the build context.
        local compose_cmd; compose_cmd=$(compose_with_options "${services_to_build[@]}")

        eval "$compose_cmd build ${services_to_build[*]} ${build_args[*]}"
        log_info "Build process completed."
    else
        log_warn "No container services to build for target '${primary_target}'."
    fi
}


run_shell() {
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
    $(compose_with_options "*") logs -n 20 -f "$@"
}

run_pull() {
    $(compose_with_options "$@") pull
}

# [v12.0] Executes a one-off command via an alias or in a service's context.
# This command is a primary dispatcher that acts on the service's configured
# *preference* (NATIVE or CONTAINER), not its current running state. This allows
# a user to run toolchain commands (e.g., `harbor run ollama list`) without
# needing the service daemon to be active.
run_run() {
    local service_handle="$1"
    if [ -z "$service_handle" ]; then
        log_error "Usage: harbor run <alias|service_handle> [command...]"
        return 1
    fi
    shift

    # 1. Prioritize aliases for user-defined shortcuts.
    local alias_cmd; alias_cmd=$(env_manager_dict aliases --silent get "$service_handle")
    if [ -n "$alias_cmd" ]; then
        log_info "Running alias '${service_handle}' -> \"$alias_cmd $@\""
        # Pass remaining arguments to the alias command
        eval "$alias_cmd $@"
        return 0
    fi

    # 2. Determine the configured execution path for the service.
    local preference; preference=$(_harbor_get_configured_execution_preference "$service_handle")
    log_debug "Dispatching 'run' for '${service_handle}' with preference: ${preference}"

    # 3. Dispatch to the appropriate runtime.
    if [[ "$preference" == "NATIVE" ]]; then
        # For native, we dispatch to the pre-compiled executable on the host.
        log_info "Executing via native toolchain for '${service_handle}'..."
        # _dispatch_native_executable handles finding the executable and its env.
        _dispatch_native_executable "$service_handle" "$@"
    else
        # For containers, we use `docker compose run` to create a new,
        # temporary container with the correct network and volume mounts.
        log_info "Executing via container for '${service_handle}'..."

        # Include all currently active services in the compose context
        # so this one-off container can communicate with them.
        local active_services; active_services=$(get_active_services)
        local compose_cmd; compose_cmd=$(compose_with_options $active_services "$service_handle")

        # --rm ensures the container is cleaned up after the command exits.
        eval "$compose_cmd run --rm "$service_handle" "$@""
    fi
}

run_stats() {
    $(compose_with_options "*") stats
}

run_hf_open() {
    local search_term="${*// /+}"
    local hf_url="https://huggingface.co/models?sort=trending&search=${search_term}"

    sys_open "$hf_url"
}

link_cli() {
    local target_dir=$(eval echo "$(env_manager get cli.path)")
    local script_name=$(env_manager get cli.name)
    local short_name=$(env_manager get cli.short)
    local script_path="$harbor_home/harbor.sh"
    local create_short_link=false

    # Check for "--short" flag
    for arg in "$@"; do
        if [[ "$arg" == "--short" ]]; then
            create_short_link=true
            break
        fi
    done

    # Determine which shell configuration file to update
    local shell_profile=""
    if [[ -f "$HOME/.zshrc" ]]; then
        shell_profile="$HOME/.zshrc"
    elif [[ -f "$HOME/.bash_profile" ]]; then
        shell_profile="$HOME/.bash_profile"
    elif [[ -f "$HOME/.bashrc" ]]; then
        shell_profile="$HOME/.bashrc"
    elif [[ -f "$HOME/.profile" ]]; then
        shell_profile="$HOME/.profile"
    else
        if [[ "$OSTYPE" == "darwin"* ]]; then
            shell_profile="$HOME/.zshrc"
        elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
            shell_profile="$HOME/.bashrc"
        else
            # We can't determine the shell profile
            log_warn "Sorry, but Harbor can't determine which shell configuration file to update."
            log_warn "Please link the CLI manually."
            log_warn "Harbor supports: ~/.zshrc, ~/.bash_profile, ~/.bashrc, ~/.profile"
            return 1
        fi
    fi

    # Check if target directory exists in PATH
    if ! echo "$PATH" | tr ':' '\n' | grep -q "$target_dir"; then
        log_info "Creating $target_dir and adding it to PATH..."
        mkdir -p "$target_dir"

        # Update the shell configuration file
        echo -e "\nexport PATH=\"\$PATH:$target_dir\"\n" >>"$shell_profile"
        export PATH="$PATH:$target_dir"
        echo "Updated $shell_profile with new PATH."
    fi

    # Create symlink
    if ln -s "$script_path" "$target_dir/$script_name"; then
        log_info "Symlink created: $target_dir/$script_name -> $script_path"
    else
        log_warn "Failed to create symlink. Please check permissions and try again."
        return 1
    fi

    # Create short symlink if "--short" flag is present
    if $create_short_link; then
        if ln -s "$script_path" "$target_dir/$short_name"; then
            log_info "Short symlink created: $target_dir/$short_name -> $script_path"
        else
            log_warn "Failed to create short symlink. Please check permissions and try again."
            return 1
        fi
    fi

    log_info "You may need to reload your shell or run 'source $shell_profile' for changes to take effect."
}

unlink_cli() {
    local target_dir=$(eval echo "$(env_manager get cli.path)")
    local script_name=$(env_manager get cli.name)
    local short_name=$(env_manager get cli.short)

    log_info "Removing symlinks..."

    # Remove the main symlink
    if [ -L "$target_dir/$script_name" ]; then
        rm "$target_dir/$script_name"
        log_info "Removed symlink: $target_dir/$script_name"
    else
        log_info "Main symlink does not exist or is not a symbolic link."
    fi

    # Remove the short symlink
    if [ -L "$target_dir/$short_name" ]; then
        rm "$target_dir/$short_name"
        log_info "Removed short symlink: $target_dir/$short_name"
    else
        log_info "Short symlink does not exist or is not a symbolic link."
    fi
}

get_container_name() {
    local service_name="$1"
    local container_name="$default_container_prefix.$service_name"
    echo "$container_name"
}

# [v12.0] Gets the primary host port for a running service.
# It correctly queries the native contract or the Docker daemon.
get_service_port() {
    local service_handle="$1"
    if [ -z "$service_handle" ]; then return 1; fi

    local runtime; runtime=$(_harbor_get_running_service_runtime "$service_handle")
    case "$runtime" in
        NATIVE)
            local context; context=$(_harbor_build_service_context "$service_handle")
            eval "$context"
            echo "$NATIVE_PORT"
            ;;
        CONTAINER)
            # This logic is preserved from the original for compatibility.
            docker port "$(get_container_name "$service_handle")" 2>/dev/null | perl -nle 'print m{0.0.0.0:\K\d+}g' | head -n 1
            ;;
        *)
            log_error "Service '${service_handle}' is not running or has no mapped port." >&2
            return 1
            ;;
    esac
}

# [v12.0] Gets the internal URL for a service, as seen from another container.
# This is critical for service-to-service communication.
get_intra_url() {
    local service_handle="$1"
    if [ -z "$service_handle" ]; then return 1; fi

    local runtime; runtime=$(_harbor_get_running_service_runtime "$service_handle")
    case "$runtime" in
        NATIVE)
            # From a container's perspective, the "internal" URL for a native
            # service is via the special host.docker.internal DNS name.
            local port; port=$(get_service_port "$service_handle")
            if [[ -n "$port" ]]; then
                echo "http://host.docker.internal:$port"
            else
                return 1
            fi
            ;;
        CONTAINER)
            # For a container, we need to find its internal, un-mapped port.
            # The most reliable way is to inspect the container's network settings.
            local container_id; container_id=$(docker compose ps -q "$service_handle")
            if [[ -z "$container_id" ]]; then return 1; fi

            # This robustly finds the first exposed TCP port. Requires jq.
            if command -v jq &>/dev/null; then
                local internal_port; internal_port=$(docker inspect "$container_id" | jq -r '.[0].NetworkSettings.Ports | keys[0] | split("/")[0]')
                if [[ -n "$internal_port" && "$internal_port" != "null" ]]; then
                    echo "http://${service_handle}:${internal_port}"
                else
                    log_error "Could not determine internal port for container '${service_handle}'." >&2
                    return 1
                fi
            else
                log_warn "jq command not found. Cannot reliably determine internal port. Please install jq." >&2
                return 1
            fi
            ;;
        *)
            log_error "Service '${service_handle}' is not running." >&2
            return 1
            ;;
    esac
}

# [v12.0] The remaining URL helpers use the above refactored functions and
# do not need to be changed themselves. They are included for completeness.

# Gets the localhost URL for a service.
get_service_url() {
    local port; port=$(get_service_port "$1")
    if [[ -n "$port" ]]; then echo "http://localhost:$port"; else return 1; fi
}

# Gets the LAN-accessible URL for a service.
get_adressable_url() {
    local port; port=$(get_service_port "$1")
    local ip_address; ip_address=$(get_ip)
    if [[ -n "$port" ]] && [[ -n "$ip_address" ]]; then
        echo "http://$ip_address:$port"
    else
        log_error "Could not determine LAN URL for '$1'." >&2
        return 1
    fi
}

# [v12.0] The main URL dispatcher. Its logic remains unchanged as it correctly
# delegates to the now hybrid-aware helper functions.
get_url() {
    local is_local=true; local is_adressable=false; local is_intra=false;
    local -a filtered_args=()
    for arg in "$@"; do
        case "$arg" in
        --intra | -i | --internal) is_local=false; is_adressable=false; is_intra=true ;;
        --addressable | -a | --lan) is_local=false; is_intra=false; is_adressable=true ;;
        *) filtered_args+=("$arg") ;;
        esac
    done

    if [[ ${#filtered_args[@]} -eq 0 ]] || [[ -z "${filtered_args[0]}" ]]; then
        filtered_args=("$default_open")
    fi

    if $is_local; then
        get_service_url "${filtered_args[@]}"
    elif $is_adressable; then
        get_adressable_url "${filtered_args[@]}"
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

    # Open the URL in the default browser
    if command -v xdg-open &>/dev/null; then
        xdg-open "$url" # Linux
    elif command -v open &>/dev/null; then
        open "$url" # macOS
    elif command -v start &>/dev/null; then
        start "$url" # Windows
    else
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
        sys_open "$service_url"
        log_info "Opened $service_url in your default browser."
        return 0
    else
        log_error "Failed to get service URL for '$1'"
        return 1
    fi
}

smi() {
    if command -v nvidia-smi &>/dev/null; then
        nvidia-smi
    else
        log_error "nvidia-smi not found."
    fi
}

nvidia_top() {
    if command -v nvtop &>/dev/null; then
        nvtop
    else
        log_error "nvtop not found."
    fi
}

eject() {
    $(compose_with_options "$@") config
}

run_exec() {
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
        echo "Error: No valid service name provided."
        return 1
    fi

    # Native support: if service is native-eligible, run directly on host
    if ! "${_SKIP_NATIVE}" && type _harbor_is_native_eligible &>/dev/null && _harbor_is_native_eligible "$service_name"; then
        log_info "Service '${service_name}' is running natively. Executing command directly on host: ${after_args[*]}"

        # Actually execute the command on the host
        "${after_args[@]}"
        return $?
    fi

    # Check if the service is running (container)
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
        echo "Creating .env file..."
        cp "$src_file" "$tgt_file"
    fi
}

reset_env_file() {
    log_warn "Resetting Harbor configuration..."
    rm .env
    ensure_env_file
}

merge_env_files() {
    local default_file=$default_profile
    local target_file=".env"

    # Check if both files exist
    if [[ ! -f "$target_file" ]]; then
        cp "$default_file" "$target_file"
        echo "Copied $default_file to $target_file"
        return
    fi

    # Create a temporary file
    local temp_file=$(mktemp)

    # Variable to track empty lines
    local empty_lines=0
    # Variable to track repeated lines
    local prev_line=""
    local repeat_count=0

    # Read .env line by line and merge with .env
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Handle empty lines
        if [[ -z "$line" ]]; then
            ((empty_lines++))
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
            ((repeat_count++))
            if ((repeat_count <= 1)); then
                echo "$line" >>"$temp_file"
            fi
        else
            repeat_count=0
            if [[ "$line" =~ ^[[:alnum:]_]+=.* ]]; then
                var_name="${line%%=*}"
                if grep -q "^$var_name=" "$target_file"; then
                    # If the variable exists in .env, use that value
                    grep "^$var_name=" "$target_file" >>"$temp_file"
                else
                    # If the variable doesn't exist in .env, add the new line
                    echo "$line" >>"$temp_file"
                fi
            else
                # For comments or other content, add the new line as is
                echo "$line" >>"$temp_file"
            fi
        fi
        prev_line="$line"
    done <"$default_file"

    # Remove trailing newlines from the temp file
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$temp_file"
    else
        sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$temp_file"
    fi

    # Move the temporary file to replace the target file
    mv "$temp_file" "$target_file"

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
                        ;;
                    1)
                        log_error "General error occurred"
                        ;;
                    2)
                        log_error "Misuse of shell builtin"
                        ;;
                    126)
                        log_error "Command invoked cannot execute (permission problem or not executable)"
                        ;;
                    127)
                        log_error "Command not found"
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
                        return 1
                        ;;
                    esac
                fi
            else
                # Less than two arguments, retry is impossible
                return 1
            fi
        fi
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
    local var_name="default_log_labels_$level"
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
log_debug() { log "DEBUG" "${c_gray}$@${c_nc}"; }
log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }

# --- Internal Helper Functions: Argument Parsing and Dependency Checks ---
# _check_dependencies: Ensures all required external CLI tools are available.
_check_dependencies() {
    _info "Checking script dependencies..."
    local missing_deps=()

    for cmd in docker "docker compose" nc curl pgrep; do
        if ! command -v "${cmd%% *}" &> /dev/null; then
            missing_deps+=("${cmd}")
        fi
    done

    # Check for Deno explicitly, as it's now used for YAML parsing.
    if ! command -v deno &> /dev/null; then
        missing_deps+=("deno (required for native service config parsing)")
    fi

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        _error "Missing required commands: ${missing_deps[*]}. Please install them."
    fi
    _info "All required CLI dependencies found."
}

# _run_bash_template <template_string> <port_value>
# Simple Bash-based templating function. Replaces `{{.native_port}}` with actual port value.
_run_bash_template() {
    local template="$1"
    local port="$2"
    echo "$template" | sed "s|{{.native_port}}|$port|g"
}


# --- Internal Helper Functions: Lock Management ---
_acquire_lock() {
    _info "Attempting to acquire lock: ${LOCK_FILE}"
    if ( set -o noclobber; echo "$$" > "${LOCK_FILE}") 2>/dev/null; then
        _info "Lock acquired. PID: $$"
    else
        local lock_pid=$(cat "${LOCK_FILE}" 2>/dev/null || true)
        if [[ -n "${lock_pid}" ]] && kill -0 "${lock_pid}" 2>/dev/null; then
            _error "Another instance of Harbor CLI is already running with PID ${lock_pid}. Exiting to prevent conflicts."
        else
            _warn "Stale lock file found (previous PID ${lock_pid} is gone or invalid)."
            if "${_FORCE_CLEANUP}"; then
                _info "Force cleanup requested. Removing stale lock file: ${LOCK_FILE}."
                rm -f "${LOCK_FILE}" || _error "Failed to remove stale lock file: ${LOCK_FILE}. Please check permissions."
                if ( set -o noclobber; echo "$$" > "${LOCK_FILE}") 2>/dev/null; then
                    _info "Lock re-acquired after force cleanup. PID: $$"
                else
                    _error "Failed to acquire lock even after attempting to remove stale lock. Check permissions for ${LOCK_FILE}."
                fi
            fi
        fi
    fi
}

_release_lock() {
    _debug "Releasing lock: ${LOCK_FILE}"
    if [[ -f "${LOCK_FILE}" ]]; then
        if [[ "$(cat "${LOCK_FILE}")" == "$$" ]]; then
            rm -f "${LOCK_FILE}" || _warn "Failed to remove lock file: ${LOCK_FILE}. Manual cleanup might be required."
        else
            _warn "Lock file owned by a different PID. Not removing."
        fi
    fi
}

# --- Main `cleanup` function, executed on script exit or signal. ---
cleanup() {
    local exit_status=$?
    # Only log detailed cleanup info if not a normal exit (status 0) or if logging level is DEBUG
    if [[ "$exit_status" -ne 0 ]] || [[ "$_LOG_LEVEL" == "DEBUG" ]] || [[ "$default_log_level" == "DEBUG" ]]; then # Check both global and .env log level
        _debug "Harbor CLI exiting (status: ${exit_status}). Running cleanup."
    fi

    # The primary role of cleanup on EXIT/Signal for the CLI is to release its own lock.
    # It should NOT stop services; that's an explicit user action (e.g., `harbor down`).
    _release_lock

    if [[ "$exit_status" -ne 0 ]]; then
        _debug "Exited with status ${exit_status}."
    fi
    # The script will exit with the original exit_status due to `set -e` or explicit exit elsewhere.
    # If trap is EXIT, it will exit with $exit_status.
    # If trap is a signal, shell usually exits with 128 + signal number.
    # No explicit `exit` command here, to allow the trap to respect the original exit cause.
}

# --- Set traps to call `cleanup` on various exit conditions or signals. ---
# trap cleanup EXIT
trap cleanup SIGINT
trap cleanup SIGTERM
trap cleanup SIGHUP


# --- Internal Native Service Management Functions ---
_is_harbor_native_running_check() {
    local command_pattern="$1"
    pgrep -f "${command_pattern}" >/dev/null 2>&1
}

_harbor_wait_for_port() {
    local host="$1"; local port="$2"; local timeout_sec="$3"; local interval_sec="$4"; local waited_time=0
    _info "Waiting for ${host}:${port}..."
    while ! nc -z "${host}" "${port}" &>/dev/null; do
        if (( waited_time >= timeout_sec )); then _error "Timeout: ${host}:${port} did not become available after ${timeout_sec}s."; return 1; fi
        _debug "Port ${port} not open, sleeping ${interval_sec}s..."; sleep "${interval_sec}"; waited_time=$((waited_time + interval_sec))
    done; _info "${host}:${port} is open."; return 0
}

_harbor_wait_for_http_health() {
    local url="$1"; local timeout_sec="$2"; local interval_sec="$3"; local waited_time=0
    _info "Waiting for HTTP health check at ${url}..."
    while ! curl --fail --silent "${url}" &>/dev/null; do
        if (( waited_time >= timeout_sec )); then _error "Timeout: HTTP health check for ${url} did not pass after ${timeout_sec}s."; return 1; fi
        _debug "Health check failed for ${url}, sleeping ${interval_sec}s..."; sleep "${interval_sec}"; waited_time=$((waited_time + interval_sec))
    done; _info "HTTP health check passed for ${url}."; return 0
}

# [v13.0] Starts a native service daemon process on the host.
# This function is a non-blocking "launcher". It gets all necessary context,
# prepares the environment, and starts the background process. It does not wait
# for the service to become healthy; that is the responsibility of the caller.
_harbor_start_native_service() {
    local service_handle="$1"

    # 1. Build the full context for this service to get all resolved configuration.
    local context; context=$(_harbor_build_service_context "$service_handle")
    eval "$context"

    # 2. Prerequisite checks.
    if [[ "$IS_ELIGIBLE" != "true" || -z "$NATIVE_DAEMON_COMMAND" ]]; then
        log_warn "Cannot start native service '${HANDLE}': it is not native-eligible or is missing 'native_daemon_command' in its contract."
        return 1
    fi
    local native_script="$harbor_home/$HANDLE/${HANDLE}_native.sh"
    if [[ ! -f "$native_script" || ! -x "$native_script" ]]; then
        log_error "Native bootstrap script for '${HANDLE}' not found or not executable at '${native_script}'."
        return 1
    fi

    # 3. Idempotency check: Do not start if already running.
    if pgrep -f "$NATIVE_DAEMON_COMMAND" >/dev/null; then
        log_info "Native daemon for '${HANDLE}' is already running."
        return 0
    fi

    # 4. Prepare environment variables to be exported for the native process.
    local env_exports=""
    if [[ ${#NATIVE_ENV_VARS_LIST[@]} -gt 0 ]]; then
        for var_name in "${NATIVE_ENV_VARS_LIST[@]}"; do
            local value; value=$(env_manager --silent get "$var_name")
            if [[ -n "$value" ]]; then
                # The export statement will be part of the command executed by nohup's subshell.
                env_exports+="export ${var_name}='${value}'; "
            fi
        done
    fi

    # 5. Execute the launch command.
    log_info "Starting native service '${HANDLE}' in the background..."
    local log_file="${LOG_DIR}/harbor-${HANDLE}-native.log"
    # Use nohup and a subshell to correctly daemonize the process with its environment.
    # `exec` replaces the final shell process with the actual application binary.
    nohup bash -c "${env_exports} exec bash \"${native_script}\"" > "$log_file" 2>&1 &

    # 6. Brief pause and quick verification that the process launched.
    sleep 2
    if ! pgrep -f "$NATIVE_DAEMON_COMMAND" >/dev/null; then
        log_error "Failed to launch native daemon for '${HANDLE}'. Check logs for details: ${log_file}"
        return 1
    else
        log_debug "Native service '${HANDLE}' process has been launched. Logs at ${log_file}"
    fi
    return 0
}

# [v13.0] Stops a native service daemon process on the host.
# This function is a self-contained "killer". It gets all necessary context,
# verifies the process to avoid killing unintended PIDs, and uses a
# robust TERM/wait/KILL shutdown sequence. It does not mutate configuration.
_harbor_stop_native_service() {
    local service_handle="$1"

    # 1. Build context to get the unique daemon command string.
    local context; context=$(_harbor_build_service_context "$service_handle")
    eval "$context"

    if [[ -z "$NATIVE_DAEMON_COMMAND" ]]; then
        log_warn "Cannot stop native service '${HANDLE}': no 'native_daemon_command' defined in its contract."
        return 1
    fi

    # 2. Find all PIDs matching the daemon command pattern.
    local pids_found; pids_found=$(pgrep -f "$NATIVE_DAEMON_COMMAND")
    if [[ -z "$pids_found" ]]; then
        log_info "No running native process found for '${HANDLE}'."
        return 0
    fi

    log_info "Attempting to stop native service '${HANDLE}' (PIDs: ${pids_found})..."

    # 3. Use pkill to send SIGTERM to all matching processes.
    pkill -f "$NATIVE_DAEMON_COMMAND"

    # 4. Wait for graceful shutdown.
    local countdown=10
    log_info "Waiting up to ${countdown}s for graceful termination..."
    while ((countdown > 0)); do
        # Re-check if any process still exists.
        if ! pgrep -f "$NATIVE_DAEMON_COMMAND" >/dev/null; then
            log_info "Native service '${HANDLE}' terminated gracefully."
            return 0
        fi
        sleep 1
        ((countdown--))
    done

    # 5. If still running, escalate to SIGKILL.
    log_warn "Service '${HANDLE}' did not terminate gracefully. Sending SIGKILL."
    pkill -9 -f "$NATIVE_DAEMON_COMMAND" || log_warn "Failed to send SIGKILL to '${HANDLE}'. Manual cleanup may be required."

    return 0
}

# [v13.0] Checks if a service is eligible for native execution.
# Eligibility is defined strictly by the existence of a native contract file
# (`<handle>_native.yml`). This is the single source of truth for whether
# a service can be considered part of the hybrid runtime system.
_harbor_is_native_eligible() {
    # This replaces the legacy checks and the `has_native_config` helper
    # with a single, clear definition of eligibility.
    [[ -f "$harbor_home/$1/${1}_native.yml" ]]
}

# shellcheck disable=SC2034
__anchor_envm=true

env_manager() {
    local env_file=".env"
    local prefix="HARBOR_"
    local silent=false

    # Parse options
    while [[ "$1" == --* ]]; do
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
            $silent || echo "Unknown option: $1"
            return 1
            ;;
        esac
    done

    case "$1" in
    get)
        if [[ -z "$2" ]]; then
            $silent || log_info "Usage: env_manager get <key>"
            return 1
        fi
        local upper_key=$(echo "$2" | tr '[:lower:]' '[:upper:]' | tr '.' '_')
        value=$(grep "^$prefix$upper_key=" "$env_file" | cut -d '=' -f2-)
        value="${value#\"}" # Remove leading quote if present
        value="${value%\"}" # Remove trailing quote if present
        echo "$value"
        ;;
    set)
        if [[ -z "$2" ]]; then
            $silent || log_info "Usage: env_manager set <key> <value>"
            return 1
        fi
        local upper_key=$(echo "$2" | tr '[:lower:]' '[:upper:]' | tr '.' '_')
        shift 2          # Remove 'set' and the key from the arguments
        local value="$*" # Capture all remaining arguments as the value
        if grep -q "^$prefix$upper_key=" "$env_file"; then
            if [[ "$(uname)" == "Darwin" ]]; then
                sed -i '' "s|^$prefix$upper_key=.*|$prefix$upper_key=\"$value\"|" "$env_file"
            else
                sed -i "s|^$prefix$upper_key=.*|$prefix$upper_key=\"$value\"|" "$env_file"
            fi
        else
            echo "$prefix$upper_key=\"$value\"" >>"$env_file"
        fi
        $silent || log_info "Set $prefix$upper_key to: \"$value\""
        ;;
    list | ls)
        grep "^$prefix" "$env_file" | sed "s/^$prefix//" | while read -r line; do
            key=${line%%=*}
            value=${line#*=}
            value=$(echo "$value" | sed -E 's/^"(.*)"$/\1/') # Remove surrounding quotes for display
            printf "%-30s %s\n" "$key" "$value"
        done
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
    --help | -h)
        echo "Harbor configuration management"
        echo
        echo "Usage: harbor config [--silent] [--env-file <file>] [--prefix <prefix>] {get|set|ls|list|reset|update} [key] [value]"
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
        echo " reset           Reset Harbor configuration to default .env"
        echo " update          Merge upstream config changes from default .env"
        return 0
        ;;
    *)
        $silent || echo "Usage: harbor config [--silent] [--env-file <file>] [--prefix <prefix>] {get|set|ls|reset} [key] [value]"
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
    local temp_file="$(mktemp)"

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
    --help | -h)
        echo "Harbor profile management"
        echo "Usage: $0 profile"
        echo
        echo "Commands:"
        echo "  save|add <profile_name>      - Save the current configuration as a profile"
        echo "  set|use|load <profile_name>  - Set current profile"
        echo "  remove|rm <profile_name> - Remove a profile"
        echo "  list|ls                  - List all profiles"
        return 0
        ;;
    *)
        echo "Usage: $0 profile {save|set|load|remove|list} [profile_name]"
        return $scramble_exit_code
        ;;
    esac
}

harbor_profile_save() {
    local profile_name=$1
    local profile_file="$profiles_dir/$profile_name.env"

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    if [ -f "$profile_file" ]; then
        if ! run_gum confirm "Profile '$profile_name' already exists. Overwrite?"; then
            echo "Save cancelled."
            return 1
        fi
    fi

    cp .env "$profile_file"
    log_info "Profile '$profile_name' saved."
}

harbor_profile_list() {
    echo "Available profiles:"
    for profile in "$profiles_dir"/*.env; do
        basename "$profile" .env
    done
}

harbor_profile_set() {
    local profile_name=$1
    local profile_file="$profiles_dir/$profile_name.env"

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    if [ ! -f "$profile_file" ]; then
        log_error "Profile '$profile_name' not found."
        return 1
    fi

    cp "$profile_file" .env
    log_info "Profile '$profile_name' loaded."
}

harbor_profile_remove() {
    local profile_name=$1
    local profile_file="$profiles_dir/$profile_name.env"

    if [ -z "$profile_name" ]; then
        log_error "Please provide a profile name."
        return 1
    fi

    if [ "$profile_name" == "default" ]; then
        log_error "Cannot remove the default profile."
        return 1
    fi

    if [ ! -f "$profile_file" ]; then
        log_error "Profile '$profile_name' not found."
        return 1
    fi

    run_gum confirm "Are you sure you want to remove profile '$profile_name'?" || return 1

    rm "$profile_file"
    log_info "Profile '$profile_name' removed."
}

# shellcheck disable=SC2034
__anchor_utils=true

run_harbor_find() {
    find $(eval echo "$(env_manager get hf.cache)") \
        $(eval echo "$(env_manager get llamacpp.cache)") \
        $(eval echo "$(env_manager get ollama.cache)") \
        $(eval echo "$(env_manager get vllm.cache)") \
        $(eval echo "$(env_manager get comfyui.workspace)") \
        -xtype f -wholename "*$**"
}

run_hf_docker_cli() {
    $(compose_with_options "hf") run --rm hf "$@"
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
    local folder=$1
    log_debug "fsacl: $folder"

    # 1000, 1001, 1002 - most frequent default users on Debian
    # 100 - most frequent default on Alpine
    # 911 - "abc" user from LinuxServer.io images
    # 101 - clickhouse
    # 1032 - libretranslate
    sudo setfacl --recursive -m user:1000:rwx $folder &&
        sudo setfacl --recursive -m user:1002:rwx $folder &&
        sudo setfacl --recursive -m user:1001:rwx $folder &&
        sudo setfacl --recursive -m user:100:rwx $folder &&
        sudo setfacl --recursive -m user:911:rwx $folder &&
        sudo setfacl --recursive -m user:101:rwx $folder &&
        sudo setfacl --recursive -m user:1032:rwx $folder
}

run_fixfs() {
    docker_fsacl .

    docker_fsacl $(eval echo "$(env_manager get hf.cache)")
    docker_fsacl $(eval echo "$(env_manager get vllm.cache)")
    docker_fsacl $(eval echo "$(env_manager get llamacpp.cache)")
    docker_fsacl $(eval echo "$(env_manager get ollama.cache)")
    docker_fsacl $(eval echo "$(env_manager get parllama.cache)")
    docker_fsacl $(eval echo "$(env_manager get opint.config.path)")
    docker_fsacl $(eval echo "$(env_manager get fabric.config.path)")
    docker_fsacl $(eval echo "$(env_manager get txtai.cache)")
    docker_fsacl $(eval echo "$(env_manager get nexa.cache)")
    docker_fsacl $(eval echo "$(env_manager get aichat.config_path)")
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
    git fetch origin main:main --depth 1
    git checkout main
    git pull
}

resolve_harbor_version() {
    curl -s "$harbor_release_url" | sed -n 's/.*"tag_name": "\(.*\)".*/\1/p'
}

update_harbor() {
    local is_latest=false

    case "$1" in
    --latest | -l)
        is_latest=true
        ;;
    esac

    if $is_latest; then
        log_info "Updating to the latest dev version..."
        unsafe_update
    else
        harbor_version=$(resolve_harbor_version)
        log_info "Updating to version $harbor_version..."
        git fetch --all --tags
        git checkout tags/$harbor_version
    fi

    log_info "Merging .env files..."
    merge_env_files

    log_info "Harbor updated successfully."
}

# [v12.0] Returns a space-separated list of all currently active services,
# regardless of their runtime (native or container). This is the canonical
# function for discovering the live state of the entire Harbor system.
get_active_services() {
    local -a active_services_list=()
    # Use the canonical helper to get every service Harbor knows about.
    local all_services; all_services=$(_harbor_get_all_possible_services)

    for service in $all_services; do
        # Query the live runtime state for each service.
        if [[ -n "$(_harbor_get_running_service_runtime "$service")" ]]; then
            active_services_list+=("$service")
        fi
    done

    echo "${active_services_list[@]}"
}

is_service_running() {
    [[ -n "$(_harbor_get_running_service_runtime "$1")" ]]
}

# [v12.0] Lists available or active Harbor services.
# This function is now a user-facing wrapper around the new canonical
# service discovery helpers, providing a unified view of both native
# and container services.
get_services() {
    local is_active=false
    local is_silent=false

    for arg in "$@"; do
        case "$arg" in
        --silent | -s) is_silent=true;;
        --active | -a) is_active=true;;
        esac
    done

    if $is_active; then
        local active_list; active_list=$(get_active_services)
        if [ -z "$active_list" ]; then
            $is_silent || log_warn "Harbor has no active services."
        else
            $is_silent || log_info "Harbor active services (native and container):"
            echo "$active_list" | tr ' ' '\n'
        fi
    else
        $is_silent || log_info "All available Harbor services (native and container):"
        # This now uses the canonical helper for all possible services.
        _harbor_get_all_possible_services
    fi
}

get_ip() {
    # Try ip command first
    ip_cmd=$(which ip 2>/dev/null)
    if [ -n "$ip_cmd" ]; then
        ip route get 1 | awk '{print $7; exit}'
        return
    fi

    # Fallback to ifconfig
    ifconfig_cmd=$(which ifconfig 2>/dev/null)
    if [ -n "$ifconfig_cmd" ]; then
        ifconfig | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -n1
        return
    fi

    # Last resort: hostname
    hostname -I | awk '{print $1}'
}

extract_tunnel_url() {
    grep -oP '(?<=\|  )https://[^[:space:]]+\.trycloudflare\.com(?=\s+\|)' | head -n1
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

        # If we've exceeded max entries, remove oldest entries
        if [ "$(wc -l <"$file")" -gt "$max_entries" ]; then
            tail -n "$max_entries" "$file" >"$file.tmp" && mv "$file.tmp" "$file"
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
        local tmp_dir=$(mktemp -d)
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
    # Get the cache directories
    cache_dirs=$(harbor config ls | grep CACHE | awk '{print $NF}' | sed "s|~|$HOME|g")
    # Add workspace dirs to the list
    cache_dirs+=$'\n'"$(harbor config ls | grep WORKSPACE | awk '{print $NF}' | sed "s|~|$HOME|g")"
    # Add $(harbor home) to the list
    cache_dirs+=$'\n'"$(harbor home)"

    # Print header
    echo "Harbor size:"
    echo "----------------------"

    # Iterate through each directory and print its size
    while IFS= read -r dir; do
        if [ -d "$dir" ]; then
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            echo "$dir: $size"
        else
            echo "$dir: Directory not found"
        fi
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
    local env_var=$1
    local env_val=$2
    local mgr_cmd="ls"

    if [ -n "$env_var" ]; then
        if [ -n "$env_val" ]; then
            mgr_cmd="set"
        else
            mgr_cmd="get"
        fi
    fi

    local env_file="$service/override.env"

    log_debug "'env' $env_file - $mgr_cmd $env_var $env_val"

    if [ ! -f "$env_file" ]; then
        log_error "Unknown service: $service. Please provide a valid service name."
        return 1
    fi

    env_manager --env-file "$env_file" --prefix "" "$mgr_cmd" "$env_var" "$env_val"
}

# Corresponds to the ".scripts" folder
run_harbor_dev() {
    local filtered_args=()

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
    local use_container=false

    if $use_container; then
        log_debug "running in container: $script"
        docker run --rm \
            -v "$harbor_home:$harbor_home" \
            -v harbor-deno-cache:/deno-dir:rw \
            -w "$harbor_home" \
            denoland/deno:distroless \
            run -A --unstable-sloppy-imports \
            "./.scripts/$script.ts" $script_args[@]
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
        ;;
    *)
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
    attention)
        shift
        env_manager_alias vllm.attention_backend "$@"
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
        echo "  harbor vllm attention [backend] - Get or set the attention backend to use"
        echo "  harbor vllm version [version]   - Get or set VLLM version (docker tag)"
        ;;
    *)
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
        ;;
    esac
}

run_parllama_command() {
    $(compose_with_options "parllama") run --rm -it --entrypoint bash parllama -c parllama
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
        $(compose_with_options "$services" "opint") run -v "$original_dir:$original_dir" --workdir "$original_dir" opint $@
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

run_harbor_cmdh_command() {
    # Check if ollama is running
    if ! is_service_running "ollama"; then
        log_error "Please start ollama service to use 'harbor how'"
        exit 1
    fi

    local services=$(get_active_services)
    local cmdh_model=$(env_manager get cmdh.model)
    local ollama_has_model=$(harbor ollama ls | grep -q "$cmdh_model" && echo "true" || echo "false")

    log_debug "services: $services"
    log_debug "cmdh_model: $cmdh_model"
    log_debug "ollama_has_model: $ollama_has_model"

    if [ "$ollama_has_model" == "false" ]; then
        log_error "Please pull cmdh model to use 'harbor how': harbor ollama pull \$(harbor cmdh model)"
        exit 1
    fi

    # Mount the current directory and set it as the working directory
    $(compose_with_options $services "cmdh" "harbor") run \
        --rm \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --name $default_container_prefix.harbor-how \
        --workdir "$original_dir" \
        cmdh "$*"
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
        echo "Fabric CLI Help:"
        ;;
    esac

    local services=$(get_active_services)

    # Fabric has some funky TTY handling
    # Container hangs for specific flags
    # We have to explicitly remove -T for them to run
    local tty_flag="-T"
    local skip_tty=("-l" "--listpatterns" "-L" "--listmodels" "-x" "--listcontexts" "-X" "--listsessions" "--setup")

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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
        ;;
    esac
}

run_comfyui_workspace_command() {
    case "$1" in
    open)
        shift
        sys_open "$harbor_home/comfyui/workspace"
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
        return $scramble_exit_code
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
        sys_open "$harbor_home/comfyui/workspace/ComfyUI/output"
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
        return $scramble_exit_code
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

# [v12.0] Provides a dedicated CLI for the Ollama service.
# This function is a clean dispatcher that respects the user's configured
# execution preference (native or container) for the 'ollama' toolchain.
run_ollama_command() {
    # This helper function is specific to the 'ctx' subcommand.
    update_ollama_env() {
        harbor env ollama OLLAMA_CONTEXT_LENGTH "$(harbor config get ollama.context_length)"
    }

    # 1. Handle configuration-only subcommands first. These do not require
    #    a running service and should be handled before any dispatching.
    case "$1" in
    ctx)
        shift
        env_manager_alias ollama.context_length --on-set update_ollama_env "$@"
        return 0
        ;;
    esac

    # 2. Determine the configured execution path for the 'ollama' service.
    # We dispatch based on PREFERENCE, allowing toolchain commands like
    # `ollama --version` to run even if the daemon is not active.
    local preference; preference=$(_harbor_get_configured_execution_preference "ollama")
    log_debug "Dispatching 'ollama' command with preference: ${preference}"

    # 3. Dispatch to the appropriate runtime.
    if [[ "$preference" == "NATIVE" ]]; then
        # For native, we use the generic helper to find and execute the
        # pre-compiled binary on the host with the correct environment.
        log_info "Executing via native 'ollama' toolchain..."
        _dispatch_native_executable "ollama" "$@"
    else
        # For containers, we use `docker compose run` to create a new,
        # temporary container that can interact with the ollama daemon.
        log_info "Executing via containerized 'ollama' toolchain..."

        # We must check if the container daemon is running for this path.
        if ! is_service_running "ollama"; then
            log_error "Ollama container service is not running. Please start it with 'harbor up ollama'."
            return 1
        fi

        local active_services; active_services=$(get_active_services)
        local ollama_host; ollama_host=$(env_manager get ollama.internal.url)
        local compose_cmd; compose_cmd=$(compose_with_options $active_services "ollama")

        eval "$compose_cmd run --rm \
            -e \"OLLAMA_HOST=$ollama_host\" \
            --name harbor.ollama-cli-$RANDOM \
            -v \"$original_dir:$original_dir\" --workdir \"$original_dir\" \
            ollama \"\$@\""
    fi
}

run_omnichain_command() {
    case "$1" in
    workspace)
        shift
        execute_and_process "env_manager get omnichain.workspace" "sys_open {{output}}" "No omnichain.workspace set"
        ;;
    -h | --help | help)
        echo "Please note that this is not omnichain CLI, but a Harbor CLI to manage aichat service."
        echo
        echo "Usage: harbor aichat <command>"
        echo
        echo "Commands:"
        echo "  harbor omnichain workspace     - Open the aichat workspace directory"
        ;;
    *)
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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
        return $scramble_exit_code
        ;;
    esac
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
        return $scramble_exit_code
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
        return $scramble_exit_code
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

run_promptfoo_command() {
    local services=$(get_active_services)
    log_debug "Active services: $services"

    # Check if the specified service is running
    if ! echo "$services" | grep -q "promptfoo"; then
        log_debug "Promptfoo backend stopped, launching..."
        run_up --no-defaults promptfoo
    else
        log_debug "Promptfoo backend already running."
    fi

    case "$1" in
    view | open | o)
        shift
        run_open promptfoo
        ;;
    esac

    $(compose_with_options $services "promptfoo") run \
        --rm \
        -it \
        --name $default_container_prefix.promptfoo-cli-$RANDOM \
        -e "TERM=xterm-256color" \
        -v "$original_dir:$original_dir" \
        --workdir "$original_dir" \
        --entrypoint promptfoo \
        promptfoo "$@"
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
            return $scramble_exit_code
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
        return $scramble_exit_code
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

run_mcp_command() {
    case "$1" in
    inspector)
        shift
        run_av_tools npx @modelcontextprotocol/inspector "$@"
        return 0
        ;;
    esac
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
    help|-h|--help)
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
version="0.3.12"
harbor_repo_url="https://github.com/av/harbor.git"
harbor_release_url="https://api.github.com/repos/av/harbor/releases/latest"
delimiter="|"
scramble_exit_code=42
harbor_home=${HARBOR_HOME:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")}
profiles_dir="$harbor_home/profiles"
default_profile="$profiles_dir/default.env"
default_current_env="$harbor_home/.env"
default_gum_image="ghcr.io/charmbracelet/gum"
LOG_DIR="$harbor_home/logs"
mkdir -p "$LOG_DIR"

# Desired compose version
desired_compose_major="2"
desired_compose_minor="23"
desired_compose_patch="1"

# --- Global Variables for CLI-wide Flags (Initialized, then parsed from args) ---
_SKIP_DOCKER=false          # If true, skip Docker Compose operations.
_SKIP_NATIVE=false          # If true, skip native service management (e.g., for debugging native issues).
_SKIP_WAIT=false            # If true, skip readiness waiting for services during `up`.
_DRY_RUN=false              # If true, only print commands, do not execute.
_FORCE_CLEANUP=false        # If true, force removal of stale lock files.
_LOG_LEVEL="INFO"           # Default logging level, can be overridden by argument parsing.

# --- Lock File Configuration ---
# This fixed path ensures robust single-instance enforcement for the Harbor CLI itself.
LOCK_FILE="/tmp/harbor_cli_startup.lock"

# --- Global Variables for dynamically loaded native service configuration ---
HARBOR_WAIT_TIMEOUT_SECONDS=60
HARBOR_WAIT_INTERVAL_SECONDS=5

original_dir=$PWD
cd "$harbor_home" || exit

# Set color variables
set_colors
# Initialize the log levels
set_default_log_levels

# Config
ensure_env_file

# Current user ID - FS + UIDs for containers (where applicable)
env_manager --silent set user.id "$(id -u)"
env_manager --silent set group.id "$(id -g)"
env_manager --silent set home.volume "$harbor_home"
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

# --- New: Global Argument Parsing (Runs once at script start) ---
parse_global_args() {
    local remaining_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --no-docker) _SKIP_DOCKER=true; shift ;;
            --no-native | --no-harbor_native) _SKIP_NATIVE=true; shift ;;
            --skip-wait) _SKIP_WAIT=true; shift ;;
            --dry-run) _DRY_RUN=true; _info "DRY RUN mode enabled. No commands will be executed."; shift ;;
            --force) _FORCE_CLEANUP=true; shift ;;
            --log-level)
                if [[ -n "$2" ]]; then
                    _LOG_LEVEL=$(echo "$2" | tr '[:lower:]' '[:upper:]'); [[ ! "$_LOG_LEVEL" =~ ^(DEBUG|INFO|WARN|ERROR)$ ]] && _error "Invalid log level: $2. Must be DEBUG, INFO, WARN, or ERROR."; shift 2
                else _error "--log-level requires an argument."; fi ;;
            *) remaining_args+=("$1"); shift ;;
        esac
    done; set -- "${remaining_args[@]}"; return 0
}

# --- NEW: Check for CLI Dependencies (e.g., `nc`, `curl`, `pgrep`, `deno`) ---
_check_dependencies

# --- NEW: Acquire Lock File to prevent multiple instances of Harbor CLI ---
_acquire_lock # This will exit if another instance is running and not forced.

main_entrypoint() {
    case "$1" in
    up | u)
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
    logs | l)
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
    defaults)
        shift
        env_manager_arr services.default "$@"
        ;;
    alias | aliases | a)
        shift
        env_manager_dict aliases "$@"
        ;;
    link | ln)
        shift
        link_cli "$@"
        ;;
    unlink)
        shift
        unlink_cli "$@"
        ;;
    open | o)
        shift
        run_open "$@"
        ;;
    url)
        shift
        get_url $@
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
    aphrodite)
        shift
        run_aphrodite_command "$@"
        ;;
    openai)
        shift
        run_open_ai_command "$@"
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
    mcp)
        shift
        run_mcp_command "$@"
        ;;
    modularmax)
        shift
        run_modularmax_command "$@"
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
        run_fixfs
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
        run_harbor_cmdh_command "$@"
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
    *)
        return $scramble_exit_code
        ;;
    esac
}

# Call the main logic with argument swapping
if ! swap_and_retry main_entrypoint "$@"; then
    show_help
    exit 1
fi
