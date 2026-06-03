# Harbor App Native Setup Integration Tests

## Prerequisites

- Run these tests on real native hosts, not Linux containers.
- Build or install a Harbor App package for the target host before running the
  smoke command. The executable path is referenced below as `$HARBOR_APP_EXE`.
- The host must allow the app to install or use Harbor prerequisites:
  - Linux: supported package manager from `requirements.sh`, interactive sudo
    if required, and Docker daemon access.
  - macOS: Homebrew install allowed when missing, Docker Desktop or equivalent
    Docker daemon available, and any unavoidable first-run Docker prompts
    completed before retrying.
  - Windows: WSL2 available or installable, Ubuntu WSL distro available or
    installable, Docker Desktop installed or installable, and WSL integration
    enabled for the selected distro before the ready-path retry.
- Set `HARBOR_APP_SETUP_SMOKE=1` so the app process runs the same Tauri setup
  backend used by the in-app setup button and exits with the setup result.
- Set `HARBOR_APP_SETUP_SMOKE_OUTPUT` to a writable JSON file path. The JSON
  must contain `ok`, `detail`, and `error` fields.
- Use an isolated Harbor home or clean host account when validating a clean
  setup path. Do not edit `.env` directly during any test.
- These tests may pull container images and the small llama.cpp smoke model.

## Test 1: Linux Ready Path

**Steps:**

1. On a supported Linux host, remove any previous Harbor install for the test
   account or use a fresh account.
2. Export:
   ```bash
   export HARBOR_APP_SETUP_SMOKE=1
   export HARBOR_APP_SETUP_SMOKE_OUTPUT="$PWD/harbor-app-linux-setup.json"
   ```
3. Run the app executable:
   ```bash
   "$HARBOR_APP_EXE"
   ```
4. Verify the JSON output:
   ```bash
   node -e 'const r=require(process.argv[1]); if (!r.ok || r.detail.status !== "ready" || !r.detail.inferenceVerificationResult) process.exit(1)' harbor-app-linux-setup.json
   ```
5. Verify Harbor and the first-run services from the same host account:
   ```bash
   harbor --version
   harbor ps | rg 'llamacpp|webui'
   url="$(harbor url webui)"
   curl -fsS --max-time 10 "$url" >/dev/null
   ```

**Expectations:**

1. The app process exits with status `0`.
2. `harbor-app-linux-setup.json` has `ok: true`.
3. `detail.status` is `ready`.
4. `detail.inferenceVerificationResult` is present.
5. `harbor ps` shows `llamacpp` and `webui`.
6. `harbor url webui` returns a URL reachable by `curl`.

## Test 2: macOS Ready Path

**Steps:**

1. On a macOS host, start Docker Desktop or complete its first-run prompts
   before the ready-path retry.
2. Remove any previous Harbor install for the test account or use a fresh
   account.
3. Export:
   ```bash
   export HARBOR_APP_SETUP_SMOKE=1
   export HARBOR_APP_SETUP_SMOKE_OUTPUT="$PWD/harbor-app-macos-setup.json"
   ```
4. Run the app executable. For an `.app` bundle, the executable is typically:
   ```bash
   "$HARBOR_APP_EXE"
   ```
5. Verify the JSON output:
   ```bash
   node -e 'const r=require(process.argv[1]); if (!r.ok || r.detail.platform !== "macos" || r.detail.status !== "ready" || !r.detail.inferenceVerificationResult) process.exit(1)' harbor-app-macos-setup.json
   ```
6. Verify Harbor and the first-run services:
   ```bash
   harbor --version
   harbor ps | rg 'llamacpp|webui'
   url="$(harbor url webui)"
   curl -fsS --max-time 10 "$url" >/dev/null
   ```

**Expectations:**

1. The app process exits with status `0`.
2. `harbor-app-macos-setup.json` has `ok: true`.
3. `detail.platform` is `macos`.
4. `detail.status` is `ready`.
5. `detail.inferenceVerificationResult` is present.
6. `harbor ps` shows `llamacpp` and `webui`.
7. Open WebUI is reachable from the macOS host.

## Test 3: Windows Ready Path

**Steps:**

1. On a Windows host, ensure Docker Desktop is installed, running, and has WSL
   integration enabled for the selected Harbor WSL2 distro.
2. Remove any previous Harbor install inside the selected WSL distro or use a
   fresh distro.
3. In PowerShell, set:
   ```powershell
   $env:HARBOR_APP_SETUP_SMOKE = "1"
   $env:HARBOR_APP_SETUP_SMOKE_OUTPUT = "$PWD\\harbor-app-windows-setup.json"
   ```
4. Run the app executable:
   ```powershell
   & $env:HARBOR_APP_EXE
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   ```
5. Verify the JSON output:
   ```powershell
   $result = Get-Content .\\harbor-app-windows-setup.json | ConvertFrom-Json
   if (-not $result.ok -or $result.detail.platform -ne "windows" -or $result.detail.status -ne "ready" -or -not $result.detail.inferenceVerificationResult) { exit 1 }
   ```
6. Verify Harbor and services inside the selected WSL distro:
   ```powershell
   $distro = $result.detail.commandTarget -replace '^wsl:', ''
   wsl.exe -d $distro -e bash -lic 'harbor --version'
   wsl.exe -d $distro -e bash -lic 'harbor ps | grep -E "llamacpp|webui"'
   ```
7. Verify Open WebUI from the Windows host:
   ```powershell
   $url = $result.detail.openWebuiUrl
   Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 $url | Out-Null
   ```

**Expectations:**

1. The app process exits with status `0`.
2. `harbor-app-windows-setup.json` has `ok: true`.
3. `detail.platform` is `windows`.
4. `detail.commandTarget` starts with `wsl:`.
5. `detail.status` is `ready`.
6. `detail.inferenceVerificationResult` is present.
7. `harbor --version` and `harbor ps` pass inside the selected WSL distro.
8. Open WebUI is reachable from the Windows host.

## Test 4: Windows Docker Integration Blocker

**Steps:**

1. On a Windows host with WSL2 available, disable Docker Desktop WSL
   integration for the selected Harbor distro.
2. Set `HARBOR_APP_SETUP_SMOKE=1` and `HARBOR_APP_SETUP_SMOKE_OUTPUT` as in the
   Windows ready-path test.
3. Run the app executable.
4. Read the JSON result:
   ```powershell
   $result = Get-Content .\\harbor-app-windows-setup.json | ConvertFrom-Json
   if ($result.ok) { exit 1 }
   if ($result.error -notmatch "Docker|WSL|integration|reachable") { exit 1 }
   ```

**Expectations:**

1. The app process exits non-zero.
2. The JSON result has `ok: false`.
3. The error text identifies Docker Desktop, WSL integration, or Docker
   reachability as the blocker.
4. No Harbor setup success is reported.
