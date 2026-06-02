use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, ExitStatus, PtySize};
use serde::Serialize;
use std::{
    env,
    ffi::OsString,
    fs,
    io::{Read, Write},
    path::PathBuf,
    process::{ChildStderr, ChildStdout, Command},
    sync::{Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, State};

const HARBOR_INSTALL_URL: &str =
    "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh";
const HARBOR_WINDOWS_INSTALL_URL: &str =
    "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.ps1";
const FIRST_RUN_MODEL: &str =
    "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/blob/main/Qwen3.5-0.8B-Q4_K_M.gguf";

#[derive(Default)]
pub struct SetupState {
    current_pid: Mutex<Option<u32>>,
    current_killer: Mutex<Option<Box<dyn ChildKiller + Send + Sync>>>,
    current_writer: Mutex<Option<Box<dyn Write + Send>>>,
    cancel_requested: Mutex<bool>,
    /// Guards the entire setup entry point so that overlapping invocations
    /// (e.g. Cancel then immediate Retry) cannot race through the
    /// `current_pid` check window between sub-steps.
    setup_active: Mutex<bool>,
    current_stage: Arc<Mutex<Option<String>>>,
}

impl SetupState {
    /// Kill any running setup child process. Called during app shutdown
    /// to prevent orphaned processes.
    pub fn kill_running_process(&self) {
        if let Ok(mut killer) = self.current_killer.lock() {
            if let Some(killer) = killer.as_mut() {
                let _ = killer.kill();
            }
            *killer = None;
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HarborSetupDetail {
    pub status: String,
    pub platform: String,
    pub architecture: String,
    pub app_version: String,
    pub command_target: String,
    pub install_target: String,
    pub cli_version: Option<String>,
    pub docker_status: Option<String>,
    pub docker_compose_status: Option<String>,
    pub doctor_summary: Option<String>,
    pub first_run_stack_service_list: Vec<String>,
    pub running_service_list: Vec<String>,
    pub open_webui_url: Option<String>,
    pub selected_small_model: String,
    pub inference_verification_result: Option<String>,
    pub last_error: Option<String>,
    pub remediation_kind: Option<String>,
    pub running: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupSmokeResult {
    ok: bool,
    detail: Option<HarborSetupDetail>,
    error: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupLogEvent {
    stage: String,
    stream: String,
    line: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupStageEvent {
    status: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupTerminalOutputEvent {
    data: String,
}

struct ProcessOutput {
    code: Option<i32>,
    stdout: String,
    stderr: String,
}

fn platform_name() -> String {
    match std::env::consts::OS {
        "macos" => "macos".into(),
        "windows" => "windows".into(),
        "linux" => "linux".into(),
        other => other.into(),
    }
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn powershell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

fn native_command_path() -> Option<OsString> {
    let mut paths = Vec::new();

    if let Some(home) = env::var_os("HOME") {
        paths.push(PathBuf::from(home).join(".local/bin"));
    }

    paths.extend([
        PathBuf::from("/opt/homebrew/bin"),
        PathBuf::from("/usr/local/bin"),
        PathBuf::from("/usr/bin"),
        PathBuf::from("/bin"),
        PathBuf::from("/usr/sbin"),
        PathBuf::from("/sbin"),
    ]);

    if let Some(current_path) = env::var_os("PATH") {
        paths.extend(env::split_paths(&current_path));
    }

    env::join_paths(paths).ok()
}

// Keep in sync with buildNativeHarborCommand in app/src/harborCommand.ts
fn native_harbor_prelude() -> &'static str {
    "export PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH\"; if ! command -v harbor >/dev/null 2>&1 && test -x \"$HOME/.harbor/harbor.sh\"; then function harbor() { \"$HOME/.harbor/harbor.sh\" \"$@\"; }; fi"
}

fn run_capture(program: &str, args: &[&str]) -> ProcessOutput {
    run_capture_timeout(program, args, None)
}

fn spawn_output_reader<R>(mut reader: R) -> std::thread::JoinHandle<String>
where
    R: Read + Send + 'static,
{
    std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = reader.read_to_end(&mut buf);
        String::from_utf8_lossy(&buf).to_string()
    })
}

fn run_capture_timeout(program: &str, args: &[&str], timeout: Option<Duration>) -> ProcessOutput {
    let mut command = Command::new(program);
    command.args(args);
    if platform_name() != "windows" {
        if let Some(path) = native_command_path() {
            command.env("PATH", path);
        }
    }

    if let Some(limit) = timeout {
        match command
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
        {
            Ok(mut child) => {
                let stdout_reader: Option<std::thread::JoinHandle<String>> = child
                    .stdout
                    .take()
                    .map(|reader: ChildStdout| spawn_output_reader(reader));
                let stderr_reader: Option<std::thread::JoinHandle<String>> = child
                    .stderr
                    .take()
                    .map(|reader: ChildStderr| spawn_output_reader(reader));
                let started = Instant::now();
                loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            let stdout = stdout_reader
                                .and_then(|reader| reader.join().ok())
                                .unwrap_or_default();
                            let stderr = stderr_reader
                                .and_then(|reader| reader.join().ok())
                                .unwrap_or_default();
                            return ProcessOutput {
                                code: status.code(),
                                stdout,
                                stderr,
                            };
                        }
                        Ok(None) => {
                            if started.elapsed() > limit {
                                let _ = child.kill();
                                let _ = child.wait();
                                let stdout = stdout_reader
                                    .and_then(|reader| reader.join().ok())
                                    .unwrap_or_default();
                                let stderr = stderr_reader
                                    .and_then(|reader| reader.join().ok())
                                    .unwrap_or_default();
                                return ProcessOutput {
                                    code: Some(124),
                                    stdout,
                                    stderr: format!(
                                        "{}{}{} timed out after {}s",
                                        stderr,
                                        if stderr.is_empty() { "" } else { "\n" },
                                        program,
                                        limit.as_secs()
                                    ),
                                };
                            }
                            std::thread::sleep(Duration::from_millis(100));
                        }
                        Err(err) => {
                            return ProcessOutput {
                                code: Some(127),
                                stdout: String::new(),
                                stderr: err.to_string(),
                            };
                        }
                    }
                }
            }
            Err(err) => ProcessOutput {
                code: Some(127),
                stdout: String::new(),
                stderr: err.to_string(),
            },
        }
    } else {
        match command.output() {
            Ok(output) => ProcessOutput {
                code: output.status.code(),
                stdout: String::from_utf8_lossy(&output.stdout).to_string(),
                stderr: String::from_utf8_lossy(&output.stderr).to_string(),
            },
            Err(err) => ProcessOutput {
                code: Some(127),
                stdout: String::new(),
                stderr: err.to_string(),
            },
        }
    }
}

fn run_shell(script: &str) -> ProcessOutput {
    run_shell_timeout(script, None)
}

fn run_shell_timeout(script: &str, timeout: Option<Duration>) -> ProcessOutput {
    if platform_name() == "windows" {
        run_capture_timeout(
            "powershell.exe",
            &[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            timeout,
        )
    } else {
        run_capture_timeout("bash", &["-lc", script], timeout)
    }
}

fn selected_wsl_distro() -> Option<String> {
    std::env::var("HARBOR_WSL_DISTRO")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn stored_wsl_distro_path() -> Option<PathBuf> {
    let base = std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("APPDATA"))
        .or_else(|| std::env::var_os("USERPROFILE"))?;
    Some(
        PathBuf::from(base)
            .join("Harbor")
            .join("setup")
            .join("wsl-distro"),
    )
}

fn read_stored_wsl_distro() -> Option<String> {
    let path = stored_wsl_distro_path()?;
    fs::read_to_string(path)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn persist_wsl_distro(distro: &str) {
    let Some(path) = stored_wsl_distro_path() else {
        return;
    };
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(path, distro);
}

fn parse_wsl2_ubuntu_distro(output: &str, require_running: bool) -> Option<String> {
    output
        .replace('\0', "")
        .lines()
        .filter_map(|line| {
            let parts = line.split_whitespace().collect::<Vec<_>>();
            if parts.is_empty() {
                return None;
            }

            let name_index = if parts.first() == Some(&"*") { 1 } else { 0 };
            let state_index = name_index + 1;
            let version_index = name_index + 2;
            let name = parts.get(name_index)?;
            let state = parts.get(state_index)?;
            let version = parts.get(version_index)?;

            if name.starts_with("Ubuntu")
                && *version == "2"
                && (!require_running || state.eq_ignore_ascii_case("Running"))
            {
                Some((*name).to_string())
            } else {
                None
            }
        })
        .next()
}

fn parse_wsl_distro_exists(output: &str, distro: &str) -> bool {
    output.replace('\0', "").lines().any(|line| {
        let parts = line.split_whitespace().collect::<Vec<_>>();
        if parts.is_empty() {
            return false;
        }

        let name_index = if parts.first() == Some(&"*") { 1 } else { 0 };
        let version_index = name_index + 2;
        parts.get(name_index) == Some(&distro) && parts.get(version_index) == Some(&"2")
    })
}

static WSL_DISTRO_CACHE: OnceLock<Mutex<Option<String>>> = OnceLock::new();

fn wsl_distro_cache() -> &'static Mutex<Option<String>> {
    WSL_DISTRO_CACHE.get_or_init(|| Mutex::new(None))
}

fn clear_wsl_distro_cache() {
    if let Ok(mut cached) = wsl_distro_cache().lock() {
        *cached = None;
    }
}

fn preferred_wsl_distro() -> Option<String> {
    if let Ok(cached) = wsl_distro_cache().lock() {
        if let Some(distro) = cached.as_ref() {
            return Some(distro.clone());
        }
    }

    let result = resolve_wsl_distro();
    if let Ok(mut cached) = wsl_distro_cache().lock() {
        *cached = result.clone();
    }
    result
}

fn resolve_wsl_distro() -> Option<String> {
    if let Some(distro) = selected_wsl_distro() {
        persist_wsl_distro(&distro);
        return Some(distro);
    }

    let distros = run_capture("wsl.exe", &["--list", "--verbose"]);
    if distros.code != Some(0) {
        return None;
    }

    if let Some(distro) = read_stored_wsl_distro() {
        if parse_wsl_distro_exists(&distros.stdout, &distro) {
            return Some(distro);
        }
    }

    let distro = parse_wsl2_ubuntu_distro(&distros.stdout, true)
        .or_else(|| parse_wsl2_ubuntu_distro(&distros.stdout, false));
    if let Some(distro) = distro.as_deref() {
        persist_wsl_distro(distro);
    }
    distro
}

fn wsl_bash_args(script: &str) -> Vec<String> {
    let mut args = Vec::new();
    if let Some(distro) = preferred_wsl_distro() {
        args.push("-d".into());
        args.push(distro);
    }
    args.extend(["-e".into(), "bash".into(), "-lic".into(), script.into()]);
    args
}

fn run_wsl_bash(script: &str) -> ProcessOutput {
    let args = wsl_bash_args(script);
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    run_capture("wsl.exe", &arg_refs)
}

fn run_wsl_bash_timeout(script: &str, timeout: Option<Duration>) -> ProcessOutput {
    let args = wsl_bash_args(script);
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    run_capture_timeout("wsl.exe", &arg_refs, timeout)
}

fn harbor_script(args: &[&str]) -> String {
    let quoted = args.iter().map(|arg| shell_quote(arg)).collect::<Vec<_>>();
    if quoted.is_empty() {
        "harbor".into()
    } else {
        format!("harbor {}", quoted.join(" "))
    }
}

fn native_harbor_script(args: &[&str]) -> String {
    format!("{}; {}", native_harbor_prelude(), harbor_script(args))
}

fn native_harbor_shell(script: &str) -> String {
    format!("{}; {script}", native_harbor_prelude())
}

fn run_harbor(args: &[&str]) -> ProcessOutput {
    if platform_name() == "windows" {
        run_wsl_bash(&harbor_script(args))
    } else {
        run_shell(&native_harbor_script(args))
    }
}

fn run_harbor_timeout(args: &[&str], timeout: Option<Duration>) -> ProcessOutput {
    if platform_name() == "windows" {
        run_wsl_bash_timeout(&harbor_script(args), timeout)
    } else {
        run_shell_timeout(&native_harbor_script(args), timeout)
    }
}

fn open_host_url(url: &str) -> ProcessOutput {
    match platform_name().as_str() {
        "windows" => run_capture(
            "powershell.exe",
            &[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                &format!("Start-Process {}", powershell_quote(url)),
            ],
        ),
        "macos" => run_capture("open", &[url]),
        _ => run_capture("xdg-open", &[url]),
    }
}

fn short_error(output: &ProcessOutput) -> Option<String> {
    output
        .stderr
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .or_else(|| {
            output
                .stdout
                .lines()
                .rev()
                .find(|line| !line.trim().is_empty())
        })
        .map(|line| line.trim().to_string())
}

fn process_indicates_missing_command(output: &ProcessOutput, command: &str) -> bool {
    let combined_output = format!("{}\n{}", output.stderr, output.stdout).to_lowercase();
    let command = command.to_lowercase();

    output.code == Some(127)
        || combined_output.contains("no such file or directory")
        || combined_output.contains("not found")
        || combined_output.contains(&format!("{command}: command not found"))
}

fn command_target() -> String {
    if platform_name() == "windows" {
        if let Some(distro) = preferred_wsl_distro() {
            return format!("wsl:{distro}");
        }

        let distro = run_wsl_bash("printf '%s' \"${WSL_DISTRO_NAME:-default}\"");
        let name = distro.stdout.trim();
        if name.is_empty() {
            "wsl:default".into()
        } else {
            format!("wsl:{name}")
        }
    } else {
        "native-shell".into()
    }
}

/// Per-command timeout applied to external processes during detection.
const DETECT_CMD_TIMEOUT: Duration = Duration::from_secs(15);

/// Timeout for longer detection commands (harbor doctor, harbor ps).
const DETECT_LONG_TIMEOUT: Duration = Duration::from_secs(30);

/// Timeout for the inference verification step during detection.
const DETECT_INFERENCE_TIMEOUT: Duration = Duration::from_secs(90);

fn detect_windows_target(detail: &mut HarborSetupDetail) -> bool {
    if detail.platform != "windows" {
        return false;
    }

    let wsl_status = run_capture_timeout("wsl.exe", &["--status"], Some(DETECT_CMD_TIMEOUT));
    if wsl_status.code != Some(0) {
        detail.status = "checking-prerequisites".into();
        detail.remediation_kind = Some("missing-wsl".into());
        detail.last_error = short_error(&wsl_status)
            .or_else(|| Some("Windows Subsystem for Linux is not available.".into()));
        return true;
    }

    let distros = run_capture_timeout(
        "wsl.exe",
        &["--list", "--verbose"],
        Some(DETECT_CMD_TIMEOUT),
    );
    if distros.code != Some(0) {
        detail.status = "checking-prerequisites".into();
        detail.remediation_kind = Some("missing-wsl-distro".into());
        detail.last_error = short_error(&distros)
            .or_else(|| Some("No WSL2 Ubuntu distro is available for Harbor setup.".into()));
        return true;
    }

    if let Some(distro) = selected_wsl_distro() {
        if !parse_wsl_distro_exists(&distros.stdout, &distro) {
            detail.command_target = format!("wsl:{distro}");
            detail.status = "checking-prerequisites".into();
            detail.remediation_kind = Some("missing-wsl-distro".into());
            detail.last_error = Some(format!(
                "Selected WSL distro '{distro}' is not an available WSL2 distro."
            ));
            return true;
        }
    } else if preferred_wsl_distro().is_none() {
        detail.status = "checking-prerequisites".into();
        detail.remediation_kind = Some("missing-wsl-distro".into());
        detail.last_error = Some("No WSL2 Ubuntu distro is available for Harbor setup.".into());
        return true;
    }

    false
}

fn detect_platform_blocker(detail: &mut HarborSetupDetail) -> bool {
    match detail.platform.as_str() {
        "linux" => {
            let check = run_shell_timeout("command -v apt-get >/dev/null || command -v dnf >/dev/null || command -v pacman >/dev/null || command -v apk >/dev/null", Some(DETECT_CMD_TIMEOUT));
            if check.code != Some(0) {
                detail.status = "blocked".into();
                detail.remediation_kind = Some("unsupported-platform".into());
                detail.last_error = Some(
                    "No supported Linux package manager found (apt, dnf, pacman, or apk).".into(),
                );
                return true;
            }
        }
        "macos" | "windows" => {}
        _ => {
            detail.status = "blocked".into();
            detail.remediation_kind = Some("unsupported-platform".into());
            detail.last_error = Some(format!(
                "Harbor App setup is not supported on {}.",
                detail.platform
            ));
            return true;
        }
    }
    false
}

fn detect_cli(detail: &mut HarborSetupDetail) -> bool {
    let detected = if detail.platform == "windows" {
        run_wsl_bash_timeout(
            "command -v harbor >/dev/null && harbor --version",
            Some(DETECT_CMD_TIMEOUT),
        )
    } else {
        run_shell_timeout(
            &format!(
                "{}; command -v harbor >/dev/null && harbor --version",
                native_harbor_prelude()
            ),
            Some(DETECT_CMD_TIMEOUT),
        )
    };

    if detected.code == Some(0) {
        detail.cli_version = Some(detected.stdout.trim().to_string());
        true
    } else if detect_native_harbor_install(detail) {
        false
    } else {
        detail.status = "checking-cli".into();
        detail.remediation_kind = Some("missing-cli".into());
        detail.last_error = short_error(&detected)
            .or_else(|| Some("Harbor CLI was not found in the setup target.".into()));
        false
    }
}

fn detect_native_harbor_install(detail: &mut HarborSetupDetail) -> bool {
    if detail.platform == "windows" {
        return false;
    }

    let installed = run_shell_timeout(
        "test -e \"$HOME/.local/bin/harbor\" -o -x \"$HOME/.harbor/harbor.sh\"",
        Some(DETECT_CMD_TIMEOUT),
    );
    if installed.code != Some(0) {
        return false;
    }

    detail.status = "refresh-required".into();
    detail.remediation_kind = Some("cli-path-refresh".into());
    detail.last_error = Some(
        "Harbor appears to be installed at ~/.local/bin/harbor or ~/.harbor/harbor.sh, but the app could not verify the CLI command. Relaunch Harbor App or refresh the shell session, then retry setup.".into(),
    );
    true
}

fn detect_docker(detail: &mut HarborSetupDetail) -> bool {
    let docker = if detail.platform == "windows" {
        run_wsl_bash_timeout("docker info >/dev/null", Some(DETECT_LONG_TIMEOUT))
    } else {
        run_capture_timeout("docker", &["info"], Some(DETECT_LONG_TIMEOUT))
    };

    if docker.code != Some(0) {
        if process_indicates_missing_command(&docker, "docker") {
            detail.status = "checking-prerequisites".into();
            detail.remediation_kind = Some(if detail.platform == "linux" {
                "verification-failed".into()
            } else {
                "missing-docker-desktop".into()
            });
            detail.docker_status = Some("missing".into());
            detail.last_error = Some("Docker CLI is not installed in the setup target.".into());
            return false;
        }

        detail.status = "blocked".into();
        detail.remediation_kind = Some("docker-daemon-unreachable".into());
        detail.docker_status = Some("unreachable".into());
        detail.last_error =
            short_error(&docker).or_else(|| Some("Docker daemon is not reachable.".into()));
        return false;
    }
    detail.docker_status = Some("ready".into());

    let compose = if detail.platform == "windows" {
        run_wsl_bash_timeout("docker compose version", Some(DETECT_CMD_TIMEOUT))
    } else {
        run_capture_timeout("docker", &["compose", "version"], Some(DETECT_CMD_TIMEOUT))
    };
    if compose.code != Some(0) {
        detail.status = "checking-prerequisites".into();
        detail.remediation_kind = Some("verification-failed".into());
        detail.docker_compose_status = Some("missing".into());
        detail.last_error =
            short_error(&compose).or_else(|| Some("Docker Compose v2 is not available.".into()));
        return false;
    }
    detail.docker_compose_status = Some(compose.stdout.trim().to_string());
    true
}

fn detect_doctor(detail: &mut HarborSetupDetail) -> bool {
    let doctor = run_harbor_timeout(&["doctor"], Some(DETECT_LONG_TIMEOUT));
    detail.doctor_summary = Some(
        doctor
            .stderr
            .lines()
            .rev()
            .find(|line| !line.trim().is_empty())
            .unwrap_or("harbor doctor completed")
            .trim()
            .to_string(),
    );

    if doctor.code != Some(0) {
        detail.status = "verifying-cli".into();
        detail.remediation_kind = Some("verification-failed".into());
        detail.last_error =
            short_error(&doctor).or_else(|| Some("Harbor doctor did not complete.".into()));
        return false;
    }

    true
}

fn verify_webui_llamacpp_config() -> ProcessOutput {
    let script = "home=$(harbor home); config=\"$home/services/webui/config.json\"; test -f \"$config\" && grep -Fq 'http://llamacpp:8080/v1' \"$config\"";
    if platform_name() == "windows" {
        run_wsl_bash_timeout(script, Some(DETECT_CMD_TIMEOUT))
    } else {
        run_shell_timeout(&native_harbor_shell(script), Some(DETECT_CMD_TIMEOUT))
    }
}

fn target_curl_url(url: &str) -> ProcessOutput {
    if platform_name() == "windows" {
        run_wsl_bash_timeout(
            &format!("curl -fsS --max-time 5 {} >/dev/null", shell_quote(url)),
            Some(DETECT_CMD_TIMEOUT),
        )
    } else {
        run_capture_timeout(
            "curl",
            &["-fsS", "--max-time", "5", url],
            Some(DETECT_CMD_TIMEOUT),
        )
    }
}

fn detect_first_run_stack(detail: &mut HarborSetupDetail) {
    detail.first_run_stack_service_list = vec!["llamacpp".into(), "webui".into()];

    let ps = run_harbor_timeout(&["ps"], Some(DETECT_LONG_TIMEOUT));
    if ps.code == Some(0) {
        detail.running_service_list = ps
            .stdout
            .lines()
            .filter(|line| line.contains("llamacpp") || line.contains("webui"))
            .map(|line| line.trim().to_string())
            .collect();
    }

    let webui_url = run_harbor_timeout(&["url", "webui"], Some(DETECT_CMD_TIMEOUT));
    if webui_url.code == Some(0) {
        detail.open_webui_url = Some(webui_url.stdout.trim().to_string());
    }

    let llamacpp_url = run_harbor_timeout(&["url", "llamacpp"], Some(DETECT_CMD_TIMEOUT));
    let webui_ok = detail
        .open_webui_url
        .as_deref()
        .map(|url| target_curl_url(url).code == Some(0))
        .unwrap_or(false);
    let llamacpp_ok = if llamacpp_url.code == Some(0) {
        let url = format!(
            "{}/v1/models",
            llamacpp_url.stdout.trim().trim_end_matches('/')
        );
        target_curl_url(&url).code == Some(0)
    } else {
        false
    };

    if !webui_ok || !llamacpp_ok {
        detail.status = "configuring-first-run-stack".into();
        detail.remediation_kind = Some("stack-start-failed".into());
        detail.last_error = Some("Open WebUI plus llama.cpp is not fully reachable yet.".into());
        return;
    }

    let webui_backend = verify_webui_llamacpp_config();
    if webui_backend.code != Some(0) {
        detail.status = "configuring-first-run-stack".into();
        detail.remediation_kind = Some("webui-backend-config-failed".into());
        detail.last_error = short_error(&webui_backend)
            .or_else(|| Some("Open WebUI is not configured with the llama.cpp backend.".into()));
        return;
    }

    let inference = if detail.platform == "windows" {
        run_wsl_bash_timeout("url=$(harbor url llamacpp | sed 's#/*$##'); model=$(curl -fsS --max-time 5 \"$url/v1/models\" | sed -n 's/.*\"id\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p' | head -n1); test -n \"$model\" && curl -fsS --max-time 60 -H 'Content-Type: application/json' -d \"{\\\"model\\\":\\\"$model\\\",\\\"messages\\\":[{\\\"role\\\":\\\"user\\\",\\\"content\\\":\\\"Say ready.\\\"}],\\\"max_tokens\\\":8}\" \"$url/v1/chat/completions\" | grep -q 'choices'", Some(DETECT_INFERENCE_TIMEOUT))
    } else {
        run_shell_timeout(&native_harbor_shell("url=$(harbor url llamacpp | sed 's#/*$##'); model=$(curl -fsS --max-time 5 \"$url/v1/models\" | sed -n 's/.*\"id\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p' | head -n1); test -n \"$model\" && curl -fsS --max-time 60 -H 'Content-Type: application/json' -d \"{\\\"model\\\":\\\"$model\\\",\\\"messages\\\":[{\\\"role\\\":\\\"user\\\",\\\"content\\\":\\\"Say ready.\\\"}],\\\"max_tokens\\\":8}\" \"$url/v1/chat/completions\" | grep -q 'choices'"), Some(DETECT_INFERENCE_TIMEOUT))
    };

    if inference.code == Some(0) {
        detail.status = "ready".into();
        detail.remediation_kind = None;
        detail.last_error = None;
        detail.inference_verification_result = Some("llama.cpp inference succeeded".into());
    } else {
        detail.status = "verifying-inference".into();
        detail.remediation_kind = Some("llamacpp-inference-failed".into());
        detail.last_error =
            short_error(&inference).or_else(|| Some("llama.cpp inference check failed.".into()));
    }
}

fn setup_is_active(state: &SetupState) -> bool {
    state
        .setup_active
        .lock()
        .map(|active| *active)
        .unwrap_or(false)
}

fn set_current_stage(state: &SetupState, stage: &str) {
    if let Ok(mut current_stage) = state.current_stage.lock() {
        *current_stage = Some(stage.to_string());
    }
}

fn current_setup_stage(state: &SetupState) -> String {
    state
        .current_stage
        .lock()
        .ok()
        .and_then(|stage| stage.clone())
        .unwrap_or_else(|| "checking-platform".into())
}

#[tauri::command]
pub fn detect_harbor_setup(state: State<'_, SetupState>) -> HarborSetupDetail {
    clear_wsl_distro_cache();
    detect_harbor_setup_inner(&state)
}

fn detect_harbor_setup_inner(state: &SetupState) -> HarborSetupDetail {
    let child_running = state
        .current_pid
        .lock()
        .map(|pid| pid.is_some())
        .unwrap_or(false);
    let running = child_running || setup_is_active(&state);
    let platform = platform_name();
    let mut detail = HarborSetupDetail {
        status: "checking-platform".into(),
        architecture: std::env::consts::ARCH.into(),
        app_version: env!("CARGO_PKG_VERSION").into(),
        command_target: if platform == "windows" {
            // Defer full WSL detection to avoid calling wsl.exe before
            // detect_windows_target() has verified WSL availability.
            "wsl:pending".into()
        } else {
            command_target()
        },
        install_target: if platform == "windows" {
            "wsl2".into()
        } else {
            "user-home".into()
        },
        platform,
        cli_version: None,
        docker_status: None,
        docker_compose_status: None,
        doctor_summary: None,
        first_run_stack_service_list: vec![],
        running_service_list: vec![],
        open_webui_url: None,
        selected_small_model: FIRST_RUN_MODEL.into(),
        inference_verification_result: None,
        last_error: None,
        remediation_kind: None,
        running,
    };

    if running {
        detail.status = current_setup_stage(&state);
        return detail;
    }

    if detect_platform_blocker(&mut detail) || detect_windows_target(&mut detail) {
        return detail;
    }

    // Now that WSL availability is confirmed (on Windows), resolve the real command target.
    if detail.platform == "windows" {
        detail.command_target = command_target();
    }

    if !detect_cli(&mut detail) {
        return detail;
    }

    detail.status = "checking-prerequisites".into();
    if !detect_docker(&mut detail) {
        return detail;
    }

    detail.status = "verifying-cli".into();
    if !detect_doctor(&mut detail) {
        return detail;
    }
    detail.status = "verifying-inference".into();
    detect_first_run_stack(&mut detail);
    detail
}

#[tauri::command]
pub fn get_harbor_wsl_distro() -> Option<String> {
    if platform_name() == "windows" {
        preferred_wsl_distro()
    } else {
        None
    }
}

fn emit_stage(app: &AppHandle, stage: &str) {
    let _ = app.emit(
        "harbor-setup-status",
        SetupStageEvent {
            status: stage.into(),
        },
    );
}

fn emit_log(app: &AppHandle, stage: &str, stream: &str, line: &str) {
    let _ = app.emit(
        "harbor-setup-log",
        SetupLogEvent {
            stage: stage.into(),
            stream: stream.into(),
            line: line.into(),
        },
    );
}

fn emit_terminal_output(app: &AppHandle, data: &str) {
    let _ = app.emit(
        "harbor-setup-terminal-output",
        SetupTerminalOutputEvent { data: data.into() },
    );
}

fn parse_setup_stage_marker(line: &str) -> Option<String> {
    line.trim()
        .strip_prefix("HARBOR_SETUP_STAGE=")
        .map(str::trim)
        .filter(|stage| !stage.is_empty())
        .map(str::to_string)
}

fn emit_process_line(
    app: &AppHandle,
    stage: &str,
    stream: &str,
    line: &str,
    marker_state: &Arc<Mutex<Option<String>>>,
    current_stage_state: &Arc<Mutex<Option<String>>>,
    last_line_state: &Arc<Mutex<Option<String>>>,
) {
    if let Ok(mut last_line) = last_line_state.lock() {
        *last_line = Some(line.trim().to_string());
    }

    if let Some(marker) = parse_setup_stage_marker(line) {
        if let Ok(mut current) = marker_state.lock() {
            *current = Some(marker.clone());
        }
        if let Ok(mut current_stage) = current_stage_state.lock() {
            *current_stage = Some(marker.clone());
        }
        emit_stage(app, &marker);
    }

    emit_log(app, stage, stream, line);
}

fn emit_process_chunk(
    app: &AppHandle,
    stage: &str,
    stream: &str,
    chunk: &str,
    marker_state: &Arc<Mutex<Option<String>>>,
    current_stage_state: &Arc<Mutex<Option<String>>>,
    last_line_state: &Arc<Mutex<Option<String>>>,
    line_buffer: &mut String,
) {
    emit_terminal_output(app, chunk);

    for ch in chunk.chars() {
        if ch == '\n' || ch == '\r' {
            let line = line_buffer.trim_end_matches('\r');
            if !line.trim().is_empty() {
                emit_process_line(
                    app,
                    stage,
                    stream,
                    line,
                    marker_state,
                    current_stage_state,
                    last_line_state,
                );
            }
            line_buffer.clear();
        } else {
            line_buffer.push(ch);
        }
    }
}

fn marker_is_terminal(marker: &str) -> bool {
    matches!(
        marker,
        "blocked" | "cancelled" | "failed" | "refresh-required"
    )
}

fn clear_running_state(state: &SetupState, reset_cancel: bool) {
    if let Ok(mut current) = state.current_pid.lock() {
        *current = None;
    }
    if let Ok(mut killer) = state.current_killer.lock() {
        *killer = None;
    }
    if let Ok(mut writer) = state.current_writer.lock() {
        *writer = None;
    }
    if reset_cancel {
        if let Ok(mut cancel_requested) = state.cancel_requested.lock() {
            *cancel_requested = false;
        }
    }
}

fn format_pty_exit(status: &ExitStatus) -> String {
    if let Some(signal) = status.signal() {
        format!("signal {signal}")
    } else {
        status.exit_code().to_string()
    }
}

fn run_logged(
    app: &AppHandle,
    state: &SetupState,
    stage: &str,
    program: &str,
    args: &[&str],
    timeout: Option<Duration>,
) -> Result<(), String> {
    set_current_stage(state, stage);
    emit_stage(app, stage);
    let command_line = format!("$ {} {}", program, args.join(" "));
    emit_log(app, stage, "stdout", &command_line);
    emit_terminal_output(app, &format!("{command_line}\r\n"));

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: 30,
            cols: 120,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|err| err.to_string())?;
    let mut command = CommandBuilder::new(program);
    command.args(args);
    command.env("TERM", "xterm-256color");
    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|err| err.to_string())?;
    let writer = pair.master.take_writer().map_err(|err| err.to_string())?;
    let mut child = pair
        .slave
        .spawn_command(command)
        .map_err(|err| err.to_string())?;

    if state.cancel_requested.lock().map(|c| *c).unwrap_or(false) {
        let _ = child.kill();
        clear_running_state(state, true);
        emit_stage(app, "cancelled");
        return Err(format!("HARBOR_SETUP_STATUS=cancelled; {stage} cancelled"));
    }
    let pid = child.process_id().unwrap_or(0);
    if let Ok(mut current) = state.current_pid.lock() {
        *current = Some(pid);
    }
    if let Ok(mut killer) = state.current_killer.lock() {
        *killer = Some(child.clone_killer());
    }
    if let Ok(mut current_writer) = state.current_writer.lock() {
        *current_writer = Some(writer);
    }

    let marker_state = Arc::new(Mutex::new(None));
    let last_line_state = Arc::new(Mutex::new(None));
    let reader_app = app.clone();
    let reader_stage = stage.to_string();
    let reader_marker_state = marker_state.clone();
    let reader_current_stage = state.current_stage.clone();
    let reader_last_line_state = last_line_state.clone();
    let reader_thread = std::thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        let mut line_buffer = String::new();
        // Carry-over buffer for incomplete multi-byte UTF-8 sequences
        // split across read boundaries. At most 3 bytes (max UTF-8 char
        // is 4 bytes, so at most 3 leading bytes can be left over).
        let mut utf8_carry: Vec<u8> = Vec::new();
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(size) => {
                    // Combine any carry-over bytes with the new read
                    // into a single contiguous slice for UTF-8 validation.
                    utf8_carry.extend_from_slice(&buffer[..size]);

                    // Find the last complete UTF-8 boundary. If the tail
                    // bytes form an incomplete character, carry them over
                    // to the next read instead of replacing them with U+FFFD.
                    let valid_end = match std::str::from_utf8(&utf8_carry) {
                        Ok(_) => utf8_carry.len(),
                        Err(e) => {
                            let valid = e.valid_up_to();
                            // If there's an error_len, the bytes are truly
                            // invalid (not just incomplete). Include them so
                            // from_utf8_lossy can replace them.
                            if let Some(len) = e.error_len() {
                                valid + len
                            } else {
                                // Incomplete sequence at the end -- carry over.
                                valid
                            }
                        }
                    };

                    if valid_end > 0 {
                        let chunk = String::from_utf8_lossy(&utf8_carry[..valid_end]).to_string();
                        emit_process_chunk(
                            &reader_app,
                            &reader_stage,
                            "pty",
                            &chunk,
                            &reader_marker_state,
                            &reader_current_stage,
                            &reader_last_line_state,
                            &mut line_buffer,
                        );
                    }

                    // Keep only the incomplete trailing bytes for next iteration.
                    if valid_end < utf8_carry.len() {
                        let remaining = utf8_carry[valid_end..].to_vec();
                        utf8_carry = remaining;
                    } else {
                        utf8_carry.clear();
                    }
                }
                Err(_) => break,
            }
        }
        // Flush any remaining bytes (incomplete UTF-8 at EOF).
        if !utf8_carry.is_empty() {
            let chunk = String::from_utf8_lossy(&utf8_carry).to_string();
            emit_process_chunk(
                &reader_app,
                &reader_stage,
                "pty",
                &chunk,
                &reader_marker_state,
                &reader_current_stage,
                &reader_last_line_state,
                &mut line_buffer,
            );
        }
        if !line_buffer.trim().is_empty() {
            emit_process_line(
                &reader_app,
                &reader_stage,
                "pty",
                &line_buffer,
                &reader_marker_state,
                &reader_current_stage,
                &reader_last_line_state,
            );
        }
    });

    let started = Instant::now();
    let wait_result: Result<ExitStatus, String> = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => {
                if timeout
                    .map(|limit| started.elapsed() > limit)
                    .unwrap_or(false)
                {
                    let _ = child.kill();
                    break Err(format!("{stage} timed out"));
                }
                std::thread::sleep(Duration::from_millis(250));
            }
            Err(err) => break Err(err.to_string()),
        }
    };

    // Always clean up state and join the reader thread before returning,
    // regardless of how the process exited (success, timeout, or error).
    let reset_cancel = wait_result.is_err();
    clear_running_state(state, reset_cancel);
    drop(pair);
    let _ = reader_thread.join();

    let status = match wait_result {
        Ok(status) => status,
        Err(err) => return Err(err),
    };

    let was_cancelled = state
        .cancel_requested
        .lock()
        .map(|mut cancel_requested| {
            let was_cancelled = *cancel_requested;
            *cancel_requested = false;
            was_cancelled
        })
        .unwrap_or(false);

    if was_cancelled {
        emit_stage(app, "cancelled");
        Err(format!("HARBOR_SETUP_STATUS=cancelled; {stage} cancelled"))
    } else if status.success() {
        Ok(())
    } else {
        let terminal_marker = marker_state
            .lock()
            .ok()
            .and_then(|marker| marker.clone())
            .filter(|marker| marker_is_terminal(marker));

        if let Some(marker) = terminal_marker {
            let last_output_line = last_line_state
                .lock()
                .ok()
                .and_then(|line| line.clone())
                .filter(|line| {
                    !parse_setup_stage_marker(line)
                        .as_deref()
                        .is_some_and(|stage| stage == marker)
                });

            let detail = last_output_line
                .map(|line| format!("; {line}"))
                .unwrap_or_default();

            return Err(format!(
                "HARBOR_SETUP_STATUS={marker}; {stage} exited with code {}{detail}",
                format_pty_exit(&status),
            ));
        }

        Err(format!(
            "{stage} exited with code {}",
            format_pty_exit(&status)
        ))
    }
}

