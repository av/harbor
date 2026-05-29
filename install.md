# Harbor

> Containerized local LLM toolkit with a CLI and companion app for running Docker Compose based AI services.

I want you to install Harbor for me. Execute the steps below autonomously, but do not make destructive changes to an existing Harbor installation.

OBJECTIVE: Orchestrate Harbor CLI installation by running Harbor's installer script, then verify it works.

DONE WHEN: `harbor --version` prints a version string and `harbor doctor` completes without required dependency failures.

## Use With Agents

```bash
# With Claude Code
curl -fsSL https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.md | claude

# With Codex
codex "$(curl -fsSL https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.md)"
```

## TODO

- [ ] Detect the operating system and shell environment
- [ ] Decide whether Harbor's installer should also install optional system requirements
- [ ] Run `install.sh` (dependencies are installed by default; pass `--skip-requirements` only if the user explicitly asks to skip)
- [ ] Refresh shell or Docker group membership if the installer asks for it
- [ ] Verify `harbor --version` and `harbor doctor`
- [ ] Optionally configure GPU container support when NVIDIA or AMD hardware is present

## Scope

Your job is to orchestrate installation, not reimplement it. The actual Harbor install/update must be delegated to `install.sh`, which resolves the latest release, installs or updates `~/.harbor`, and links the CLI.

Do not manually clone Harbor, check out tags, or run `./harbor.sh ln` as the primary installation path. Use manual repair steps only when the installer fails and the failure clearly calls for them.

Use these canonical locations and URLs:

```bash
HARBOR_INSTALL_PATH="$HOME/.harbor"
HARBOR_INSTALL_URL="https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh"
HARBOR_REQUIREMENTS_URL="https://raw.githubusercontent.com/av/harbor/refs/heads/main/requirements.sh"
```

## Run Installer

Run:

```bash
curl -fsSL "$HARBOR_INSTALL_URL" | bash
```

The installer installs dependencies by default. To skip dependency installation (only when all prerequisites are confirmed present), run:

```bash
curl -fsSL "$HARBOR_INSTALL_URL" | bash -s -- --skip-requirements
```

The installer is expected to:

- install system dependencies (git, curl, Docker, Docker Compose) via the platform's package manager
- install or update Harbor in `~/.harbor`
- resolve the latest GitHub release tag
- check out that release
- link the `harbor` command into the user's PATH

Then continue with [Verify](#verify).

## Detect Platform

Run:

```bash
uname -s
uname -m
printf 'SHELL=%s\n' "${SHELL:-unknown}"
```

Supported environments:

| Environment | Notes |
|---|---|
| Linux | Native Linux with Docker Engine and Docker Compose plugin |
| macOS | Docker Desktop is expected for Docker daemon and Compose |
| Windows | Run installation inside WSL2, not PowerShell or cmd.exe |

If this is Windows without WSL2, stop and tell the user to install and enter WSL2 first.

## Dependency Orchestration

Harbor's installer runs the requirements installer by default. The requirements installer installs or checks Git, curl, Docker, Docker Compose v2, and Docker access. It supports macOS with Homebrew and Linux distributions using apt, dnf, pacman, or apk.

Prefer `install.sh` (which runs requirements automatically) over calling `requirements.sh` directly. Call `requirements.sh` directly only when diagnosing a dependency failure separately from Harbor installation:

```bash
curl -fsSL "$HARBOR_REQUIREMENTS_URL" | bash
```

The requirements installer may use `sudo`, start or enable the Docker service on Linux, and add the user to the `docker` group. If it adds group membership, tell the user they may need to log out and back in, or run:

```bash
newgrp docker
```

Then continue in the refreshed shell and run:

```bash
docker info
```

## Optional Preflight Checks

These checks are optional since the installer handles dependencies by default. If a required dependency is missing and you skipped requirements, rerun the installer without `--skip-requirements`.

```bash
git --version
curl --version
docker --version
docker compose version
docker info
```

Docker Compose must be v2.23.1 or newer. If Docker is installed but `docker info` fails:

- On Linux, start Docker with `sudo systemctl start docker` when systemd is available.
- On macOS, start Docker Desktop.
- On WSL2, start Docker Desktop on Windows and enable WSL integration for the distro.
- If Docker reports permission denied on Linux, add the user to the `docker` group, then refresh the login session.

If the installer succeeds but the current shell still cannot find `harbor`, export PATH for this session and retry verification:

```bash
export PATH="$PATH:$HOME/.local/bin"
```

## Verify

Run:

```bash
harbor --version
harbor doctor
```

If `harbor --version` prints a version string and `harbor doctor` has no required dependency failures, Harbor CLI installation is complete.

If `harbor doctor` only warns about missing NVIDIA or AMD GPU support on a CPU-only machine, installation is still complete.

## Optional GPU Support

Configure GPU container support only when matching GPU hardware is present or the user explicitly asks for it.

### NVIDIA

Check:

```bash
nvidia-smi
```

If NVIDIA hardware is available, install NVIDIA Container Toolkit using the platform's current package instructions, then restart Docker. On Ubuntu or Debian, the general flow is:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
distribution=$(. /etc/os-release; echo "$ID$VERSION_ID")
curl -s -L "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
harbor doctor
```

### AMD ROCm

Check:

```bash
ls -l /dev/kfd /dev/dri 2>/dev/null
```

If AMD GPU devices are available, install AMD Container Toolkit and configure the Docker runtime. On Ubuntu 22.04 or 24.04, the general flow is:

```bash
wget https://repo.radeon.com/rocm/rocm.gpg.key -O - | \
  gpg --dearmor | sudo tee /etc/apt/keyrings/rocm.gpg >/dev/null
source /etc/os-release
echo "deb [signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/amd-container-toolkit/apt/ $VERSION_CODENAME main" | \
  sudo tee /etc/apt/sources.list.d/amd-container-toolkit.list
sudo apt-get update
sudo apt-get install -y amd-container-toolkit
sudo amd-ctk runtime configure
sudo systemctl restart docker
sudo usermod -aG render,video "$USER"
```

Verify after refreshing group membership:

```bash
docker run --rm --runtime=amd -e AMD_VISIBLE_DEVICES=all ubuntu ls -l /dev/dri
harbor doctor
```

## First Use

Start the default Harbor stack:

```bash
harbor up
harbor open
```

First startup downloads Docker images and can take several minutes. Open WebUI will ask the user to create a local admin account on first launch.

EXECUTE NOW: Complete the TODO list until `harbor --version` works and `harbor doctor` has no required dependency failures.
