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

# Handle optional executable parameter
# If no arguments provided, default to starting the service manager
if [[ $# -eq 0 ]]; then
    echo "INFO: No command provided, defaulting to Speaches service manager" >&2
    EXECUTABLE="harbor-speaches-server"
    ARGS=()
else
    # Extract the executable name and arguments
    EXECUTABLE="$1"
    shift
    ARGS=("$@")
fi

# Function to check if a command exists
command_exists() {
    command -v "$1" &>/dev/null
}

# Function to check if a Python module is available
python_module_exists() {
    python -c "import $1" &>/dev/null 2>&1
}

# Function to detect conda environments with speaches
find_conda_speaches_env() {
    if command_exists conda; then
        # Look for conda environments that might have speaches
        conda env list 2>/dev/null | grep -E "(speaches|speech)" | head -n1 | awk '{print $1}' || true
    fi
}

# Function to setup ONNX Runtime providers using our Python utilities
setup_onnx_providers() {
    echo "INFO: Setting up ONNX Runtime providers for optimal performance..." >&2

    # Try to use our Python ONNX utilities for better detection
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local onnx_utils="$script_dir/onnx_utils.py"

    if [[ -f "$onnx_utils" && $(command_exists python) ]]; then
        echo "INFO: Using advanced ONNX provider detection..." >&2

        # Try to run our ONNX utils for provider setup
        if eval "$(python "$onnx_utils" --setup 2>/dev/null)"; then
            echo "INFO: ONNX providers configured via Python utilities" >&2
            return 0
        else
            echo "WARN: Python ONNX utils failed, falling back to basic detection" >&2
        fi
    fi

    # Fallback to basic platform detection
    echo "INFO: Using basic ONNX provider detection..." >&2
    local platform=$(uname)

    # Set default CPU thread count if not already set
    if [[ -z "${OMP_NUM_THREADS:-}" ]]; then
        local cpu_cores
        if command_exists nproc; then
            cpu_cores=$(nproc)
        elif [[ "$platform" == "Darwin" ]]; then
            cpu_cores=$(sysctl -n hw.ncpu)
        else
            cpu_cores=4  # Safe fallback
        fi
        export OMP_NUM_THREADS="$cpu_cores"
        echo "INFO: Set OMP_NUM_THREADS=$cpu_cores" >&2
    fi

    # Basic platform-specific provider fallback
    case "$platform" in
        "Darwin")
            # macOS: Prefer CoreML for Apple Silicon, CPU for Intel
            if [[ "$(uname -m)" == "arm64" ]]; then
                echo "INFO: Apple Silicon detected - enabling CoreML acceleration" >&2
                # Let ONNX Runtime auto-detect, but hint towards CoreML
                export ONNX_PROVIDER="${ONNX_PROVIDER:-CoreMLExecutionProvider,CPUExecutionProvider}"
            else
                echo "INFO: Intel Mac detected - using CPU execution" >&2
                export ONNX_PROVIDER="${ONNX_PROVIDER:-CPUExecutionProvider}"
            fi
            ;;
        "Linux")
            # Linux: Check for NVIDIA GPU support
            if command_exists nvidia-smi && nvidia-smi &>/dev/null; then
                echo "INFO: NVIDIA GPU detected - enabling CUDA acceleration" >&2
                export ONNX_PROVIDER="${ONNX_PROVIDER:-CUDAExecutionProvider,CPUExecutionProvider}"
                # Ensure CUDA device visibility is preserved
                export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
            else
                echo "INFO: No NVIDIA GPU detected - using CPU execution" >&2
                export ONNX_PROVIDER="${ONNX_PROVIDER:-CPUExecutionProvider}"
            fi
            ;;
        *)
            # Other platforms (Windows via WSL, etc): Default to CPU
            echo "INFO: Platform $platform - using CPU execution" >&2
            export ONNX_PROVIDER="${ONNX_PROVIDER:-CPUExecutionProvider}"
            ;;
    esac

    echo "INFO: ONNX_PROVIDER set to: $ONNX_PROVIDER" >&2
}

# Function to check Python version compatibility
check_python_version() {
    local python_cmd="$1"
    if ! command_exists "$python_cmd"; then
        return 1
    fi

    # Speaches requires Python 3.12+ but <3.13
    local version
    version=$("$python_cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")

    if [[ "$version" == "3.12" ]]; then
        return 0
    else
        echo "INFO: Python version $version found with $python_cmd (Speaches requires Python 3.12.x)" >&2
        return 1
    fi
}

