#!/bin/bash

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
    echo "  up|u [handle(s)]           - Start the service(s)"
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
    echo "  open handle                   - Open a service in the default browser"
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
    echo "    history list|ls - List recored history"
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

    # Check if Docker is installed and running
    if command -v docker &>/dev/null && docker info &>/dev/null; then
        log_info "${ok} Docker is installed and running"
    else
        log_error "${nok} Docker is not installed or not running. Please install or start Docker."
        return 1
    fi

    # Check if Docker Compose (v2) is installed
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        log_info "${ok} Docker Compose (v2) is installed"
    else
        log_error "${nok} Docker Compose (v2) is not installed. Please install Docker Compose (v2)."
        return 1
    fi

    # Check if the Harbor workspace directory exists
    if [ -d "$harbor_home" ]; then
        log_info "${ok} Harbor home: $harbor_home"
    else
        log_error "${nok} Harbor home does not exist or is not reachable."
        return 1
    fi

    # Check if the default profile file exists and is readable
    if [ -f $default_profile ] && [ -r $default_profile ]; then
        log_info "${ok} Default profile exists and is readable"
    else
        log_error "${nok} Default profile is missing or not readable. Please ensure it exists and has the correct permissions."
        return 1
    fi

    # Check if the .env file exists and is readable
    if [ -f ".env" ] && [ -r ".env" ]; then
        log_info "${ok} Current profile (.env) exists and is readable"
    else
        log_error "${nok} Current profile (.env) is missing or not readable. Please ensure it exists and has the correct permissions."
        return 1
    fi

    # Check if CLI is linked
    if [ -L "$(eval echo "$(env_manager get cli.path)")/$(env_manager get cli.name)" ]; then
        log_info "${ok} CLI is linked"
    else
        log_error "${nok} CLI is not linked. Run 'harbor link' to create a symlink."
        return 1
    fi

    # Check if nvidia-container-toolkit is installed
    if command -v nvidia-container-toolkit &>/dev/null; then
        log_info "${ok} NVIDIA Container Toolkit is installed"
    else
        log_warn "${nok} NVIDIA Container Toolkit is not installed. NVIDIA GPU support may not work."
    fi

    log_info "Harbor Doctor checks completed successfully."
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

compose_with_options() {
    local base_dir="$PWD"
    local compose_files=("$base_dir/compose.yml") # Always include the base compose file
    local options=("${default_options[@]}")

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
        *)
            options+=("$1")
            shift
            ;;
        esac
    done

    # Check for NVIDIA GPU and drivers
    if command -v nvidia-smi &>/dev/null && command -v nvidia-container-toolkit &>/dev/null; then
        options+=("nvidia")
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
                    if [[ ! " ${options[*]} " =~ " ${part} " ]] && [[ ! " ${options[*]} " =~ " * " ]]; then
                        all_matched=false
                        break
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
                    match=true
                    break
                fi

                if [[ $filename == *".$option."* ]]; then
                    match=true
                    break
                fi
            done

            # Include the file if:
            # 1. It matches an option and is not an NVIDIA file
            # 2. It matches an option, is an NVIDIA file, and NVIDIA is supported
            # if $match && (! $is_nvidia_file || ($is_nvidia_file && $has_nvidia)); then
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

    # Return the command string
    echo "$cmd"
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

run_up() {
    local should_tail=false
    local should_open=false
    local filtered_args=()
    local up_args=()

    for arg in "$@"; do
        case "$arg" in
        --no-defaults)
            up_args+=("$arg")
            ;;
        --open | -o)
            should_open=true
            ;;
        --tail | -t)
            should_tail=true
            ;;
        *)
            filtered_args+=("$arg") # Add to filtered arguments
            ;;
        esac
    done

    log_debug "Running 'up' for services: ${up_args[@]} ${filtered_args[@]}"
    $(compose_with_options "${up_args[@]}" "${filtered_args[@]}") up -d --wait

    if [ "$default_autoopen" = "true" ]; then
        run_open "$default_open"
    fi

    for service in "${default_tunnels[@]}"; do
        establish_tunnel "$service"
    done

    if $should_tail; then
        run_logs "$filtered_args"
    fi

    if $should_open; then
        run_open "$filtered_args"
    fi
}