fn run_logged_shell(
    app: &AppHandle,
    state: &SetupState,
    stage: &str,
    script: &str,
    timeout: Option<Duration>,
) -> Result<(), String> {
    if platform_name() == "windows" {
        run_logged(
            app,
            state,
            stage,
            "powershell.exe",
            &[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            timeout,
        )
    } else {
        run_logged(app, state, stage, "bash", &["-lc", script], timeout)
    }
}

fn run_logged_wsl_bash(
    app: &AppHandle,
    state: &SetupState,
    stage: &str,
    script: &str,
    timeout: Option<Duration>,
) -> Result<(), String> {
    let args = wsl_bash_args(script);
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    run_logged(app, state, stage, "wsl.exe", &arg_refs, timeout)
}

fn install_script() -> String {
    if let Ok(local_script) = std::env::var("HARBOR_APP_INSTALL_SCRIPT") {
        format!("bash {}", shell_quote(&local_script))
    } else {
        format!("curl -fsSL {} | bash", shell_quote(HARBOR_INSTALL_URL))
    }
}

fn windows_install_script(distro: Option<&str>) -> String {
    let distro_prefix = distro
        .map(|distro| format!("$env:HARBOR_WSL_DISTRO = {}; ", powershell_quote(distro)))
        .unwrap_or_default();

    if let Ok(local_script) = std::env::var("HARBOR_APP_WINDOWS_INSTALL_SCRIPT") {
        let distro_arg = distro
            .map(|distro| format!(" -Distro {}", powershell_quote(distro)))
            .unwrap_or_default();
        format!(
            "{}& {}{}",
            distro_prefix,
            powershell_quote(&local_script),
            distro_arg
        )
    } else {
        format!(
            "{}iwr -UseBasicParsing {} | iex",
            distro_prefix,
            powershell_quote(HARBOR_WINDOWS_INSTALL_URL)
        )
    }
}

#[tauri::command]
pub fn start_harbor_setup(
    app: AppHandle,
    state: State<'_, SetupState>,
) -> Result<HarborSetupDetail, String> {
    start_harbor_setup_inner(&app, &state)
}

fn start_harbor_setup_inner(
    app: &AppHandle,
    state: &SetupState,
) -> Result<HarborSetupDetail, String> {
    let guard = acquire_setup_lock(state)?;

    reset_cancel(state);

    if platform_name() == "windows" {
        let distro = preferred_wsl_distro();
        run_logged_shell(
            app,
            state,
            "installing-cli",
            &windows_install_script(distro.as_deref()),
            Some(Duration::from_secs(1800)),
        )?;
    } else {
        run_logged_shell(
            app,
            state,
            "installing-cli",
            &install_script(),
            Some(Duration::from_secs(1800)),
        )?;
    }

    verify_harbor_cli_inner(app, state)?;
    configure_first_run_stack_inner(app, state)?;
    start_first_run_stack_inner(app, state)?;
    verify_first_run_stack_inner(app, state)?;
    drop(guard);
    Ok(detect_harbor_setup_inner(state))
}

pub fn run_setup_smoke(app: AppHandle) -> Result<HarborSetupDetail, String> {
    let state = app.state::<SetupState>();
    start_harbor_setup_inner(&app, &state)
}

pub fn spawn_setup_smoke(app: AppHandle) {
    std::thread::spawn(move || {
        let result = run_setup_smoke(app.clone());
        let ready = result
            .as_ref()
            .map(|detail| detail.status == "ready")
            .unwrap_or(false);
        let exit_code = if ready { 0 } else { 1 };
        let smoke_result = match result {
            Ok(detail) => SetupSmokeResult {
                ok: ready,
                error: if ready {
                    None
                } else {
                    Some(format!("Setup ended with status {}", detail.status))
                },
                detail: Some(detail),
            },
            Err(error) => SetupSmokeResult {
                ok: false,
                detail: None,
                error: Some(error),
            },
        };

        if let Ok(output_path) = std::env::var("HARBOR_APP_SETUP_SMOKE_OUTPUT") {
            if let Ok(json) = serde_json::to_string_pretty(&smoke_result) {
                let _ = fs::write(output_path, json);
            }
        }

        app.exit(exit_code);
    });
}

#[tauri::command]
pub fn cancel_harbor_setup(state: State<'_, SetupState>) -> Result<(), String> {
    if let Ok(mut cancel_requested) = state.cancel_requested.lock() {
        *cancel_requested = true;
    }
    let mut killer = state.current_killer.lock().map_err(|err| err.to_string())?;
    if let Some(killer) = killer.as_mut() {
        killer.kill().map_err(|err| err.to_string())
    } else {
        Ok(())
    }
}

#[tauri::command]
pub fn write_harbor_setup_input(state: State<'_, SetupState>, data: String) -> Result<(), String> {
    let mut writer = state.current_writer.lock().map_err(|err| err.to_string())?;
    let Some(writer) = writer.as_mut() else {
        return Err("Harbor setup is not waiting for input.".into());
    };

    writer
        .write_all(data.as_bytes())
        .and_then(|_| writer.flush())
        .map_err(|err| err.to_string())
}

#[tauri::command]
pub fn verify_harbor_cli(app: AppHandle, state: State<'_, SetupState>) -> Result<(), String> {
    let _guard = acquire_setup_lock(&state)?;
    verify_harbor_cli_inner(&app, &state)
}

fn verify_harbor_cli_inner(app: &AppHandle, state: &SetupState) -> Result<(), String> {
    if platform_name() == "windows" {
        run_logged_wsl_bash(
            app,
            state,
            "verifying-cli",
            "harbor --version && harbor doctor",
            Some(Duration::from_secs(300)),
        )
    } else {
        run_logged_shell(
            app,
            state,
            "verifying-cli",
            &native_harbor_shell("harbor --version && harbor doctor"),
            Some(Duration::from_secs(300)),
        )
    }
}

#[tauri::command]
pub fn configure_first_run_stack(
    app: AppHandle,
    state: State<'_, SetupState>,
) -> Result<(), String> {
    let _guard = acquire_setup_lock(&state)?;
    reset_cancel(&state);
    configure_first_run_stack_inner(&app, &state)
}

fn reset_cancel(state: &SetupState) {
    if let Ok(mut cancel_requested) = state.cancel_requested.lock() {
        *cancel_requested = false;
    }
}

fn check_not_running(state: &SetupState) -> Result<(), String> {
    if state
        .current_pid
        .lock()
        .map(|pid| pid.is_some())
        .unwrap_or(false)
    {
        return Err("Harbor setup is already running.".into());
    }
    Ok(())
}

/// Acquire the setup-wide active lock. Returns an error if another
/// setup chain is already executing. The returned guard must be held
/// for the duration of the setup function — dropping it releases the
/// lock even on error/panic paths.
fn acquire_setup_lock(state: &SetupState) -> Result<SetupActiveGuard<'_>, String> {
    let mut active = state
        .setup_active
        .lock()
        .map_err(|e| format!("setup lock poisoned: {e}"))?;
    if *active {
        return Err("Harbor setup is already in progress.".into());
    }
    *active = true;
    Ok(SetupActiveGuard { state })
}

