#!/usr/bin/env bash
# speaches/speaches_native.sh
#
# Native Service Entrypoint for Speaches in Harbor
#
# This script serves as the entrypoint for running Speaches natively via Harbor's
# hybrid orchestration system. It follows the Docker-style ENTRYPOINT + CMD
# pattern where Harbor passes the complete command to execute.
#
# DESIGN PATTERN:
# This script uses a hybrid approach to handle multiple installation methods
# for Speaches. Unlike simpler services like Ollama, Speaches may be installed
# as a Python package, conda environment, or system binary, so we need more
# sophisticated detection and execution logic.
#
# SUPPORTED INSTALLATION METHODS:
# 1. System Binary: `speaches` command available in PATH
# 2. Python Module: `python -m speaches` (pip install speaches)
# 3. Conda Environment: Speaches installed in a conda environment
# 4. Direct Python: speaches module available in current Python environment
#
# USAGE PATTERNS:
# Harbor calls this script with the full command to execute:
#
# Daemon Startup:
#   speaches_native.sh "speaches" "--host" "0.0.0.0" "--port" "34331"
#
# The script will transform this based on the detected installation method:
# - Binary: speaches --host 0.0.0.0 --port 34331
# - Module: python -m speaches --host 0.0.0.0 --port 34331
# - Conda: conda run -n speaches-env speaches --host 0.0.0.0 --port 34331
#
# ERROR HANDLING:
# This script provides comprehensive validation and helpful error messages:
# - Detects available installation methods
# - Validates Python environment if needed
# - Checks for required dependencies
# - Provides installation guidance on failure
#
# LOGGING:
# This script's stdout/stderr are redirected to Harbor's log directory:
# $HARBOR_HOME/app/backend/data/logs/harbor-speaches-native.log

set -euox pipefail # Strict mode for robustness.

# potential brew dependencies to install: brew install uv onnxruntime uvicorn ffmpeg
# speaches uv install needs the sync command to have extras:
# uv sync --all-extras
#
# also upgrade packages (may break things): uv sync --all-extras --upgrade
#
# example of running the cli command:
# uvx speaches-cli registry ls
#
# Downloading a Text To Speech (TTS) model:
# ± uvx speaches-cli model download speaches-ai/Kokoro-82M-v1.0-ONNX
#
# Downloading a Speech To Text (STT) model:
# ± uvx speaches-cli model download Systran/faster-distil-whisper-small.en
#
# models of note:
# uvx speaches-cli model download speaches-ai/Kokoro-82M-v1.0-ONNX
# uvx speaches-cli model download Systran/faster-distil-whisper-small.en
#
# Run with ui:
# export DO_NOT_TRACK=1 && export ENABLE_UI=TRUE && uvicorn --factory --host 0.0.0.0 speaches.main:create_app

#!/usr/bin/env bash
#
# speaches_native.sh: Robust, self-contained installer and launcher for Speaches.
# Variation: robust-script-v3

set -euo pipefail

# --- Configuration ---
# Use Harbor's cache, fall back to user's home cache.
HARBOR_CACHE_DIR="${HARBOR_HF_CACHE:-$HOME/.cache/harbor}"
SPEACHES_INSTALL_DIR="$HARBOR_CACHE_DIR/speaches_native_install"
VENV_DIR="$SPEACHES_INSTALL_DIR/venv"
PYTHON_VERSION_TARGET="3.10" # Target for librosa/numba compatibility
LOG_PREFIX="[speaches_native.sh]"

# --- Helper Functions ---
log_info() {
    echo "$LOG_PREFIX INFO: $1" >&2
}

log_error() {
    echo "$LOG_PREFIX ERROR: $1" >&2
    exit 1
}

command_exists() {
    command -v "$1" &>/dev/null
}

# --- Core Logic Functions ---

# Ensures uv is installed, trying multiple methods.
ensure_uv_available() {
    if command_exists uv; then
        log_info "uv is already installed: $(command -v uv)"
        return
    fi
    log_info "uv not found, attempting installation..."
    if command_exists curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source "$HOME/.cargo/env" || true
    elif command_exists pip3; then
        pip3 install uv
    else
        log_error "Cannot install uv. Please install 'curl' or 'pip3' and try again."
    fi
    if ! command_exists uv; then
        log_error "uv installation failed. Please install it manually."
    fi
}

# Finds a compatible Python interpreter (3.10 or 3.11).
find_compatible_python() {
    for py_cmd in "python${PYTHON_VERSION_TARGET}" "python3.11" "python3"; do
        if command_exists "$py_cmd"; then
            version=$($py_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            if [[ "$version" == "3.10" || "$version" == "3.11" ]]; then
                log_info "Found compatible Python at $($py_cmd -c 'import sys; print(sys.executable)')"
                echo "$py_cmd"
                return
            fi
        fi
    done
    log_error "No compatible Python found. Please install Python 3.10 or 3.11."
}

# The main installation and patching logic.
install_and_patch_speaches() {
    local python_cmd="$1"

    # 1. Create a stable installation directory and virtual environment
    mkdir -p "$SPEACHES_INSTALL_DIR"
    if [ ! -d "$VENV_DIR" ]; then
        log_info "Creating virtual environment at $VENV_DIR with $python_cmd..."
        uv venv "$VENV_DIR" -p "$python_cmd"
    else
        log_info "Virtual environment already exists at $VENV_DIR"
    fi

    # 2. Check if speaches is already installed and working.
    if "$VENV_DIR/bin/python" -c "import speaches" &>/dev/null; then
        log_info "Speaches is already installed in the venv. Skipping installation."
        return
    fi

    # 3. Attempt a direct install first. This will fail but we try anyway.
    log_info "Attempting direct install of speaches (this may fail and trigger patching)..."
    if "$VENV_DIR/bin/uv" pip install "speaches[server]" &>/dev/null; then
        log_info "Direct installation successful! No patching needed."
        return
    fi

    # 4. Clone-and-patch strategy
    log_info "Direct install failed as expected. Proceeding with clone-and-patch strategy."
    local speaches_repo_dir="$SPEACHES_INSTALL_DIR/speaches_repo"
    if [ ! -d "$speaches_repo_dir" ]; then
        log_info "Cloning speaches repository into $speaches_repo_dir..."
        git clone https://github.com/speaches-ai/speaches.git "$speaches_repo_dir"
    else
        log_info "speaches repository already cloned. Pulling latest changes..."
        (cd "$speaches_repo_dir" && git pull)
    fi

    # 5. Patch pyproject.toml
    local pyproject_file="$speaches_repo_dir/pyproject.toml"
    log_info "Patching $pyproject_file to allow Python ${PYTHON_VERSION_TARGET}..."
    # This sed command is cross-platform (works on macOS and Linux)
    sed -i.bak 's/requires-python = ">=3.12,<3.13"/requires-python = ">=3.10,<3.13"/' "$pyproject_file"
    rm -f "${pyproject_file}.bak"
    log_info "Patching complete."

    # 6. Install the patched local version with all extras
    log_info "Installing patched speaches from local directory with all extras..."
    "$VENV_DIR/bin/uv" pip install --system --all-extras -e "$speaches_repo_dir"

    log_info "Speaches installation completed successfully."
}

# Setup ONNX for GPU or CPU
setup_onnx_providers() {
    # This function would contain the ONNX provider detection logic
    # from the original script or delegate to onnx_utils.py
    log_info "Setting up ONNX providers..."
    # For brevity, assuming onnx_utils.py is called if present.
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    if [ -f "$SCRIPT_DIR/onnx_utils.py" ]; then
        log_info "Using onnx_utils.py for advanced provider detection."
        # Exporting variables set by the python script
        eval $("$VENV_DIR/bin/python" "$SCRIPT_DIR/onnx_utils.py" --setup)
    else
        log_info "Basic ONNX provider detection..."
        # Simplified fallback logic
        if [[ "$(uname)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
            export ONNX_PROVIDER="${ONNX_PROVIDER:-CoreMLExecutionProvider,CPUExecutionProvider}"
        elif command_exists nvidia-smi; then
            export ONNX_PROVIDER="${ONNX_PROVIDER:-CUDAExecutionProvider,CPUExecutionProvider}"
        else
            export ONNX_PROVIDER="${ONNX_PROVIDER:-CPUExecutionProvider}"
        fi
    fi
    log_info "ONNX_PROVIDER set to: ${ONNX_PROVIDER}"
}


# --- Main Execution ---

if [[ $# -eq 0 ]]; then
    log_error "No command provided. Usage: $0 <command> [args...]"
fi

log_info "--- Speaches Native Launcher Initializing ---"

ensure_uv_available
COMPATIBLE_PYTHON=$(find_compatible_python)
install_and_patch_speaches "$COMPATIBLE_PYTHON"
setup_onnx_providers

# Harbor passes the command and args from speaches_native.yml here.
# For example: `harbor-speaches-server --host 0.0.0.0`
# The final command in the chain is executed via `exec`.
log_info "Handing off to command: $VENV_DIR/bin/$1 ${@:2}"
exec "$VENV_DIR/bin/$1" "${@:2}"

# continue your process and your wait process, I want to iterate on sub-variations on variation 1, I would like to support brew whenever it is available which can include, I also believe that by integrating a more robust version of the following we can
# brew install uv onnxruntime uvicorn ffmpeg
# # uv init --python=3.12
# uv init
# uv sync --all-extras --upgrade
# uvx speaches-cli model download ${HARBOR_SPEACHES_STT_MODEL:-Systran/faster-distil-whisper-small.en}
# uvx speaches-cli model download ${HARBOR_SPEACHES_TTS_MODEL:-speaches-ai/Kokoro-82M-v1.0-)

# export ENABLE_UI=TRUE && uvicorn --factory --host 0.0.0.0 speaches.main:create_app