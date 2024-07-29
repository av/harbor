#!/bin/bash

default_options=("webui" "ollama")
version="0.0.1"

compose_with_options() {
    local base_dir="$PWD"
    local compose_files=("compose.yml")  # Always include the base compose file
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

    # Loop through compose files in the directory
    for file in "$base_dir"/compose.*.yml; do
        if [ -f "$file" ]; then
            local filename=$(basename "$file")
            local match=false
            local is_nvidia_file=false

            # Check if file matches any of the options
            for option in "${options[@]}"; do
                if [[ $option == "*" ]]; then
                    match=true
                    break
                fi

                if [[ $filename == *"$option"* ]]; then
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

show_version() {
    echo "Harbor CLI version: $version"
}

show_help() {
    echo "Usage: $0 <command> [options]"
    echo
    echo "Compose Setup Commands:"
    echo "  up       - Start the containers"
    echo "  down     - Stop and remove the containers"
    echo "  ps       - List the running containers"
    echo "  logs     - View the logs of the containers"
    echo "  help     - Show this help message"
    echo
    echo "Setup Manageent Commands:"
    echo "  hf       - Run the Hugging Face CLI"
    echo
    echo "CLI Commands:"
    echo "  ln       - Create a symbolic link to the CLI"
    echo "  defaults - Show the default services"
    echo "  version  - Show the CLI version"
    echo
    echo "Options:"
    echo "  Additional options to pass to the compose_with_options function"
}

run_hf_cli() {
    local hf_cli_image=shaowenchen/huggingface-cli
    docker run --rm --log-driver none -v ~/.cache/huggingface:/root/.cache/huggingface $hf_cli_image $@
}

show_default_services() {
    echo "Default services:"
    for service in "${default_options[@]}"; do
        echo "  - $service"
    done
}

link_cli() {
    ln -s $(pwd)/harbor.sh ~/bin/harbor
}

open_webui() {
    local webui_url="http://localhost:33801/"
    if command -v xdg-open &> /dev/null; then
        xdg-open $webui_url
    elif command -v open &> /dev/null; then
        open $webui_url
    else
        echo "Open the following URL in your browser: $webui_url"
    fi
}

# Main script logic
case "$1" in
    up)
        shift
        $(compose_with_options "$@") up -d
        ;;
    down)
        shift
        $(compose_with_options "*") down
        ;;
    ps)
        shift
        $(compose_with_options "*") ps -a
        ;;
    logs)
        shift
        $(compose_with_options "*") logs -n 20 -f
        ;;
    help)
        show_help
        ;;
    --help)
        show_help
        ;;
    hf)
        shift
        run_hf_cli $@
        ;;
    defaults)
        shift
        show_default_services
        ;;
    ln)
        shift
        link_cli
        ;;
    open)
        shift
        open_webui
        ;;
    version)
        shift
        show_version
        ;;
    --version)
        shift
        show_version
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac