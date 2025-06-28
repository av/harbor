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

set -euo pipefail # Strict mode to stop on errors.

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
#!/usr/bin/env bash
#
# ==============================================================================
# speaches_native.sh: (v4.0) Final Synthesized Native Launcher for Harbor
# ==============================================================================
#
# This script is the all-in-one entrypoint for running the Speaches service
# natively. It is idempotent, robust, state-aware, and developer-friendly.
#
# It handles all setup, dependency patching, and execution in a linear,
# robust, and idempotent manner. It is designed to be run by Harbor,
# expecting command-line arguments to be passed for execution.
#
# ------------------------------------------------------------------------------
# --- Quickstart & Setup Sequence (New Method as of PR #449) ---
# PR Link: https://github.com/speaches-ai/speaches/pull/449
#
# This script automates the following manual steps:
#
# # 1. Clone the repository (using the simplified CLI branch)
# # git clone -b cli-simplified-locked https://github.com/ahundt/speaches.git
# # cd speaches
#
# # 2. Setup environment and install tools
# # uv venv
# # source .venv/bin/activate
# # uv sync --all-extras --upgrade
# # uv tool install .
#
# # 3. Download models (replaces old 'uvx speaches-cli ...' command)
# # speaches model download speaches-ai/Kokoro-82M-v1.0-ONNX
# # speaches model download Systran/faster-distil-whisper-small.en
#
# # 4. Run the server (replaces direct 'uvicorn ...' command)
# # speaches serve --host 0.0.0.0 --port 8000
# ------------------------------------------------------------------------------

# ==============================================================================
# --- Script Configuration ---
# All parameters can be overridden by setting the corresponding environment variable.
# ==============================================================================
LOG_PREFIX="[speaches_native.sh v4.0]"

# variable to force setup of the repository and virtual environment
HARBOR_SPEACHES_FORCE_SETUP="${HARBOR_SPEACHES_FORCE_SETUP:-false}"
# --- Paths Configuration ---
# The workspace is now located directly inside the `speaches` service directory.
# This can be overridden by setting HARBOR_SPEACHES_WORKSPACE.
HARBOR_SPEACHES_WORKSPACE="${HARBOR_SPEACHES_WORKSPACE:-$HARBOR_HOME/speaches/workspace}"

# All artifacts (venv, repo) will be placed inside this workspace.
VENV_DIR="$HARBOR_SPEACHES_WORKSPACE/venv"
# REPO LOCATION: The speaches git repository will be cloned to this directory.
REPO_DIR="$HARBOR_SPEACHES_WORKSPACE/speaches_repo"
# Marker file for fast-path launches.
STATE_FILE="$HARBOR_SPEACHES_WORKSPACE/.setup_complete"

# --- Python Configuration ---
# User can force a Python command with HARBOR_PYTHON_CMD (e.g., /usr/local/bin/python3.10)
export OVERRIDE_PYTHON_CMD="${HARBOR_PYTHON_CMD:-}"
# User can specify a preferred Python version (e.g., 3.10 or 3.11)
export HARBOR_PYTHON_VERSION="${HARBOR_PYTHON_VERSION:-}"
# If not overridden, the script will search for these Python versions in order.

# --- Speaches Configuration ---
# The repository and branch are now updated to the new, simplified CLI version.
export SPEACHES_REPO_URL="${SPEACHES_REPO_URL:-https://github.com/ahundt/speaches.git}"
export SPEACHES_REPO_BRANCH="${SPEACHES_REPO_BRANCH:-cli-simplified-locked}"
# Default models to pre-download. Can be overridden by Harbor env vars.
export SPEACHES_STT_MODEL="${HARBOR_SPEACHES_STT_MODEL:-Systran/faster-distil-whisper-small.en}"
export SPEACHES_TTS_MODEL="${HARBOR_SPEACHES_TTS_MODEL:-speaches-ai/Kokoro-82M-v1.0-ONNX}"

