param(
  [string]$Distro = $env:HARBOR_WSL_DISTRO,
  [string]$InstallPath = $env:HARBOR_INSTALL_SOURCE_PATH
)

$ErrorActionPreference = "Stop"
$InstallUrl = "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh"
$DockerDesktopArch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
$DockerDesktopInstallerUrl = "https://desktop.docker.com/win/main/$DockerDesktopArch/Docker%20Desktop%20Installer.exe"

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
  & wsl.exe --status | Out-Host
  return $LASTEXITCODE -eq 0
}

function Normalize-WslOutput {
  param([string]$Text)
  $Text -replace [string][char]0, ""
}

function ConvertTo-BashSingleQuoted {
  param([string]$Value)
  "'" + $Value.Replace("'", "'\''") + "'"
}

function Get-HarborInstallCommand {
  if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    return "curl -fsSL '$InstallUrl' | bash"
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
  Start-Process -FilePath $desktopPath | Out-Null
}

function Install-DockerDesktop {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Output "Installing Docker Desktop with winget."
    & winget install --exact --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
      throw "winget failed to install Docker Desktop with code $LASTEXITCODE"
    }
    return
  }

  Write-Output "Installing Docker Desktop with the official Docker Desktop installer."
  $installerPath = Join-Path $env:TEMP "Docker Desktop Installer.exe"
  Invoke-WebRequest -UseBasicParsing -Uri $DockerDesktopInstallerUrl -OutFile $installerPath
  $installer = Start-Process -FilePath $installerPath -Wait -PassThru -ArgumentList @("install", "--user")
  if ($installer.ExitCode -ne 0) {
    throw "Docker Desktop installer exited with code $($installer.ExitCode)"
  }
}

function Test-WslDockerReady {
  param([string]$TargetDistro)

  & wsl.exe -d $TargetDistro -e bash -lic "docker info >/dev/null && docker compose version"
  return $LASTEXITCODE -eq 0
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
  Write-SetupStage "refresh-required"
  throw "WSL installation started. Restart Windows or complete distro first-run setup, then retry Harbor setup."
}

Write-SetupStage "checking-prerequisites"
$distros = Normalize-WslOutput ((& wsl.exe --list --verbose) -join "`n")
if ([string]::IsNullOrWhiteSpace($Distro)) {
  if ($distros -match "(?m)^\s*\*?\s*(Ubuntu[^\s]*)\s+Running\s+2\s*$") {
    $Distro = $Matches[1]
  } elseif ($distros -match "(?m)^\s*\*?\s*(Ubuntu[^\s]*)\s+\w+\s+2\s*$") {
    $Distro = $Matches[1]
  }
}

if ([string]::IsNullOrWhiteSpace($Distro)) {
  Write-SetupStage "installing-prerequisites"
  Write-Output "No WSL2 Ubuntu distro was found. Installing Ubuntu."
  & wsl.exe --install -d Ubuntu
  Write-SetupStage "refresh-required"
  throw "Ubuntu WSL installation started. Complete first-run account setup, then retry Harbor setup."
}

if ($distros -notmatch "(?m)^\s*\*?\s*$([regex]::Escape($Distro))\s+\w+\s+2\s*$") {
  Write-SetupStage "blocked"
  throw "Selected distro '$Distro' is not a WSL2 distro. Harbor setup requires WSL2."
}

Invoke-Wsl @("-d", $Distro, "-e", "bash", "-lic", "uname -s && command -v bash && command -v curl")

Write-SetupStage "checking-prerequisites"
if (-not (Test-DockerDesktopInstalled)) {
  Write-SetupStage "installing-prerequisites"
  Install-DockerDesktop
  Start-DockerDesktop
  Write-SetupStage "refresh-required"
  throw "Docker Desktop installation completed. Open Docker Desktop, accept required first-run prompts, enable WSL integration for '$Distro', then retry Harbor setup."
}

Start-DockerDesktop
if (-not (Wait-WslDockerReady $Distro)) {
  Write-SetupStage "blocked"
  throw "Docker Desktop did not become reachable inside WSL distro '$Distro'. Start Docker Desktop and enable WSL integration for this distro, then retry."
}

Write-SetupStage "installing-cli"
Invoke-Wsl @("-d", $Distro, "-e", "bash", "-lic", "$(Get-HarborInstallCommand)")

Write-SetupStage "verifying-cli"
Invoke-Wsl @("-d", $Distro, "-e", "bash", "-lic", "harbor --version && harbor doctor")

Write-SetupStage "ready"
Write-Output "Harbor CLI installed in WSL distro '$Distro'."
