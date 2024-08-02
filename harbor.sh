#!/bin/bash

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
    echo "  up            - Start the containers"
    echo "  down          - Stop and remove the containers"
    echo "  ps            - List the running containers"
    echo "  logs          - View the logs of the containers"
    echo "  exec          - Execute a command in a running service"
    echo "  pull          - Pull the latest images"
    echo "  dive          - Run the Dive CLI to inspect Docker images"
    echo
    echo "Setup Management Commands:"
    echo "  ollama        - Run the Harbor's Ollama CLI. Ollama service should be running"
    echo "  smi           - Show NVIDIA GPU information"
    echo "  top           - Run nvtop to monitor GPU usage"
    echo "  llamacpp      - Configure llamacpp service"
    echo "  tgi           - Configure text-generation-inference service"
    echo "  litellm       - Configure LiteLLM service"
    echo "  openai        - Configure OpenAI API keys and URLs"
    echo "  vllm          - Configure VLLM service"
    echo "  aphrodite     - Configure Aphrodite service"
    echo
    echo "Huggingface CLI:"
    echo "  hf            - Run the Harbor's Huggingface CLI. Expanded with a few additional commands."
    echo "  hf parse-url  - Parse file URL from Hugging Face"
    echo "  hf token      - Get/set the Hugging Face Hub token"
    echo
    echo "Harbor CLI Commands:"
    echo "  open                  - Open a service in the default browser"
    echo "  url                   - Get the URL for a service"
    echo "  config                - Manage the Harbor environment configuration"
    echo "  ln                    - Create a symbolic link to the CLI"
    echo "  eject                 - Eject the Compose configuration, accepts same options as 'up'"
    echo "  defaults [ls]         - List default services"
    echo "  defaults rm           - Remove default services, no options to remove all, accepts handle or index"
    echo "  defaults add <handle> - Add a default service"
    echo "  help                  - Show this help message"
    echo "  version               - Show the CLI version"
    echo "  gum                   - Run the Gum terminal commands"
    echo "  fixfs                 - Fix file system ACLs for service volumes"
    echo "  info                  - Show system information for debug/issues"
    echo
    echo "Options:"
    echo "  Additional options to pass to the compose_with_options function"
}

compose_with_options() {
    local base_dir="$PWD"
    local compose_files=("$base_dir/compose.yml")  # Always include the base compose file
    local options=("${default_options[@]}")

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dir=*)
                base_dir="${1#*=}"
                shift
                ;;
            *)
                options+=("$1")
                shift
                ;;
        esac
    done

    # Check for NVIDIA GPU and drivers
    local has_nvidia=false
    if command -v nvidia-smi &> /dev/null && docker info | grep -q "Runtimes:.*nvidia"; then
        has_nvidia=true
    fi

    for file in "$base_dir"/compose.*.yml; do
        if [ -f "$file" ]; then
            local filename=$(basename "$file")
            local match=false
            local is_nvidia_file=false

            # This is a "cross" file, only to be included
            # if we're running all the mentioned services
            if [[ $filename == *".x."* ]]; then
                local cross="${filename#compose.x.}"
                cross="${cross%.yml}"

                # Convert dot notation to array
                local filename_parts=(${cross//./ })
                local all_matched=true

                for part in "${filename_parts[@]}"; do
                    if [[ ! " ${options[*]} " =~ " ${part} " ]]; then
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

            # Check if it's an NVIDIA file
            if [[ $filename == *".nvidia."* ]]; then
                is_nvidia_file=true
            fi

            # Include the file if:
            # 1. It matches an option and is not an NVIDIA file
            # 2. It matches an option, is an NVIDIA file, and NVIDIA is supported
            if $match && (! $is_nvidia_file || ($is_nvidia_file && $has_nvidia)); then
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

run_hf_cli() {
    case "$1" in
        parse-url)
            shift
            parse_hf_url $@
            return
            ;;
        token)
            shift
            env_manager_alias hf.hub.token $@
            return
            ;;
    esac

    local hf_cli_image=shaowenchen/huggingface-cli
    docker run --rm --log-driver none -v ~/.cache/huggingface:/root/.cache/huggingface $hf_cli_image $@
}

run_gum() {
    local gum_image=ghcr.io/charmbracelet/gum
    docker run --rm -it -e "TERM=xterm-256color" $gum_image $@
}

run_dive() {
    local dive_image=wagoodman/dive
    docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock $dive_image $@
}

