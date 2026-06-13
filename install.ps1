param(
  [string]$Distro = $env:HARBOR_WSL_DISTRO,
  [string]$InstallPath = $env:HARBOR_INSTALL_SOURCE_PATH
)

$ErrorActionPreference = "Stop"
$InstallUrl = "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh"
$DockerDesktopArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
$DockerDesktopInstallerUrl = "https://desktop.docker.com/win/main/$DockerDesktopArch/Docker%20Desktop%20Installer.exe"

# Supported WSL distro name prefixes, in preference order.
# Keep in sync with WSL_DISTRO_PREFIXES in app/src-tauri/src/setup.rs.
$SupportedDistroPrefixes = @("Ubuntu", "Debian", "Fedora", "openSUSE", "Kali", "Arch")

function Write-SetupStage {
  param([string]$Stage)
  Write-Output "HARBOR_SETUP_STAGE=$Stage"
}

function Invoke-Wsl {
  param([string[]]$Arguments)
  & wsl.exe @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "wsl.exe $($Arguments -join ' ') exited with code $LASTEXITCODE"
  }
}

function Test-WslAvailable {
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    return $false
  }
  # Capture output without piping through Write-Output, which can
  # reset $LASTEXITCODE in some PowerShell versions.
  #
  # Use a local $ErrorActionPreference override because 2>&1 converts
  # native-command stderr lines into ErrorRecords. Under the script's
  # global $ErrorActionPreference = "Stop" (PowerShell 5.1), even a
  # single ErrorRecord triggers a terminating exception — killing the
  # whole script instead of returning $false.
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  try {
    $output = & wsl.exe --status 2>&1
    $result = $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $prevEAP
  }
  # Write-Host routes to the PTY display without entering the output stream,
  # keeping the return value a pure boolean.
  if ($output) { Write-Host ($output -join "`n") }
  return $result
}

function Normalize-WslOutput {
  param([string]$Text)
  # Remove null bytes (UTF-16LE artifacts) and the BOM (U+FEFF) that
  # wsl.exe sometimes emits.  Without this, regex anchors like ^ fail to
  # match the first line.
  $Text -replace [string][char]0, "" -replace ([string][char]0xFEFF), ""
}

function ConvertTo-BashSingleQuoted {
  param([string]$Value)
  "'" + $Value.Replace("'", "'\''") + "'"
}

function Get-HarborInstallCommand {
  if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    return "curl -fsSL --connect-timeout 15 --max-time 60 '$InstallUrl' | bash"
  }

  $quotedPath = ConvertTo-BashSingleQuoted $InstallPath
  return @(
    "source_path=`$(wslpath -a $quotedPath)"
    "bash `"`$source_path/install.sh`" --source-path `"`$source_path`" --requirements-path `"`$source_path/requirements.sh`" --version source"
  ) -join " && "
}

function Get-DockerDesktopPath {
  $candidates = @()
  if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $candidates += Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe"
  }
  if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles})) {
    $candidates += Join-Path ${env:ProgramFiles} "Docker\Docker\Docker Desktop.exe"
  }

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return $null
}

function Test-DockerDesktopInstalled {
  if (Get-DockerDesktopPath) {
    return $true
  }

  $registryRoots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )

  foreach ($root in $registryRoots) {
    $match = Get-ItemProperty $root -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -like "Docker Desktop*" } |
      Select-Object -First 1
    if ($match) {
      return $true
    }
  }

  return $false
}

function Start-DockerDesktop {
  $desktopPath = Get-DockerDesktopPath

  if ([string]::IsNullOrWhiteSpace($desktopPath)) {
    # Fallback: look up the install location from the registry (same roots
    # that Test-DockerDesktopInstalled uses to detect presence).
    $registryRoots = @(
      "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
      "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
      "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    foreach ($root in $registryRoots) {
      $match = Get-ItemProperty $root -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like "Docker Desktop*" } |
        Select-Object -First 1
      if ($match -and $match.InstallLocation) {
        $candidate = Join-Path $match.InstallLocation "Docker Desktop.exe"
        if (Test-Path $candidate) {
          $desktopPath = $candidate
          break
        }
      }
    }
  }

  if ([string]::IsNullOrWhiteSpace($desktopPath)) {
    Write-Output "WARNING: Could not find Docker Desktop executable. Please start Docker Desktop manually."
    return
  }

  Write-Output "Starting Docker Desktop."
  try {
    Start-Process -FilePath $desktopPath
  } catch {
    Write-Output "WARNING: Failed to start Docker Desktop ($($_.Exception.Message)). Please start it manually."
  }
}