# Function to detect platform capabilities
detect_platform_capabilities() {
    local platform=$(uname)

    case "$platform" in
        "Linux")
            echo "INFO: Linux detected - full TTS/STT capabilities available" >&2
            export PLATFORM_SUPPORTS_TTS="true"
            ;;
        "Darwin")
            echo "WARN: macOS detected - TTS features may be limited (piper-tts is Linux-only)" >&2
            export PLATFORM_SUPPORTS_TTS="false"
            ;;
        *)
            echo "WARN: Platform $platform - TTS features may be limited" >&2
            export PLATFORM_SUPPORTS_TTS="false"
            ;;
    esac
}

# Function to install uv package manager if needed
ensure_uv_available() {
    if command_exists uv; then
        echo "INFO: uv package manager found: $(command -v uv)" >&2
        return 0
    fi

    echo "INFO: Installing uv package manager (recommended for Speaches)..." >&2

    # Method 1: Try Homebrew first (preferred on macOS)
    if command_exists brew; then
        echo "INFO: Installing uv via Homebrew..." >&2
        if brew install uv; then
            echo "INFO: uv installed successfully via Homebrew" >&2
            return 0
        else
            echo "WARN: Homebrew installation failed, trying other methods..." >&2
        fi
    fi

    # Method 2: Try the official installer via curl
    if command_exists curl; then
        echo "INFO: Installing uv via official installer..." >&2
        if curl -LsSf https://astral.sh/uv/install.sh | sh; then
            # Update PATH to include cargo bin directory
            export PATH="$HOME/.cargo/bin:$PATH"
            # Also try common alternative locations
            for uv_path in "$HOME/.cargo/bin/uv" "$HOME/.local/bin/uv"; do
                if [ -x "$uv_path" ]; then
                    export PATH="$(dirname "$uv_path"):$PATH"
                    break
                fi
            done

            if command_exists uv; then
                echo "INFO: uv installed successfully via official installer" >&2
                return 0
            fi
        else
            echo "WARN: Official installer failed, trying pip..." >&2
        fi
    fi

    # Method 3: Fallback to pip install
    if command_exists pip; then
        echo "INFO: Installing uv via pip (fallback method)..." >&2
        if pip install uv; then
            echo "INFO: uv installed via pip" >&2
            return 0
        else
            echo "WARN: pip installation also failed" >&2
        fi
    fi

    echo "ERROR: Could not install uv using any method." >&2
    echo "       Please install uv manually:" >&2
    echo "       - macOS: brew install uv" >&2
    echo "       - Other: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "       - Fallback: pip install uv" >&2
    echo "       Then retry this script." >&2
    return 1
}

# Function to attempt Speaches installation
install_speaches() {
    echo "INFO: Attempting to install Speaches..." >&2

    # Detect platform capabilities first
    detect_platform_capabilities

    # Find compatible Python version
    local python_cmd=""
    for py_candidate in python3.12 python3 python; do
        if check_python_version "$py_candidate"; then
            python_cmd="$py_candidate"
            echo "INFO: Using Python: $python_cmd (version $(${python_cmd} --version))" >&2
            break
        fi
    done

    if [[ -z "$python_cmd" ]]; then
        echo "ERROR: No compatible Python version found. Speaches requires Python 3.12.x" >&2
        show_python_installation_help
        return 1
    fi

    # Try uv-based installation first (official recommendation)
    if ensure_uv_available; then
        echo "INFO: Installing Speaches using uv (official method)..." >&2
        if install_with_uv "$python_cmd"; then
            return 0
        fi
        echo "WARN: uv installation failed, trying pip fallback..." >&2
    fi

    # Fallback to pip installation
    echo "INFO: Installing Speaches using pip..." >&2
    if install_with_pip "$python_cmd"; then
        return 0
    fi

    echo "ERROR: All installation methods failed" >&2
    return 1
}

# Function to try uv pip install speaches[server] in a temp venv
try_uv_pip_install() {
    local python_cmd="$1"
    local temp_dir="${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches-uv-pip-tmp"
    mkdir -p "$temp_dir"
    cd "$temp_dir" || return 1

    # Create a uv venv
    if ! uv venv --python "$python_cmd"; then
        echo "WARN: Failed to create uv venv for pip install" >&2
        return 1
    fi

    # Try to install speaches[server] via uv pip
    if .venv/bin/uv pip install 'speaches[server]'; then
        echo "INFO: Successfully installed speaches[server] via uv pip" >&2
        # Symlink for easier discovery
        ln -sf "$temp_dir/.venv" "${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches/.venv" 2>/dev/null || true
        export SPEACHES_VENV_PATH="$temp_dir/.venv"
        return 0
    else
        echo "WARN: uv pip install speaches[server] failed, will try local repo clone" >&2
        return 1
    fi
}