# --- Harbor/Upstream Compatibility Environment Variables ---
export SPEACHES_HOST_PORT="${HARBOR_SPEACHES_HOST_PORT:-34331}"
export SPEACHES_VERSION="${HARBOR_SPEACHES_VERSION:-latest}"
export UVICORN_PORT="${HARBOR_SPEACHES_HOST_PORT}"
export UVICORN_HOST="${HARBOR_SPEACHES_HOST}"

# ONNX Runtime provider configuration (auto-detection recommended)
# Options: auto, CoreMLExecutionProvider, CUDAExecutionProvider, CPUExecutionProvider
export ONNX_PROVIDER="${HARBOR_SPEACHES_ONNX_PROVIDER:-auto}" # Default to auto-detect ONNX provider.
export OMP_NUM_THREADS="${HARBOR_SPEACHES_OMP_NUM_THREADS:-}" # Optional override for

# or Systran/faster-whisper-tiny.en if you are running on a CPU for a faster inference.
# or older Systran/faster-distil-whisper-large-v3
export SPEACHES_STT_MODEL="${HARBOR_SPEACHES_STT_MODEL:-deepdml/faster-distil-whisper-large-v3.5 }"
export TRANSCRIPTION_MODEL=SPEACHES_STT_MODEL

export SPEACHES_TTS_MODEL="${HARBOR_SPEACHES_TTS_MODEL:-hexgrad/Kokoro-82M}"
export SPEACHES_TTS_VOICE="${HARBOR_SPEACHES_TTS_VOICE:-af_bella}"
export ONNX_PROVIDER="${HARBOR_SPEACHES_ONNX_PROVIDER:-auto}"
export OMP_NUM_THREADS="${HARBOR_SPEACHES_OMP_NUM_THREADS:-}"
export SPEACHES_WORKSPACE="${HARBOR_SPEACHES_WORKSPACE:-./speaches/workspace}"
# Stop Gradio in Speaches from tracking usage data.
export DO_NOT_TRACK=1

# ==============================================================================
# --- Helper Functions ---
# ==============================================================================

log_info() { echo "$LOG_PREFIX INFO: $1" >&2; }
log_error() { echo "$LOG_PREFIX ERROR: $1" >&2; exit 1; }
command_exists() { command -v "$1" &>/dev/null; }

# ==============================================================================
# --- Main Execution ---
# This script follows a single, linear execution path. It first checks for a
# state file to perform a fast launch, otherwise it runs the full, idempotent
# setup process from scratch.
# ==============================================================================

log_info "--- Speaches Native Launcher Initializing ---"