function Install-DockerDesktop {
  $installerPath = Join-Path $env:TEMP "Docker Desktop Installer.exe"
  Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue

  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Output "Installing Docker Desktop with winget."
    & winget install --exact --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
      return
    }
    # winget failed — fall back to direct download.  This can happen when
    # winget is present but misconfigured (broken source, network proxy
    # blocking the msstore, expired agreements, etc.).
    Write-Output "WARNING: winget install failed (exit code $LASTEXITCODE). Falling back to direct download."
  }

  Write-Output "Installing Docker Desktop with the official Docker Desktop installer."

  # Suppress the progress bar for the duration of the download. Under
  # Windows PowerShell 5.1 the progress bar makes Invoke-WebRequest orders
  # of magnitude slower for large files. Function-scoped preference variables
  # in PowerShell revert automatically when the function returns, so this
  # does not leak to the caller's session.
  $ProgressPreference = 'SilentlyContinue'

  # Retry the download up to 3 times. The installer is ~600MB and network
  # interruptions are common, especially on slower connections.
  $maxAttempts = 3
  for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    try {
      if ($attempt -gt 1) {
        Write-Output "Download attempt $attempt of $maxAttempts..."
      }
      Invoke-WebRequest -UseBasicParsing -Uri $DockerDesktopInstallerUrl -OutFile $installerPath
      break
    } catch {
      if ($attempt -eq $maxAttempts) {
        throw "Failed to download Docker Desktop installer after $maxAttempts attempts: $_"
      }
      Write-Output "Download failed: $_. Retrying in 5 seconds..."
      Start-Sleep -Seconds 5
    }
  }

  if (-not (Test-Path $installerPath)) {
    throw "Docker Desktop installer was not downloaded. Check your network connection and try again."
  }

  try {
    $installer = Start-Process -FilePath $installerPath -Wait -PassThru -ArgumentList @("install", "--user")
    if ($installer.ExitCode -ne 0) {
      throw "Docker Desktop installer exited with code $($installer.ExitCode)"
    }
  } finally {
    # Clean up the ~600MB installer to avoid leaving stale files in TEMP.
    Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue
  }
}

function Test-WslDockerReady {
  param([string]$TargetDistro)

  # Use timeout to prevent docker info from hanging when the daemon is
  # starting up or unresponsive. The 15-second limit matches DETECT_TIMEOUT
  # in setup.rs.
  $job = Start-Job -ScriptBlock {
    param($d)
    # Suppress all output so that only the exit code marker reaches the
    # output stream.  Without this, wsl.exe startup messages (e.g.
    # "Starting <distro>...") end up in the Receive-Job result, turning
    # it into an array and breaking the exit-code comparison.
    & wsl.exe -d $d -e bash -lic "docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1" *> $null
    $LASTEXITCODE
  } -ArgumentList $TargetDistro

  $completed = Wait-Job $job -Timeout 15
  if ($null -eq $completed) {
    Stop-Job $job
    Remove-Job $job -Force
    return $false
  }
  $output = Receive-Job $job
  Remove-Job $job -Force
  # If Receive-Job still returns multiple objects (e.g. from shell
  # profile output), use only the last one — the explicit $LASTEXITCODE.
  if ($output -is [array]) {
    $exitCode = $output[-1]
  } else {
    $exitCode = $output
  }
  return $exitCode -eq 0
}

function Wait-WslDockerReady {
  param(
    [string]$TargetDistro,
    [int]$TimeoutSeconds = 180
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-WslDockerReady $TargetDistro) {
      return $true
    }
    Write-Output "Waiting for Docker Desktop to become reachable inside WSL distro '$TargetDistro'."
    Start-Sleep -Seconds 5
  }

  return $false
}