# Function to install with uv (official method)
install_with_uv() {
    local python_cmd="$1"

    # Try uv pip install first
    if try_uv_pip_install "$python_cmd"; then
        return 0
    fi

    # Create a temporary directory for installation
    local install_dir="${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches-install"
    mkdir -p "$install_dir"
    cd "$install_dir" || return 1

    # Clone the repository if not exists
    if [[ ! -d "speaches" ]]; then
        echo "INFO: Cloning Speaches repository..." >&2
        if ! git clone https://github.com/speaches-ai/speaches.git; then
            echo "ERROR: Failed to clone Speaches repository" >&2
            return 1
        fi
    fi

    cd speaches || return 1

    # Patch pyproject.toml for Python 3.10 compatibility
    patch_speaches_pyproject_python_version

    # Create virtual environment
    echo "INFO: Creating virtual environment with uv..." >&2
    if ! uv venv --python "$python_cmd"; then
        echo "ERROR: Failed to create virtual environment with uv" >&2
        return 1
    fi

    # Install dependencies
    echo "INFO: Installing dependencies..." >&2
    local sync_args="--all-extras"

    # On non-Linux platforms, try to skip Linux-only dependencies
    if [[ "$PLATFORM_SUPPORTS_TTS" == "false" ]]; then
        echo "INFO: Platform doesn't support full TTS - attempting minimal installation..." >&2
        # Try to install without all extras to skip Linux-only dependencies
        sync_args=""
    fi

    if ! uv sync $sync_args; then
        echo "ERROR: Failed to install dependencies with uv" >&2
        return 1
    fi

    # Test the installation
    if .venv/bin/python -c "import speaches; print('Speaches installed successfully')" 2>/dev/null; then
        echo "INFO: Speaches installation verified" >&2
        # Export the path to the virtual environment for later use
        export SPEACHES_VENV_PATH="$install_dir/speaches/.venv"

        # Also create a symlink for easier discovery
        ln -sf "$install_dir/speaches/.venv" "${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches/.venv" 2>/dev/null || true

        return 0
    else
        echo "ERROR: Speaches installation verification failed" >&2
        return 1
    fi
}

# Function to install with pip (fallback method)
install_with_pip() {
    local python_cmd="$1"

    echo "INFO: Attempting pip installation of Speaches..." >&2

    # Create a virtual environment
    local venv_dir="${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches-venv"
    echo "INFO: Creating virtual environment at $venv_dir..." >&2

    if ! "$python_cmd" -m venv "$venv_dir"; then
        echo "ERROR: Failed to create virtual environment" >&2
        return 1
    fi

    # Activate virtual environment and install
    local pip_cmd="$venv_dir/bin/pip"
    local python_venv="$venv_dir/bin/python"

    echo "INFO: Upgrading pip..." >&2
    if ! "$pip_cmd" install --upgrade pip; then
        echo "ERROR: Failed to upgrade pip" >&2
        return 1
    fi

    # Install speaches with platform-appropriate dependencies
    echo "INFO: Installing Speaches..." >&2
    local install_cmd="speaches"

    # On non-Linux platforms, we might need to install without certain extras
    if [[ "$PLATFORM_SUPPORTS_TTS" == "false" ]]; then
        echo "INFO: Installing minimal version for non-Linux platform..." >&2
        # Just install basic speaches - may not work but worth trying
    fi

    if ! "$pip_cmd" install "$install_cmd"; then
        echo "ERROR: Failed to install Speaches with pip" >&2
        return 1
    fi

    # Test the installation
    if "$python_venv" -c "import speaches; print('Speaches installed successfully')" 2>/dev/null; then
        echo "INFO: Speaches installation verified" >&2
        export SPEACHES_VENV_PATH="$venv_dir"
        return 0
    else
        echo "ERROR: Speaches installation verification failed" >&2
        return 1
    fi
}

# Function to provide Python installation guidance
show_python_installation_help() {
    echo "=== Python 3.12 Installation Help ===" >&2
    echo "Speaches requires Python 3.12.x (not 3.13+)" >&2
    echo "" >&2

    local platform=$(uname)
    case "$platform" in
        "Darwin")
            echo "On macOS, install Python 3.12 using:" >&2
            echo "  brew install python@3.12" >&2
            echo "  # Or use pyenv:" >&2
            echo "  pyenv install 3.12.8" >&2
            echo "  pyenv global 3.12.8" >&2
            ;;
        "Linux")
            echo "On Linux, install Python 3.12 using:" >&2
            echo "  # Ubuntu/Debian:" >&2
            echo "  sudo apt update && sudo apt install python3.12 python3.12-venv python3.12-dev" >&2
            echo "  # Or use pyenv:" >&2
            echo "  pyenv install 3.12.8" >&2
            echo "  pyenv global 3.12.8" >&2
            ;;
        *)
            echo "Install Python 3.12 for your platform and try again." >&2
            ;;
    esac
    echo "" >&2
}