/// RAII guard that sets `setup_active` back to `false` on drop,
/// ensuring the lock is released even when the function returns
/// early via `?` or panics.
struct SetupActiveGuard<'a> {
    state: &'a SetupState,
}

impl Drop for SetupActiveGuard<'_> {
    fn drop(&mut self) {
        if let Ok(mut active) = self.state.setup_active.lock() {
            *active = false;
        }
    }
}

fn configure_first_run_stack_inner(app: &AppHandle, state: &SetupState) -> Result<(), String> {
    check_not_running(state)?;
    let script = format!(
        "{} && {}",
        harbor_script(&["llamacpp", "model", FIRST_RUN_MODEL]),
        harbor_script(&["models", "pull", "--source", "llamacpp", FIRST_RUN_MODEL])
    );

    if platform_name() == "windows" {
        run_logged_wsl_bash(
            app,
            state,
            "configuring-first-run-stack",
            &script,
            Some(Duration::from_secs(1800)),
        )
    } else {
        run_logged_shell(
            app,
            state,
            "configuring-first-run-stack",
            &native_harbor_shell(&script),
            Some(Duration::from_secs(1800)),
        )
    }
}

#[tauri::command]
pub fn start_first_run_stack(app: AppHandle, state: State<'_, SetupState>) -> Result<(), String> {
    let _guard = acquire_setup_lock(&state)?;
    start_first_run_stack_inner(&app, &state)
}