link_cli() {
    local target_dir="$HOME/.local/bin"
    local script_name="harbor"
    local script_path="$harbor_home/harbor.sh"

    # Check if target directory exists in PATH
    if ! echo $PATH | tr ':' '\n' | grep -q "$target_dir"; then
        echo "Creating $target_dir and adding it to PATH..."
        mkdir -p "$target_dir"
        echo -e '\nexport PATH="$PATH:$HOME/.local/bin"\n' >> "$HOME/.bashrc"
        export PATH="$PATH:$HOME/.local/bin"
    fi

    # Create symlink
    if ln -s "$script_path" "$target_dir/$script_name"; then
        echo "Symlink created: $target_dir/$script_name -> $script_path"
        echo "You may need to reload your shell or run 'source ~/.bashrc' for changes to take effect."
    else
        echo "Failed to create symlink. Please check permissions and try again."
        return 1
    fi
}

get_service_url() {
    # Get list of running services
    services=$(docker ps --format "{{.Names}}")

    # Check if any services are running
    if [ -z "$services" ]; then
        echo "No services are currently running."
        return 1
    fi

    # If no service name provided, default to webui
    if [ -z "$1" ]; then
        get_service_url "$default_open"
        return 0
    fi

    local target_name="$default_container_prefix.$1"

    # Check if the specified service is running
    if ! echo "$services" | grep -q "^$target_name$"; then
        echo "Service '$1' is not currently running."
        echo "Available services:"
        echo "$services"
        return 1
    fi

    # Get the port mapping for the service
    port=$(docker port "$target_name" | grep -oP '0.0.0.0:\K\d+' | head -n 1)

    if [ -z "$port" ]; then
        echo "No port mapping found for service '$1'."
        return 1
    fi

    # Construct the URL
    url="http://localhost:$port"

    echo "$url"
}

sys_info() {
    docker info
}

sys_open() {
    url=$1

    # Open the URL in the default browser
    if command -v xdg-open &> /dev/null; then
        xdg-open "$url"  # Linux
    elif command -v open &> /dev/null; then
        open "$url"  # macOS
    elif command -v start &> /dev/null; then
        start "$url"  # Windows
    else
        echo "Unable to open browser. Please visit $url manually."
        return 1
    fi
}

open_service() {
    output=$(get_service_url "$1" 2>&1) || {
        echo "Failed to get service URL for $1. Error output:" >&2;
        echo "$output" >&2;
        exit 1;
    }
    url="$output"
    sys_open "$url"
    echo "Opened $url in your default browser."
}

smi() {
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi
    else
        echo "nvidia-smi not found."
    fi
}

nvidia_top() {
    if command -v nvtop &> /dev/null; then
        nvtop
    else
        echo "nvtop not found."
    fi
}

eject() {
    $(compose_with_options "$@") config
}

run_in_service() {
    local service_name="$1"
    shift
    local command_to_run="$@"

    if docker compose ps --services --filter "status=running" | grep -q "^${service_name}$"; then
        echo "Service ${service_name} is running. Executing command..."
        docker compose exec ${service_name} ${command_to_run}
    else
        echo "Harbor ${service_name} is not running. Please start it with 'harbor up ${service_name}' first."
    fi
}

exec_ollama() {
    run_in_service ollama ollama "$@"
}

# ========================================================================
# == Env Manager
# ========================================================================

env_manager() {
    local env_file=".env"
    local prefix="HARBOR_"

    transform_llamacpp_model() {
        local url="$1"
        local repo=$(echo "$url" | sed -n 's|https://huggingface.co/\(.*\)/blob/.*|\1|p')
        local file=$(basename "$url")
        echo "--hf-repo $repo --hf-file $file"
    }

    case "$1" in
        get)
            if [[ -z "$2" ]]; then
                echo "Usage: env_manager get <key>"
                return 1
            fi
            local upper_key=$(echo "$2" | tr '[:lower:]' '[:upper:]' | tr '.' '_')
            value=$(grep "^$prefix$upper_key=" "$env_file" | cut -d '=' -f2-)
            value="${value#\"}"  # Remove leading quote if present
            value="${value%\"}"  # Remove trailing quote if present
            echo "$value"
            ;;
        set)
            if [[ -z "$2" ]]; then
                echo "Usage: env_manager set <key> <value>"
                return 1
            fi

            local upper_key=$(echo "$2" | tr '[:lower:]' '[:upper:]' | tr '.' '_')
            shift 2  # Remove 'set' and the key from the arguments
            local value="$*"  # Capture all remaining arguments as the value

            if grep -q "^$prefix$upper_key=" "$env_file"; then
                sed -i "s|^$prefix$upper_key=.*|$prefix$upper_key=\"$value\"|" "$env_file"
            else
                echo "$prefix$upper_key=\"$value\"" >> "$env_file"
            fi
            echo "Set $prefix$upper_key to: \"$value\""
            ;;
        list)
            grep "^$prefix" "$env_file" | sed "s/^$prefix//" | while read -r line; do
                key=${line%%=*}
                value=${line#*=}
                value=$(echo "$value" | sed -E 's/^"(.*)"$/\1/')  # Remove surrounding quotes for display
                printf "%-30s %s\n" "$key" "$value"
            done
            ;;
        *)
            echo "Usage: harbor config {get|set|list} [key] [value]"
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

    if [ $# -eq 0 ]; then
        env_manager get $field
        if [ -n "$get_command" ]; then
            eval "$get_command"
        fi
    else
        env_manager set $field $@
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
        ls|"")
            # Show all values
            local array=$(get_array)
            if [ -z "$array" ]; then
                echo "Config $field is empty"
            else
                echo "$array" | tr "$delimiter" "\n"
            fi
            if [ -n "$get_command" ]; then
                eval "$get_command"
            fi
            ;;
        rm)
            if [ -z "$value" ]; then
                # Remove all values
                set_array ""
                echo "All values removed from $field"
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
                echo "Value removed from $field"
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
            echo "Value added to $field"
            if [ -n "$add_command" ]; then
                eval "$add_command"
            fi
            ;;
        *)
            echo "Usage: env_manager_arr <field> [--on-get <command>] [--on-set <command>] [--on-add <command>] [--on-remove <command>] {ls|rm|add} [value]"
            return 1
            ;;
    esac
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
    ' "$file" > "$temp_file" && mv "$temp_file" "$file"

    if [ $? -eq 0 ]; then
        echo "Successfully updated '$key' in $file"
    else
        echo "Failed to update '$key' in $file"
        return 1
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