# Function to provide installation guidance
show_installation_help() {
    echo "=== Speaches Installation Help ===" >&2
    echo "Speaches was not found in any supported installation method." >&2
    echo "" >&2

    # Check if this is a platform issue
    local platform=$(uname)
    if [[ "$platform" != "Linux" ]]; then
        echo "⚠️  NOTE: You are running on $platform. Speaches has some Linux-only TTS features." >&2
        echo "   Consider using Docker for full compatibility:" >&2
        echo "   harbor up speaches  # Uses containerized version" >&2
        echo "" >&2
    fi

    echo "For native installation, try:" >&2
    echo "" >&2
    echo "1. Auto-install (recommended):" >&2
    echo "   # This script can attempt installation - run Harbor again" >&2
    echo "   # and it will try to install Speaches automatically" >&2
    echo "" >&2
    echo "2. Manual installation with uv (official method):" >&2
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "   git clone https://github.com/speaches-ai/speaches.git" >&2
    echo "   cd speaches" >&2
    echo "   uv venv --python 3.12" >&2
    echo "   uv sync --all-extras" >&2
    echo "" >&2
    echo "3. Manual installation with pip:" >&2
    echo "   python3.12 -m venv speaches-env" >&2
    echo "   source speaches-env/bin/activate" >&2
    echo "   pip install speaches" >&2
    echo "" >&2
    echo "After installation, verify with:" >&2
    echo "   python -c 'import speaches; print(speaches.__version__)'" >&2
    echo "" >&2

    show_python_installation_help
}

# Function to patch requires-python in pyproject.toml for local speaches install
patch_speaches_pyproject_python_version() {
    local speaches_dir="$(dirname "$0")"/speaches
    local pyproject_file="$speaches_dir/pyproject.toml"
    if [[ ! -f "$pyproject_file" ]]; then
        echo "WARN: speaches/pyproject.toml not found at $pyproject_file" >&2
        return 1
    fi
    echo "INFO: Patching requires-python in $pyproject_file to allow Python 3.10..." >&2
    # Use sed to replace any >=3.12,<3.13 or >=3.12 with >=3.10,<3.13, but only if needed
    if grep -qE '^requires-python\s*=\s*"[^"]*3.12' "$pyproject_file"; then
        sed -i '' -E 's|^(requires-python\s*=\s*")[^"]*3.12[^"]*(")|\1>=3.10,<3.13\2|' "$pyproject_file"
        echo "INFO: requires-python patched to '>=3.10,<3.13'" >&2
        # Uncomment to commit the change if in a git repo
        # (cd "$speaches_dir" && git add pyproject.toml && git commit -m "Allow Python 3.10 in requires-python")
    else
        echo "INFO: No requires-python >=3.12 found, no patch needed." >&2
    fi
}

# Detection and execution logic
echo "INFO: Detecting Speaches installation method..." >&2

# Setup ONNX Runtime providers for optimal performance
setup_onnx_providers

# Try to use service manager for enhanced initialization
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/speaches_service_manager.py" ]]; then
    echo "INFO: Using Speaches service manager for initialization..." >&2

    # Try to find Python and run service manager
    for python_cmd in python3.12 python3 python; do
        if command_exists "$python_cmd"; then
            if "$python_cmd" "$SCRIPT_DIR/speaches_service_manager.py" --init 2>/dev/null; then
                echo "INFO: Service environment initialized via service manager" >&2
                break
            else
                echo "INFO: Service manager initialization failed, continuing with basic setup" >&2
            fi
        fi
    done
fi

# === UVV-FIRST APPROACH: Priority detection order ===
# 1. Check for Harbor's own uv-managed environments (HIGHEST PRIORITY)
# 2. Check for local project uv environments
# 3. Check for system binaries installed by uv
# 4. Fallback to traditional detection methods

