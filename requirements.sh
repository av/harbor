#!/bin/bash

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if command -v $1 &> /dev/null; then
        return 0
    else
        return 1
    fi
}

install_basic_tools() {
    log_info "Updating package lists..."
    sudo apt-get update || {
        log_error "Failed to update package lists"
        return 1
    }

    for tool in git curl; do
        if check_command $tool; then
            log_warn "$tool is already installed"
        else
            log_info "Installing $tool..."
            sudo apt-get install -y $tool || {
                log_error "Failed to install $tool"
                return 1
            }
        fi
    done
}

install_docker() {
    if check_command docker && check_command "docker compose"; then
        log_warn "Docker and Docker Compose are already installed"
        return 0
    fi

    log_info "Installing Docker using convenience script..."
    curl -fsSL https://get.docker.com | sudo sh || {
        log_error "Failed to install Docker"
        return 1
    }

    log_info "Adding current user to docker group..."
    sudo usermod -aG docker $USER || {
        log_error "Failed to add user to docker group"
        return 1
    }
}

install_nvidia_container_toolkit() {
    if ! command -v nvidia-smi &> /dev/null; then
        log_warn "NVIDIA GPU not detected, skipping Container Toolkit installation"
        return 0
    fi

    if curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | \
       grep -q "BEGIN PGP PUBLIC KEY BLOCK"; then
        log_info "Installing NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
            sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && \
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list && \
        sudo apt-get update && \
        sudo apt-get install -y nvidia-container-toolkit && \
        sudo nvidia-ctk runtime configure --runtime=docker && \
        sudo systemctl restart docker || {
            log_error "Failed to install NVIDIA Container Toolkit"
            return 1
        }
    else
        log_error "Failed to verify NVIDIA GPG key"
        return 1
    fi
}

verify_installations() {
    log_info "Verifying installations..."

    local tools=("git" "curl" "docker")
    for tool in "${tools[@]}"; do
        if check_command $tool; then
            log_info "$tool version: $($tool --version | head -n1)"
        else
            log_error "$tool is not installed properly"
        fi
    done

    if check_command "docker compose"; then
        log_info "Docker Compose version: $(docker compose version)"
    else
        log_error "Docker Compose is not installed properly"
    fi

    if command -v nvidia-smi &> /dev/null; then
        if docker run --rm --gpus all ubuntu:22.04 nvidia-smi &> /dev/null; then
            log_info "NVIDIA Container Toolkit is working properly"
        else
            log_error "NVIDIA Container Toolkit is not working properly"
        fi
    fi
}

main() {
    log_info "Starting installation process..."

    install_basic_tools || exit 1
    install_docker || exit 1
    install_nvidia_container_toolkit || exit 1
    verify_installations

    log_info "Installation complete! Please log out and log back in for docker group changes to take effect."
}

main