run_down() {
    local services=$(get_active_services)
    local matched_services=()

    log_debug "Active services: $services"

    services=$(echo "$services" | tr ' ' '\n')
    for service in "$@"; do
        log_debug "Checking if service '$service' is in active services list..."
        matched_service=$(echo "$services" | grep "^$service-")
        if [ -n "$matched_service" ]; then
            matched_services+=("$matched_service")
        fi
    done

    log_debug "Matched: ${matched_services[*]}"

    matched_services_str=$(printf " %s" "${matched_services[@]}")
    $(compose_with_options "*") down --remove-orphans "$@" $matched_services_str
}

run_restart() {
    run_down "$@"
    run_up "$@"
}

run_ps() {
    $(compose_with_options "*") ps
}

run_build() {
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

run_run() {
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
    $(compose_with_options $services "$service") run --rm "$service" "$@"
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
    if port=$(docker port "$target_name" | perl -nle 'print m{0.0.0.0:\K\d+}g' | head -n 1) && [ -n "$port" ]; then
        echo "$port"
    else
        log_error "No port mapping found for service '$1': $port"
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

get_adressable_url() {
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
    local is_adressable=false
    local is_intra=false

    local filtered_args=()
    local arg

    for arg in "$@"; do
        case "$arg" in
        --intra | -i | --internal)
            is_local=false
            is_adressable=false
            is_intra=true
            ;;
        --addressable | -a | --lan)
            is_local=false
            is_intra=false
            is_adressable=true
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
log_debug() { log "DEBUG" "${c_gray}$@${c_nc}"; }
log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }

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
    sudo setfacl --recursive -m user:1000:rwx $folder \
    && sudo setfacl --recursive -m user:1002:rwx $folder \
    && sudo setfacl --recursive -m user:1001:rwx $folder \
    && sudo setfacl --recursive -m user:100:rwx $folder \
    && sudo setfacl --recursive -m user:911:rwx $folder \
    && sudo setfacl --recursive -m user:101:rwx $folder
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

get_active_services() {
    docker compose ps --format "{{.Service}}" | tr '\n' ' '
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
    cache_dirs=$(h config ls | grep CACHE | awk '{print $NF}' | sed "s|~|$HOME|g")
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

# shellcheck disable=SC2034
__anchor_service_clis=true

run_gum() {
    docker run --rm -it -e "TERM=xterm-256color" $default_gum_image "$@"
}

run_dive() {
    local dive_image=wagoodman/dive
    docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock $dive_image "$@"
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
        env_manager_alias llamacpp.gguf "$@"
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

run_plandex_command() {
    case "$1" in
    health)
        shift
        execute_and_process "get_url plandexserver" "curl {{output}}/health" "No plandexserver URL:"
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

    # Mount the current directory and set it as the working directory
    $(compose_with_options $services "cmdh" "harbor") run \
        --rm \
        -v "$harbor_home/cmdh/harbor.prompt:/app/cmdh/system.prompt" \
        -v "$original_dir:$original_dir" \
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
        -v "$original_dir:/root/workspace" \
        --workdir "/root/workspace" \
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

run_ollama_command() {
    local services=$(get_active_services)
    local ollama_host=$(env_manager get ollama.internal.url)

    # If ollama is not in $services - inform user
    if ! is_service_running "ollama"; then
        log_error "Please start ollama service to use 'harbor ollama'"
        exit 1
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
            ;;        version)
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
        view|open|o)
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

    if [ "$is_running" = true ] ; then
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

# ========================================================================
# == Main script
# ========================================================================

# Globals
version="0.2.21"
harbor_repo_url="https://github.com/av/harbor.git"
harbor_release_url="https://api.github.com/repos/av/harbor/releases/latest"
delimiter="|"
scramble_exit_code=42
harbor_home=${HARBOR_HOME:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")}
profiles_dir="$harbor_home/profiles"
default_profile="$profiles_dir/default.env"
default_current_env="$harbor_home/.env"
default_gum_image="ghcr.io/charmbracelet/gum"

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
default_options=($(env_manager get services.default | tr ';' ' '))
default_tunnels=($(env_manager get services.tunnels | tr ';' ' '))
default_open=$(env_manager get ui.main)
default_autoopen=$(env_manager get ui.autoopen)
default_container_prefix=$(env_manager get container.prefix)
default_log_level=$(env_manager get log.level)
default_history_file=$(env_manager get history.file)
default_history_size=$(env_manager get history.size)

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
    promptfoo|pf)
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
