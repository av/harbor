# Harbor App Native Setup Integration Tests

These are manual UI-driven scenarios for the app's guided first-run setup
(`app/src/setup/HarborSetupGate.tsx` + `app/src-tauri/src/setup.rs`). The app
has no headless setup mode — every scenario is observed through the setup gate
UI and verified from a terminal afterwards.

## Prerequisites

- Run these tests on real native hosts, not Linux containers.
- Build or install a Harbor App package for the target host. The executable
  path is referenced below as `$HARBOR_APP_EXE`.
- The host must allow the app to install or use Harbor prerequisites:
  - Linux: supported package manager from `requirements.sh`, interactive sudo
    if required, and Docker daemon access.
  - macOS: Homebrew install allowed when missing, Docker Desktop or equivalent
    Docker daemon available, and any unavoidable first-run Docker prompts
    completed before retrying.
  - Windows: WSL2 available or installable, Ubuntu WSL distro available or
    installable, Docker Desktop installed or installable, and WSL integration
    enabled for the selected distro before the ready-path retry.
- Use an isolated Harbor home or clean host account when validating a clean
  setup path. Do not edit `.env` directly during any test.

## Test 1: Linux Ready Path

**Steps:**

1. On a supported Linux host, remove any previous Harbor install for the test
   account (`~/.harbor`, `~/.local/bin/harbor`) or use a fresh account.
2. Launch `$HARBOR_APP_EXE`. The setup gate should show the welcome screen
   with **Install Harbor** (status `not-installed`).
3. Click **Install Harbor**. The step indicator and live terminal output
   should progress through the `HARBOR_SETUP_STAGE` markers
   (`checking-platform` → `installing-prerequisites` → `installing-cli` →
   `linking-cli` → `verifying-cli`).
4. If the installer prompts for sudo, type the password into the input field
   below the terminal output and press **Send**.
5. Wait for the "Harbor is ready" success screen showing the CLI version, then
   click **Get Started**.
6. Verify from a fresh terminal on the same account:
   ```bash
   harbor --version
   harbor doctor --check
   ```

**Expectations:**

1. The success screen appears with a CLI version.
2. The main app UI loads after **Get Started** and lists services.
3. `harbor --version` prints a version and `harbor doctor --check` exits `0`.

## Test 2: macOS Ready Path

**Steps:**

1. On a macOS host, start Docker Desktop and complete its first-run prompts.
2. Remove any previous Harbor install for the test account or use a fresh
   account.
3. Launch `$HARBOR_APP_EXE` and run the same install flow as the Linux ready
   path (steps 2–5).
4. Verify from a fresh terminal:
   ```bash
   harbor --version
   harbor doctor --check
   ```

**Expectations:**

1. The success screen appears with a CLI version and the main UI loads.
2. `harbor doctor --check` exits `0`.

## Test 3: Windows Ready Path

**Steps:**

1. On a Windows host, ensure Docker Desktop is installed, running, and has WSL
   integration enabled for the selected Harbor WSL2 distro.
2. Remove any previous Harbor install inside the selected WSL distro or use a
   fresh distro.
3. Launch `$HARBOR_APP_EXE` and run the install flow from the setup gate.
4. Verify inside the selected WSL distro:
   ```powershell
   wsl.exe -d <distro> -e bash -lic 'harbor --version'
   wsl.exe -d <distro> -e bash -lic 'harbor doctor --check'
   ```

**Expectations:**

1. The success screen appears with a CLI version and the main UI loads.
2. The distro the app selected is persisted under
   `%LOCALAPPDATA%\Harbor\setup\wsl-distro`.
3. `harbor --version` and `harbor doctor --check` pass inside that distro.

## Test 4: Windows Docker Integration Blocker

**Steps:**

1. On a Windows host with WSL2 available, disable Docker Desktop WSL
   integration for the selected Harbor distro.
2. Launch `$HARBOR_APP_EXE` and start the install from the setup gate.

**Expectations:**

1. Setup does not reach the success screen.
2. The gate ends in `blocked` or `refresh-required` with guidance that
   identifies Docker Desktop, WSL integration, or Docker reachability as the
   problem (terminal output and the error panel name the blocker).
3. After enabling WSL integration and clicking **Retry** / **Redetect**, the
   ready path completes.

## Test 5: Existing Install Detection

**Steps:**

1. On a host where Harbor is already installed and `harbor doctor --check`
   exits `0`, launch `$HARBOR_APP_EXE`.

**Expectations:**

1. The setup gate does not appear (status `ready`); the main UI loads
   directly.
2. With the Docker daemon stopped, relaunching the app shows the setup gate
   with heading **"Almost done"** (status `refresh-required`), message
   "Harbor was installed, but it can't fully connect to Docker yet.", and red
   error text "Harbor is installed but can't connect to Docker yet. Try
   logging out and back in."; starting Docker and clicking **Redetect** loads
   the main UI.
