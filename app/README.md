# Harbor App

Companion app for Harbor.

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