fn start_first_run_stack_inner(app: &AppHandle, state: &SetupState) -> Result<(), String> {
    check_not_running(state)?;
    let script = harbor_script(&["up", "--no-defaults", "llamacpp", "webui"]);
    if platform_name() == "windows" {
        run_logged_wsl_bash(
            app,
            state,
            "starting-first-run-stack",
            &script,
            Some(Duration::from_secs(1800)),
        )
    } else {
        run_logged_shell(
            app,
            state,
            "starting-first-run-stack",
            &native_harbor_shell(&script),
            Some(Duration::from_secs(1800)),
        )
    }
}

#[tauri::command]
pub fn verify_first_run_stack(app: AppHandle, state: State<'_, SetupState>) -> Result<(), String> {
    let _guard = acquire_setup_lock(&state)?;
    verify_first_run_stack_inner(&app, &state)
}

fn verify_first_run_stack_inner(app: &AppHandle, state: &SetupState) -> Result<(), String> {
    check_not_running(state)?;
    let script = "webui=$(harbor url webui | sed 's#/*$##'); llama=$(harbor url llamacpp | sed 's#/*$##'); \
for i in $(seq 1 120); do curl -fsS --max-time 5 \"$webui\" >/dev/null && curl -fsS --max-time 5 \"$llama/v1/models\" >/dev/null && break; sleep 5; done; \
curl -fsS --max-time 5 \"$webui\" >/dev/null && curl -fsS --max-time 5 \"$llama/v1/models\" >/dev/null || { echo 'HARBOR_SETUP_STAGE=failed'; echo 'Services did not start within the expected time (stack-start-failed)'; exit 1; }; \
home=$(harbor home); config=\"$home/services/webui/config.json\"; \
test -f \"$config\" || { echo 'HARBOR_SETUP_STAGE=failed'; echo 'WebUI backend config not found (webui-backend-config-failed)'; exit 1; }; \
grep -Fq 'http://llamacpp:8080/v1' \"$config\" || { echo 'HARBOR_SETUP_STAGE=failed'; echo 'WebUI is not configured with the llama.cpp backend (webui-backend-config-failed)'; exit 1; }; \
model=$(curl -fsS --max-time 5 \"$llama/v1/models\" | sed -n 's/.*\"id\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p' | head -n1); \
test -n \"$model\" || { echo 'HARBOR_SETUP_STAGE=failed'; echo 'No models found on the llama.cpp server (verifying-inference)'; exit 1; }; \
curl -fsS --max-time 120 -H 'Content-Type: application/json' -d \"{\\\"model\\\":\\\"$model\\\",\\\"messages\\\":[{\\\"role\\\":\\\"user\\\",\\\"content\\\":\\\"Say ready.\\\"}],\\\"max_tokens\\\":8}\" \"$llama/v1/chat/completions\" | grep -q 'choices' || { echo 'HARBOR_SETUP_STAGE=failed'; echo 'Inference verification failed - llama.cpp did not return a valid response (verifying-inference)'; exit 1; }";
    if platform_name() == "windows" {
        run_logged_wsl_bash(
            app,
            state,
            "verifying-inference",
            script,
            Some(Duration::from_secs(900)),
        )
    } else {
        run_logged_shell(
            app,
            state,
            "verifying-inference",
            &native_harbor_shell(script),
            Some(Duration::from_secs(900)),
        )
    }
}

#[tauri::command]
pub fn open_webui(app: AppHandle) -> Result<(), String> {
    let url = run_harbor(&["url", "webui"]);
    if url.code != Some(0) {
        return Err(short_error(&url).unwrap_or_else(|| "Unable to resolve Open WebUI URL.".into()));
    }

    let url = url.stdout.trim();
    if url.is_empty() {
        return Err("Harbor returned an empty Open WebUI URL.".into());
    }

    emit_stage(&app, "ready");
    emit_log(&app, "ready", "stdout", &format!("Opening {url}"));
    let opened = open_host_url(url);
    if opened.code == Some(0) {
        Ok(())
    } else {
        Err(short_error(&opened).unwrap_or_else(|| "Unable to open Open WebUI URL.".into()))
    }
}