run_llamacpp_command() {
    update_model_spec() {
        local spec=""
        local current_model=$(env_manager get llamacpp.model)

        if [ -n "$current_model" ]; then
            spec=$(hf_url_2_llama_spec $current_model)
        fi

        env_manager set llamacpp.model.specifier "$spec"
    }

    case "$1" in
        model)
            shift
            env_manager_alias llamacpp.model --on-set update_model_spec $@
            ;;
        args)
            shift
            env_manager_alias llamacpp.extra.args $@
            ;;
        *)
            echo "Please note that this is not llama.cpp CLI, but a Harbor CLI to manage llama.cpp service."
            echo "Access llama.cpp own CLI by running 'harbor exec llamacpp' when it's running."
            echo
            echo "Usage: harbor llamacpp <command>"
            echo
            echo "Commands:"
            echo "  harbor llamacpp model [Huggingface URL] - Get or set the llamacpp model to run"
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
            env_manager_alias tgi.model --on-set update_model_spec $@
            ;;
        args)
            shift
            env_manager_alias tgi.extra.args $@
            ;;
        quant)
            shift
            env_manager_alias tgi.quant --on-set update_model_spec $@
            ;;
        revision)
            shift
            env_manager_alias tgi.revision --on-set update_model_spec $@
            ;;
        *)
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
    esac
}

docker_fsacl() {
    local folder=$1
    sudo setfacl --recursive -m user:1000:rwx $folder && sudo setfacl --recursive -m user:1002:rwx $folder && sudo setfacl --recursive -m user:1001:rwx $folder
}

fix_fs_acl() {
    docker_fsacl ./ollama
    docker_fsacl ./langfuse
    docker_fsacl ./open-webui
    docker_fsacl ./tts
    docker_fsacl ./librechat
    docker_fsacl ./searxng
}

run_litellm_command() {
    case "$1" in
        username)
            shift
            env_manager_alias litellm.ui.username $@
            ;;
        password)
            shift
            env_manager_alias litellm.ui.password $@
            ;;
        ui)
            shift
            if service_url=$(get_service_url litellm 2>&1); then
                sys_open "$service_url/ui"
            else
                echo "Error: Failed to get service URL for litellm: $service_url"
                exit 1
            fi
            ;;
        *)
            echo "Please note that this is not LiteLLM CLI, but a Harbor CLI to manage LiteLLM service."
            echo
            echo "Usage: harbor litellm <command>"
            echo
            echo "Commands:"
            echo "  harbor litellm username [username] - Get or set the LITeLLM UI username"
            echo "  harbor litellm password [username] - Get or set the LITeLLM UI password"
            echo "  harbor litellm ui                  - Open LiteLLM UI screen"
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
            env_manager_alias vllm.model --on-set update_model_spec $@
            ;;
        args)
            shift
            env_manager_alias vllm.extra.args $@
            ;;
        attention)
            shift
            env_manager_alias vllm.attention_backend $@
            ;;
        *)
            echo "Please note that this is not VLLM CLI, but a Harbor CLI to manage VLLM service."
            echo "Access VLLM own CLI by running 'harbor exec vllm' when it's running."
            echo
            echo "Usage: harbor vllm <command>"
            echo
            echo "Commands:"
            echo "  harbor vllm model [user/repo]   - Get or set the VLLM model repository to run"
            echo "  harbor vllm args [args]         - Get or set extra args to pass to the VLLM CLI"
            echo "  harbor vllm attention [backend] - Get or set the attention backend to use"
            ;;
    esac
}