# Method 1: Check for Harbor-managed uv environments (PRIORITY)
echo "INFO: Checking for uv-managed Speaches installations..." >&2
for uv_location in \
    "${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches-install/speaches/.venv" \
    "${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches/.venv" \
    "$HOME/.local/share/uv/speaches/.venv" \
    "$(pwd)/speaches/.venv" \
    "$(pwd)/.venv"; do

    if [[ -f "$uv_location/bin/python" ]]; then
        # Test if harbor-speaches command is available in this environment
        if [[ -f "$uv_location/bin/harbor-speaches" ]]; then
            echo "INFO: Found Harbor Speaches in uv environment: $uv_location" >&2
            echo "INFO: Executing via uv binary: $uv_location/bin/harbor-speaches ${ARGS[*]}" >&2
            exec "$uv_location/bin/harbor-speaches" "${ARGS[@]}"
        # Test if speaches module is available
        elif "$uv_location/bin/python" -c "import speaches" 2>/dev/null; then
            echo "INFO: Found Speaches module in uv environment: $uv_location" >&2
            # Check if this is a server start command - use service manager
            if [[ "${ARGS[*]}" == *"--server"* || "${ARGS[*]}" == *"--host"* ]]; then
                echo "INFO: Starting server via service manager" >&2
                exec "$uv_location/bin/python" "$SCRIPT_DIR/speaches_service_manager.py" --server "${ARGS[@]}"
            else
                echo "INFO: Executing via uv Python module: $uv_location/bin/python -m speaches ${ARGS[*]}" >&2
                exec "$uv_location/bin/python" -m speaches "${ARGS[@]}"
            fi
        fi
    fi
done

# Method 2: Check for system-wide uv installations
if command_exists uv; then
    echo "INFO: uv found, checking for global installations..." >&2

    # Check if harbor-speaches is available globally via uv
    if command_exists "harbor-speaches"; then
        echo "INFO: Found harbor-speaches system binary via uv" >&2
        echo "INFO: Executing: harbor-speaches ${ARGS[*]}" >&2
        exec harbor-speaches "${ARGS[@]}"
    fi
fi

# Method 3: Check for system binary (could be installed by uv or other methods)
if command_exists "$EXECUTABLE"; then
    echo "INFO: Found Speaches system binary: $(command -v "$EXECUTABLE")" >&2
    echo "INFO: Executing: $EXECUTABLE ${ARGS[*]}" >&2
    exec "$EXECUTABLE" "${ARGS[@]}"

# Method 3: Check for Python module in current environment
elif command_exists python && python_module_exists speaches; then
    echo "INFO: Found Speaches Python module in current environment" >&2
    echo "INFO: Executing: python -m speaches ${ARGS[*]}" >&2
    exec python -m speaches "${ARGS[@]}"

# Method 4: Check for Harbor-managed pip installations
elif [[ -f "${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches-venv/bin/python" ]]; then
    local venv_python="${HARBOR_HF_CACHE:-$HOME/.cache/harbor}/speaches-venv/bin/python"
    echo "INFO: Found Speaches in Harbor-managed pip installation" >&2
    echo "INFO: Executing: $venv_python -m speaches ${ARGS[*]}" >&2
    exec "$venv_python" -m speaches "${ARGS[@]}"

# Method 5: Check for conda environment
elif command_exists conda; then
    CONDA_ENV=$(find_conda_speaches_env)
    if [[ -n "$CONDA_ENV" ]]; then
        echo "INFO: Found Speaches in conda environment: $CONDA_ENV" >&2
        echo "INFO: Executing: conda run -n $CONDA_ENV python -m speaches ${ARGS[*]}" >&2
        exec conda run -n "$CONDA_ENV" python -m speaches "${ARGS[@]}"
    fi
fi

# Method 6: Try alternative Python executables with compatible versions
for python_cmd in python3.12 python3 python; do
    if check_python_version "$python_cmd" 2>/dev/null && "$python_cmd" -c "import speaches" &>/dev/null; then
        echo "INFO: Found Speaches with $python_cmd" >&2
        echo "INFO: Executing: $python_cmd -m speaches ${ARGS[*]}" >&2
        exec "$python_cmd" -m speaches "${ARGS[@]}"
    fi
done

# If we get here, Speaches is not installed - attempt installation
echo "INFO: Speaches not found. Attempting automatic installation..." >&2

if install_speaches; then
    echo "INFO: Installation successful! Retrying execution..." >&2

    # Retry execution after successful installation
    if [[ -n "${SPEACHES_VENV_PATH:-}" ]] && [[ -f "${SPEACHES_VENV_PATH}/bin/python" ]]; then
        echo "INFO: Executing newly installed Speaches: ${SPEACHES_VENV_PATH}/bin/python -m speaches ${ARGS[*]}" >&2
        exec "${SPEACHES_VENV_PATH}/bin/python" -m speaches "${ARGS[@]}"
    fi
fi

# If installation failed or execution still doesn't work
echo "ERROR: Speaches installation failed or is not accessible." >&2
echo "" >&2
show_installation_help
exit 1
