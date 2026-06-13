# Harbor App

Companion app for Harbor.

## First-run setup

Install a Harbor App package for your platform, then launch the app. On first
run the app checks whether the Harbor CLI is installed and reachable. If not, the
setup screen runs the official Harbor installer (`install.sh` on Linux/macOS,
`install.ps1` on Windows) with live terminal output. After setup reports
**ready**, start services from the app Home screen or with `harbor up`.

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

### Native setup validation

First-run guided setup is validated manually through the app UI on real hosts.
The detailed host scenarios live in `../tests/app-native-setup.md`.