run_aphrodite_command() {
    case "$1" in
        model)
            shift
            env_manager_alias aphrodite.model $@
            ;;
        args)
            shift
            env_manager_alias aphrodite.extra.args $@
            ;;
        *)
            echo "Please note that this is not Aphrodite CLI, but a Harbor CLI to manage Aphrodite service."
            echo "Access Aphrodite own CLI by running 'harbor exec aphrodite' when it's running."
            echo
            echo "Usage: harbor aphrodite <command>"
            echo
            echo "Commands:"
            echo "  harbor aphrodite model <user/repo>   - Get/set the Aphrodite model to run"
            echo "  harbor aphrodite args <args>         - Get/set extra args to pass to the Aphrodite CLI"
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
            env_manager_arr openai.keys --on-set update_main_key $@
            ;;
        urls)
            shift
            env_manager_arr openai.urls --on-set update_main_url $@
            ;;
        *)
            echo "Please note that this is not an OpenAI CLI, but a Harbor CLI to manage OpenAI configuration."
            echo
            echo "Usage: harbor openai <command>"
            echo
            echo "Commands:"
            echo "  harbor openai keys [ls|rm|add]   - Get/set the API Keys for the OpenAI-compatible APIs."
            echo "  harbor openai urls [ls|rm|add]   - Get/set the API URLs for the OpenAI-compatible APIs."
            ;;
    esac
}

run_webui_command() {
    case "$1" in
        secret)
            shift
            env_manager_alias webui.secret $@
            ;;
        name)
            shift
            env_manager_alias webui.name $@
            ;;
        log)
            shift
            env_manager_alias webui.log.level $@
            ;;
        *)
            echo "Please note that this is not WebUI CLI, but a Harbor CLI to manage WebUI service."
            echo
            echo "Usage: harbor webui <command>"
            echo
            echo "Commands:"
            echo "  harbor webui secret [secret]   - Get/set WebUI JWT Secret"
            echo "  harbor webui name [name]       - Get/set the name WebUI will present"
            echo "  harbor webui log [level]       - Get/set WebUI log level"
            ;;
    esac

}


# ========================================================================
# == Main script
# ========================================================================

version="0.0.11"
delimiter="|"

harbor_home=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
original_dir=$PWD

cd $harbor_home

default_options=($(env_manager get services.default | tr ';' ' '))
default_open=$(env_manager get ui.main)
default_autoopen=$(env_manager get ui.autoopen)
default_container_prefix=$(env_manager get container.prefix)

# Main script logic
case "$1" in
    up)
        shift
        $(compose_with_options "$@") up -d

        if [ "$default_autoopen" = "true" ]; then
            open_service $default_open
        fi
        ;;
    down)
        shift
        $(compose_with_options "*") down "$@"
        ;;
    ps)
        shift
        $(compose_with_options "*") ps
        ;;
    logs)
        shift
        # Only pass "*" to the command if no options are provided
        $(compose_with_options "*") logs -n 20 -f "$@"
        ;;
    pull)
        shift
        $(compose_with_options "$@") pull
        ;;
    exec)
        shift
        run_in_service $@
        ;;
    run)
        shift
        service=$1
        shift
        $(compose_with_options "$service") run --rm $service $@
        ;;
    cmd)
        shift
        echo $(compose_with_options "$@")
        ;;
    help|--help|-h)
        show_help
        ;;
    hf)
        shift
        run_hf_cli $@
        ;;
    defaults)
        shift
        env_manager_arr services.default $@
        ;;
    ln)
        shift
        link_cli
        ;;
    open)
        shift
        open_service $@
        ;;
    url)
        shift
        get_service_url $@
        ;;
    version|--version|-v)
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
        run_dive $@
        ;;
    eject)
        shift
        eject $@
        ;;
    ollama)
        shift
        exec_ollama $@
        ;;
    llamacpp)
        shift
        run_llamacpp_command $@
        ;;
    tgi)
        shift
        run_tgi_command $@
        ;;
    litellm)
        shift
        run_litellm_command $@
        ;;
    vllm)
        shift
        run_vllm_command $@
        ;;
    aphrodite)
        shift
        run_aphrodite_command $@
        ;;
    openai)
        shift
        run_open_ai_command $@
        ;;
    webui)
        shift
        run_webui_command $@
        ;;
    config)
        shift
        env_manager $@
        ;;
    gum)
        shift
        run_gum $@
        ;;
    fixfs)
        shift
        fix_fs_acl
        ;;
    info)
        shift
        sys_info
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
