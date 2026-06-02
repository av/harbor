# Harbor App

Companion app for Harbor.

## First-run setup

Install a Harbor App package for your platform, then launch the app. On first
run the app checks the Harbor CLI, Docker readiness, and the fixed first-run
stack. If Harbor is not ready, the setup screen runs the official Harbor
installer and then configures Open WebUI plus llama.cpp with a small CPU-viable
model.

Linux and macOS setup uses:

```bash
curl -fsSL https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh | bash
```

Windows setup installs Harbor inside WSL2 through `install.ps1`; Harbor commands
continue to run through WSL from the app.

## Development

This project uses [bun](https://github.com/oven-sh/bun#install) package manager.

### Tauri System Dependencies

This project uses Tauri and requires the following system dependencies:

1. [System Dependencies](https://tauri.app/start/prerequisites/#system-dependencies)
2. [Rust](https://tauri.app/start/prerequisites/#rust)

### Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/)
  - [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode)
  - [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)

### Start the development server

```bash
# Change to the app directory
cd ./app

# Install dependencies
bun install

# Run the app in development mode
bun tauri dev
```

### Build

```bash
# For the current targets
bun tauri build
```

### Native setup smoke

Native setup validation can run the app's Tauri setup backend directly from the
app process:

```bash
HARBOR_APP_SETUP_SMOKE=1 \
HARBOR_APP_SETUP_SMOKE_OUTPUT="$PWD/harbor-app-setup.json" \
./path/to/Harbor
```

The process exits `0` when setup reaches `ready`, exits non-zero on setup
failure, and writes JSON with `ok`, `detail`, and `error` fields. The detailed
host scenarios live in `../tests/app-native-setup.md`.