if [[ $# -eq 0 ]]; then
    log_error "No command provided. This script is an entrypoint for Harbor and expects a command (e.g., 'serve')."
fi

# Create the workspace directory if it doesn't exist. This is safe to run every time.
mkdir -p "$HARBOR_SPEACHES_WORKSPACE"

# NOTE: the local speaches the user already installed will be run if the speaches command exists,
# it will skip the full setup to just run the command at the bottom

# if harbor speaches force setup is set or the command speaches does not exist, we will always run the full setup.
if [[ "$HARBOR_SPEACHES_FORCE_SETUP" == "true" ]] || ! command_exists speaches; then

# # If the state file exists, we can skip the lengthy setup process.
# if [[ -f "$STATE_FILE" ]]; then
#     log_info "Setup complete marker found. Skipping to runtime configuration."
# else
    # --- Full Setup Path (First Run or Forced) ---
    log_info "Performing full first-time setup into workspace: $HARBOR_SPEACHES_WORKSPACE"

    # Step 1: Check for System Dependencies
    log_info "[Step 1/6] Checking system dependencies (git, uv)..."
    # If brew exists, use it to install dependencies
    if command_exists brew; then
        log_info "Homebrew detected. Installing dependencies via brew..."
        brew install git uv onnxruntime uvicorn ffmpeg

        BREW_BIN_DIR="$(brew --prefix)/bin"
        if [[ ":$PATH:" != *":$BREW_BIN_DIR:"* ]]; then
            export PATH="$BREW_BIN_DIR:$PATH"
            log_info "Added Homebrew bin directory to PATH: $BREW_BIN_DIR"
        fi
    fi
    if ! command_exists git; then log_error "'git' command not found. Please install it."; exit 1; fi
    if ! command_exists uv; then log_error "'uv' command not found. Please install via 'pip install uv' or your package manager."; exit 1; fi

    # Step 2: Clone, Patch, and Install Speaches
    log_info "[Step 2/6] Installing Speaches Python package..."
    if [ ! -d "$REPO_DIR" ]; then
        log_info "Cloning speaches from branch '$SPEACHES_REPO_BRANCH'..."
        git clone --depth 1 -b "$SPEACHES_REPO_BRANCH" "$SPEACHES_REPO_URL" "$REPO_DIR"
    else
        log_info "Speaches repository found. Pulling latest changes..."
        (cd "$REPO_DIR" && git pull)
    fi

    cd "$REPO_DIR"

    # Step 3: Setup Virtual Environment
    log_info "[Step 3/6] Setting up virtual environment in '$VENV_DIR'..."
    if [[ ! -f "$VENV_DIR/bin/python" ]]; then
        if [[ -n "$HARBOR_PYTHON_VERSION" ]]; then
            log_info "Creating venv with Python version $HARBOR_PYTHON_VERSION via uv venv..."
            uv venv "$VENV_DIR" --python "python${HARBOR_PYTHON_VERSION}"
        else
            log_info "Creating venv with default Python via uv venv..."
            uv venv "$VENV_DIR"
        fi
    else
        log_info "Virtual environment already exists."
    fi
    # Source the venv to ensure correct environment for subsequent commands
    # shellcheck disable=SC1090
    source "$VENV_DIR/bin/activate"
    log_info "Using Python: $($VENV_DIR/bin/python --version)"

    # local pyproject_file="$REPO_DIR/pyproject.toml"
    # if grep -q 'requires-python = ">=3.12' "$pyproject_file"; then
    #     log_info "Patching 'requires-python' in '$pyproject_file' to allow older Python version..."
    #     sed -i.bak 's/requires-python = ">=3.12,<3.13"/requires-python = ">=3.10,<3.13"/' "$pyproject_file"
    # fi

    log_info "Syncing and upgrading dependencies via 'uv sync'..."
    # NOTE: You can do uv sync --upgrade to ensure latest packages but can occasionally introduce breaking changes. Removed because stability is preferred.
    "$VENV_DIR/bin/uv" sync --all-extras --python "$python_executable" -f "$REPO_DIR/pyproject.toml"

    log_info "Installing the 'speaches' command-line tool via 'uv tool install'..."
    "$VENV_DIR/bin/uv" tool install . --from "$REPO_DIR" --python "$python_executable"

    # Step 5: Pre-download Default Models
    log_info "[Step 5/6] Pre-downloading default models for faster first launch..."
    # This check is now more robust. It uses the tool itself to list available
    # models and greps the output, rather than relying on cache directory structure.
    if "$VENV_DIR/bin/speaches" model list | grep -q "$SPEACHES_STT_MODEL"; then
        log_info "STT model '$SPEACHES_STT_MODEL' already available."
    else
        log_info "Downloading STT model: '$SPEACHES_STT_MODEL'..."
        "$VENV_DIR/bin/speaches" model download "$SPEACHES_STT_MODEL"
    fi
    if "$VENV_DIR/bin/speaches" model list | grep -q "$SPEACHES_TTS_MODEL"; then
        log_info "TTS model '$SPEACHES_TTS_MODEL' already available."
    else
        log_info "Downloading TTS model: '$SPEACHES_TTS_MODEL'..."
        "$VENV_DIR/bin/speaches" model download "$SPEACHES_TTS_MODEL"
    fi

    # Step 6: Create the state file to enable the fast path for next time.
    log_info "[Step 6/6] Full setup successful. Creating state file."
    touch "$STATE_FILE"
fi

# # --- Runtime Setup (runs every time) ---
# log_info "Configuring runtime environment..."
# # Setup ONNX for GPU or CPU, respecting user overrides.
# if [[ -z "${ONNX_PROVIDER:-}" ]]; then
#     if [[ "$(uname)" == "Darwin" ]] && [[ "$(uname -m)" == "arm64" ]]; then
#         export ONNX_PROVIDER="CoreMLExecutionProvider,CPUExecutionProvider"
#     elif command_exists nvidia-smi; then
#         export ONNX_PROVIDER="CUDAExecutionProvider,CPUExecutionProvider"
#     else
#         export ONNX_PROVIDER="CPUExecutionProvider"
#     fi
#     log_info "Auto-configured ONNX_PROVIDER to: $ONNX_PROVIDER"
# fi

# --- Final Process Handoff ---
# The `exec` command is the final and most critical step. It replaces the
# current bash script process with the command specified by Harbor.
#
# How it works with speaches_native.yml and the new `speaches serve` command:
# 1. Harbor's `daemon_args` will be defined to use the new API:
#    daemon_args: ["serve", "--host", "0.0.0.0", "--port", "${HARBOR_SPEACHES_HOST_PORT:-34331}"]
# 2. Harbor calls this script with those args:
#    `./speaches_native.sh serve --host 0.0.0.0 --port 34331`
# 3. This script sets up the environment and then calls `exec` with all arguments it received ("$@").
#    The `exec` line becomes:
#    `exec .../workspace/venv/bin/speaches serve --host 0.0.0.0 --port 34331`
#
# This launches the uvicorn server via the `speaches` tool, and ensures
# Harbor directly manages the final service process for clean shutdowns.
log_info "Speaches setup complete. Handing off to command: speaches $@"

# include the url of the pull request, and up:
# https://github.com/speaches-ai/speaches/pull/449

# # main repository
# # git clone https://github.com/speaches-ai/speaches.git
# # easier to user branch
# git clone -b cli-simplified-locked https://github.com/ahundt/speaches.git
# cd speaches
# uv venv
# source .venv/bin/activate
# uv sync --all-extras --upgrade
# uv tool install .

# # Downloading a Text To Speech (TTS) model:
# uvx speaches model download speaches-ai/Kokoro-82M-v1.0-ONNX

# # Downloading a Speech To Text (STT) model:
# uvx speaches model download Systran/faster-distil-whisper-small.en

# # run the speaches server then open http://localhost:8000 in your web browser to try speaches
# speaches serve --host 0.0.0.0 --port 8000

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    log_info "Activating virtual environment: $VENV_DIR"
    cd "$HARBOR_SPEACHES_WORKSPACE"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
fi

 exec "$@"


# https://aistudio.google.com/app/prompts?state=%7B%22ids%22:%5B%221SrK-h2XlgJj0jOyMKSlWKOH8_k6Ikucp%22%5D,%22action%22:%22open%22,%22userId%22:%22113401184214553951890%22,%22resourceKeys%22:%7B%7D%7D&usp=sharing
# continue your process and your wait process, I want to iterate on sub-variations on variation 1, I would like to support brew whenever it is available which can include, I also believe that by integrating a more robust version of the following we can
# brew install uv onnxruntime uvicorn ffmpeg
# # uv init --python=3.12
# uv init
# uv sync --all-extras --upgrade
# uvx speaches-cli model download ${HARBOR_SPEACHES_STT_MODEL:-Systran/faster-distil-whisper-small.en}
# uvx speaches-cli model download ${HARBOR_SPEACHES_TTS_MODEL:-speaches-ai/Kokoro-82M-v1.0-)

# export ENABLE_UI=TRUE && uvicorn --factory --host 0.0.0.0 speaches.main:create_app