Write-SetupStage "checking-platform"

if (-not (Test-WslAvailable)) {
  Write-SetupStage "installing-prerequisites"
  Write-Output "WSL is not available. Starting the Windows-supported WSL installation flow."
  & wsl.exe --install
  if ($LASTEXITCODE -ne 0) {
    Write-SetupStage "failed"
    Write-Host "WSL installation failed (exit code $LASTEXITCODE). Run 'wsl --install' manually from an elevated PowerShell prompt."
    exit 1
  }
  Write-SetupStage "refresh-required"
  Write-Host "WSL installation started. Restart Windows or complete distro first-run setup, then retry Harbor setup."
  exit 1
}

Write-SetupStage "checking-prerequisites"
$distros = Normalize-WslOutput ((& wsl.exe --list --verbose) -join "`n")
# Get running distro names via --list --running (locale-independent — the
# output is just names, no state column).  Used below to prefer a running
# WSL2 distro over a stopped one without relying on the English word
# "Running" in the --list --verbose output.
# wsl.exe --list --running exits non-zero when no distros are running,
# potentially writing an error message to stdout (locale-dependent).
# Capture $LASTEXITCODE so we can discard the output when the command fails,
# avoiding false-positive distro name matches against the error text.
$runningRaw = (& wsl.exe --list --running) -join "`n"
if ($LASTEXITCODE -eq 0) {
  $runningDistros = Normalize-WslOutput $runningRaw
} else {
  $runningDistros = ""
}
if ([string]::IsNullOrWhiteSpace($Distro)) {
  # Try each supported distro prefix in preference order,
  # preferring a running WSL2 distro over a stopped one.
  # Use .+ instead of \w+ for the state field because non-English
  # Windows locales can produce multi-word state names (e.g. German
  # "Wird ausgeführt" for "Running").
  foreach ($prefix in $SupportedDistroPrefixes) {
    if ($distros -match "(?m)^\s*\*?\s*($([regex]::Escape($prefix))[^\s]*)\s+.+\s+2\s*$") {
      $candidate = $Matches[1]
      # Check if this WSL2 distro is currently running.  The --list
      # --running output may include a "(Default)" suffix after the name.
      if ($runningDistros -match "(?m)^\s*$([regex]::Escape($candidate))(\s|\s*$)") {
        $Distro = $candidate
        break
      }
    }
  }
  if ([string]::IsNullOrWhiteSpace($Distro)) {
    foreach ($prefix in $SupportedDistroPrefixes) {
      if ($distros -match "(?m)^\s*\*?\s*($([regex]::Escape($prefix))[^\s]*)\s+.+\s+2\s*$") {
        $Distro = $Matches[1]
        break
      }
    }
  }
}

if ([string]::IsNullOrWhiteSpace($Distro)) {
  # Check if there is a WSL1 distro that matches — give a specific upgrade message.
  $wsl1Match = $null
  foreach ($prefix in $SupportedDistroPrefixes) {
    if ($distros -match "(?m)^\s*\*?\s*($([regex]::Escape($prefix))[^\s]*)\s+.+\s+1\s*$") {
      $wsl1Match = $Matches[1]
      break
    }
  }
  if ($wsl1Match) {
    Write-SetupStage "blocked"
    Write-Host "Found WSL1 distro '$wsl1Match' but Harbor requires WSL2. Upgrade it with: wsl --set-version $wsl1Match 2"
    exit 1
  }

  Write-SetupStage "installing-prerequisites"
  $supportedNames = $SupportedDistroPrefixes -join ", "
  Write-Output "No supported WSL2 distro found (checked: $supportedNames). Installing Ubuntu."
  & wsl.exe --install -d Ubuntu
  if ($LASTEXITCODE -ne 0) {
    Write-SetupStage "failed"
    Write-Host "Ubuntu WSL installation failed (exit code $LASTEXITCODE). Run 'wsl --install -d Ubuntu' manually from an elevated PowerShell prompt."
    exit 1
  }
  Write-SetupStage "refresh-required"
  Write-Host "Ubuntu WSL installation started. Complete first-run account setup, then retry Harbor setup."
  exit 1
}

# Verify the selected distro is actually WSL2.
if ($distros -match "(?m)^\s*\*?\s*$([regex]::Escape($Distro))\s+.+\s+1\s*$") {
  Write-SetupStage "blocked"
  Write-Host "Selected distro '$Distro' is running under WSL1. Harbor requires WSL2. Upgrade it with: wsl --set-version $Distro 2"
  exit 1
} elseif ($distros -notmatch "(?m)^\s*\*?\s*$([regex]::Escape($Distro))\s+.+\s+2\s*$") {
  Write-SetupStage "blocked"
  Write-Host "Selected distro '$Distro' is not a WSL2 distro or is not installed. Set HARBOR_WSL_DISTRO to a valid WSL2 distro name."
  exit 1
}

try {
  # Use Start-Job with a timeout to prevent hanging on broken/unresponsive
  # WSL distros (e.g., filesystem corruption, hung systemd init, interactive
  # first-run setup prompts).  Without a timeout, this blocks the entire
  # install for up to 30 minutes (the Tauri run_logged timeout).
  $healthJob = Start-Job -ScriptBlock {
    param($d)
    & wsl.exe -d $d -e bash -lic "uname -s && command -v bash && command -v curl" *> $null
    $LASTEXITCODE
  } -ArgumentList $Distro
  $healthCompleted = Wait-Job $healthJob -Timeout 30
  if ($null -eq $healthCompleted) {
    Stop-Job $healthJob
    Remove-Job $healthJob -Force
    throw "WSL distro '$Distro' did not respond within 30 seconds"
  }
  $healthOutput = Receive-Job $healthJob
  Remove-Job $healthJob -Force
  if ($healthOutput -is [array]) { $healthOutput = $healthOutput[-1] }
  if ($healthOutput -ne 0) {
    throw "WSL distro '$Distro' health check failed (exit code $healthOutput)"
  }
} catch {
  Write-SetupStage "blocked"
  Write-Host "WSL distro '$Distro' cannot run basic commands (bash, curl). The distro may need a first-run setup (username/password creation) or may be corrupted. Run 'wsl -d $Distro' in a terminal to check, then retry."
  exit 1
}

Write-SetupStage "checking-prerequisites"
if (-not (Test-DockerDesktopInstalled)) {
  Write-SetupStage "installing-prerequisites"
  try {
    Install-DockerDesktop
    Start-DockerDesktop
  } catch {
    Write-SetupStage "failed"
    # Emitted after the marker so the app surfaces it as the error detail.
    Write-Output $_.Exception.Message
    exit 1
  }
  Write-SetupStage "refresh-required"
  Write-Host "Docker Desktop installation completed. Open Docker Desktop, accept required first-run prompts, enable WSL integration for '$Distro', then retry Harbor setup."
  exit 1
}

Start-DockerDesktop
if (-not (Wait-WslDockerReady $Distro)) {
  Write-SetupStage "blocked"
  Write-Host "Docker Desktop did not become reachable inside WSL distro '$Distro' within 3 minutes. Possible causes: (1) Docker Desktop requires accepting the EULA/subscription agreement on first launch, (2) WSL integration is not enabled for '$Distro' in Docker Desktop Settings > Resources > WSL Integration, (3) Docker Desktop failed to start. Open Docker Desktop manually, complete any first-run prompts, then retry."
  exit 1
}

Write-SetupStage "installing-cli"
# install.sh emits its own HARBOR_SETUP_STAGE markers (checking-platform,
# installing-prerequisites, installing-cli, linking-cli, verifying-cli, ready)
# that flow through WSL stdout to the Tauri PTY reader.  On success it sets
# "ready"; on failure it sets "blocked", "refresh-required", or "failed" and
# exits non-zero (which Invoke-Wsl converts to a throw).
# Do NOT re-run "harbor doctor" or re-emit "verifying-cli" here — that would
# cause the step indicator to regress from "ready" back to "verify" briefly
# and duplicate work that install.sh already completed.
Invoke-Wsl @("-d", $Distro, "-e", "bash", "-lic", "$(Get-HarborInstallCommand)")

Write-Output "Harbor CLI installed in WSL distro '$Distro'."
