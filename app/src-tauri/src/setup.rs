use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, ExitStatus, PtySize};
use serde::Serialize;
use std::{
    env,
    ffi::OsString,
    fs,
    io::{Read, Write},
    path::PathBuf,
    process::{ChildStderr, ChildStdout, Command, Stdio},
    sync::{Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, State};

const HARBOR_INSTALL_URL: &str =
    "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh";
const HARBOR_WINDOWS_INSTALL_URL: &str =
    "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.ps1";
const DETECT_TIMEOUT: Duration = Duration::from_secs(15);
const PANIC_RECOVERY_MESSAGE: &str =
    "An unexpected internal error occurred during setup. Please try again, and if the problem persists, report it at github.com/av/harbor/issues";

#[derive(Default)]
pub struct SetupState {
    current_pid: Mutex<Option<u32>>,
    current_killer: Mutex<Option<Box<dyn ChildKiller + Send + Sync>>>,
    current_writer: Mutex<Option<Box<dyn Write + Send>>>,
    cancel_requested: Mutex<bool>,
    setup_active: Mutex<bool>,
    current_stage: Arc<Mutex<Option<String>>>,
}

impl SetupState {
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
    pub cli_version: Option<String>,
    pub last_error: Option<String>,
    pub running: bool,
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

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupCompleteEvent {
    detail: HarborSetupDetail,
    error: Option<String>,
}

#[allow(dead_code)]
struct ProcessOutput {
    code: Option<i32>,
    stdout: String,
    stderr: String,
}

/// Structured error from `run_logged` / `run_logged_shell`.
///
/// Replaces the previous pattern of encoding status into the error
/// string as `"HARBOR_SETUP_STATUS=<status>; <message>"` and parsing
/// it back at the call site.
struct SetupError {
    /// Terminal status to emit (e.g. "cancelled", "failed", "blocked").
    status: String,
    /// Human-readable error message.
    message: String,
}

impl SetupError {
    fn failed(message: String) -> Self {
        Self { status: "failed".into(), message }
    }
}

/// Shared mutable state threaded through `emit_process_line` /
/// `emit_process_chunk` during a PTY read loop.
struct ProcessLineState {
    marker: Arc<Mutex<Option<String>>>,
    current_stage: Arc<Mutex<Option<String>>>,
    last_line: Arc<Mutex<Option<String>>>,
}

// ── Platform utilities ─────────────────────────────────

fn platform_name() -> &'static str {
    std::env::consts::OS
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
    "export PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH\"; if ! command -v harbor >/dev/null 2>&1 && test -x \"${HARBOR_HOME:-$HOME/.harbor}/harbor.sh\"; then function harbor() { \"${HARBOR_HOME:-$HOME/.harbor}/harbor.sh\" \"$@\"; }; fi"
}

// ── Process execution ──────────────────────────────────

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

fn collect_readers(
    stdout_reader: Option<std::thread::JoinHandle<String>>,
    stderr_reader: Option<std::thread::JoinHandle<String>>,
) -> (String, String) {
    let stdout = stdout_reader
        .and_then(|r| r.join().ok())
        .unwrap_or_default();
    let stderr = stderr_reader
        .and_then(|r| r.join().ok())
        .unwrap_or_default();
    (stdout, stderr)
}

fn run_capture_timeout(program: &str, args: &[&str], timeout: Duration) -> ProcessOutput {
    let mut command = Command::new(program);
    command.args(args);
    if platform_name() != "windows" {
        if let Some(path) = native_command_path() {
            command.env("PATH", path);
        }
    }

    match command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(mut child) => {
            let stdout_reader = child
                .stdout
                .take()
                .map(|r: ChildStdout| spawn_output_reader(r));
            let stderr_reader = child
                .stderr
                .take()
                .map(|r: ChildStderr| spawn_output_reader(r));
            let started = Instant::now();
            loop {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        let (stdout, stderr) =
                            collect_readers(stdout_reader, stderr_reader);
                        return ProcessOutput {
                            code: status.code(),
                            stdout,
                            stderr,
                        };
                    }
                    Ok(None) => {
                        if started.elapsed() > timeout {
                            let _ = child.kill();
                            let _ = child.wait();
                            let (stdout, stderr) =
                                collect_readers(stdout_reader, stderr_reader);
                            return ProcessOutput {
                                code: Some(124),
                                stdout,
                                stderr: format!(
                                    "{}{}{} timed out after {}s",
                                    stderr,
                                    if stderr.is_empty() { "" } else { "\n" },
                                    program,
                                    timeout.as_secs()
                                ),
                            };
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                    Err(err) => {
                        // try_wait failed at the OS level.  Kill and
                        // reap the child so we don't leak it, then
                        // join the reader threads to avoid dangling
                        // background threads.
                        let _ = child.kill();
                        let _ = child.wait();
                        let (stdout, stderr) =
                            collect_readers(stdout_reader, stderr_reader);
                        return ProcessOutput {
                            code: Some(127),
                            stdout,
                            stderr: format!(
                                "{}{}{}",
                                err,
                                if stderr.is_empty() { "" } else { "\n" },
                                stderr,
                            ),
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
}

fn run_shell_timeout(script: &str, timeout: Duration) -> ProcessOutput {
    if platform_name() == "windows" {
        run_capture_timeout(
            "powershell.exe",
            &["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout,
        )
    } else {
        run_capture_timeout("bash", &["-lc", script], timeout)
    }
}

// ── WSL support ────────────────────────────────────────

fn selected_wsl_distro() -> Option<String> {
    std::env::var("HARBOR_WSL_DISTRO")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
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
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
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

/// Supported WSL distro prefixes for auto-detection, in preference order.
/// Ubuntu is preferred because install.ps1 installs it by default.
const WSL_DISTRO_PREFIXES: &[&str] = &["Ubuntu", "Debian", "Fedora", "openSUSE", "Kali", "Arch"];

/// Strip null bytes and BOM from `wsl.exe` output.  WSL emits UTF-16LE
/// with a BOM, which after lossy UTF-8 conversion leaves stray `\0` and
/// `\u{FEFF}` characters that break line parsing.
fn clean_wsl_output(output: &str) -> String {
    output.replace('\0', "").replace('\u{FEFF}', "")
}

fn parse_wsl2_supported_distro(
    output: &str,
    running_names: Option<&[String]>,
) -> Option<String> {
    let cleaned = clean_wsl_output(output);
    for prefix in WSL_DISTRO_PREFIXES {
        for line in cleaned.lines() {
            let parts = line.split_whitespace().collect::<Vec<_>>();
            if parts.is_empty() {
                continue;
            }
            let name_index = if parts.first() == Some(&"*") { 1 } else { 0 };
            // Use the last element as the version column.  Non-English
            // Windows locales can produce multi-word state names (e.g.
            // German "Wird ausgeführt" for "Running"), which shifts the
            // column layout when using split_whitespace.
            let Some(name) = parts.get(name_index) else { continue };
            let Some(version) = parts.last() else { continue };
            // Need at least one state token between name and version.
            if parts.len() <= name_index + 2 {
                continue;
            }
            if name.starts_with(prefix)
                && *version == "2"
                && running_names
                    .map(|names| names.iter().any(|n| n == name))
                    .unwrap_or(true)
            {
                return Some((*name).to_string());
            }
        }
    }
    None
}

/// Parse the output of `wsl.exe --list --running` into a list of distro names.
/// This output is locale-independent (just names, no state/version columns),
/// so it avoids the localized "Running" detection problem.
///
/// The `--list` (non-verbose) format may include a "(Default)" suffix
/// after the name, so we strip everything from the first `(` onward.
fn parse_running_distro_names(output: &str) -> Vec<String> {
    let cleaned = clean_wsl_output(output);
    cleaned
        .lines()
        .skip(1) // skip the header line ("Windows Subsystem for Linux Distributions:")
        .filter_map(|line| {
            let trimmed = line.trim().trim_start_matches('*').trim();
            if trimmed.is_empty() {
                return None;
            }
            // Strip "(Default)" or any other parenthetical suffix.
            let name = trimmed.split('(').next().unwrap_or(trimmed).trim();
            if name.is_empty() {
                None
            } else {
                Some(name.to_string())
            }
        })
        .collect()
}

fn parse_wsl_distro_exists(output: &str, distro: &str) -> bool {
    clean_wsl_output(output).lines().any(|line| {
        let parts = line.split_whitespace().collect::<Vec<_>>();
        if parts.is_empty() {
            return false;
        }
        let name_index = if parts.first() == Some(&"*") { 1 } else { 0 };
        // Use the last element as the version column to handle
        // multi-word localized state names.
        parts.get(name_index) == Some(&distro) && parts.last() == Some(&"2")
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
    let distros = run_capture_timeout("wsl.exe", &["--list", "--verbose"], DETECT_TIMEOUT);
    if distros.code != Some(0) {
        return None;
    }
    if let Some(distro) = read_stored_wsl_distro() {
        if parse_wsl_distro_exists(&distros.stdout, &distro) {
            return Some(distro);
        }
    }
    // Use `--list --running` for locale-independent detection of running
    // distros.  The `--list --verbose` state column is localized (e.g.
    // German "Wird ausgeführt"), so matching the English word "Running"
    // fails on non-English Windows.
    let running_output =
        run_capture_timeout("wsl.exe", &["--list", "--running"], DETECT_TIMEOUT);
    let running_names = if running_output.code == Some(0) {
        parse_running_distro_names(&running_output.stdout)
    } else {
        Vec::new()
    };
    let distro = parse_wsl2_supported_distro(&distros.stdout, Some(&running_names))
        .or_else(|| parse_wsl2_supported_distro(&distros.stdout, None));
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

fn run_wsl_bash_timeout(script: &str, timeout: Duration) -> ProcessOutput {
    let args = wsl_bash_args(script);
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    run_capture_timeout("wsl.exe", &arg_refs, timeout)
}

// ── Emit helpers ───────────────────────────────────────

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

fn emit_setup_failure(app: &AppHandle, status: &str, message: &str) {
    emit_stage(app, status);
    let _ = app.emit(
        "harbor-setup-complete",
        SetupCompleteEvent {
            detail: HarborSetupDetail {
                status: status.into(),
                platform: platform_name().into(),
                cli_version: None,
                last_error: Some(message.into()),
                running: false,
            },
            error: Some(message.into()),
        },
    );
}

fn parse_setup_stage_marker(line: &str) -> Option<String> {
    line.trim()
        .strip_prefix("HARBOR_SETUP_STAGE=")
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

fn emit_process_line(
    app: &AppHandle,
    stage: &str,
    stream: &str,
    line: &str,
    pls: &ProcessLineState,
) {
    if let Ok(mut last) = pls.last_line.lock() {
        *last = Some(line.trim().to_string());
    }
    if let Some(marker) = parse_setup_stage_marker(line) {
        emit_stage(app, &marker);
        if let Ok(mut current) = pls.marker.lock() {
            *current = Some(marker.clone());
        }
        if let Ok(mut stage_lock) = pls.current_stage.lock() {
            *stage_lock = Some(marker);
        }
    }
    emit_log(app, stage, stream, line);
}

fn emit_process_chunk(
    app: &AppHandle,
    stage: &str,
    stream: &str,
    chunk: &str,
    pls: &ProcessLineState,
    line_buffer: &mut String,
) {
    emit_terminal_output(app, chunk);
    for ch in chunk.chars() {
        if ch == '\n' || ch == '\r' {
            let line = line_buffer.trim_end_matches('\r');
            if !line.trim().is_empty() {
                emit_process_line(app, stage, stream, line, pls);
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

// ── State management ───────────────────────────────────

fn setup_is_active(state: &SetupState) -> bool {
    state
        .setup_active
        .lock()
        .map(|a| *a)
        .unwrap_or(false)
}

fn set_current_stage(state: &SetupState, stage: &str) {
    if let Ok(mut s) = state.current_stage.lock() {
        *s = Some(stage.to_string());
    }
}

fn current_setup_stage(state: &SetupState) -> String {
    state
        .current_stage
        .lock()
        .ok()
        .and_then(|s| s.clone())
        .unwrap_or_else(|| "checking".into())
}

fn clear_running_state(state: &SetupState, reset_cancel: bool) {
    if let Ok(mut pid) = state.current_pid.lock() {
        *pid = None;
    }
    if let Ok(mut killer) = state.current_killer.lock() {
        *killer = None;
    }
    if let Ok(mut writer) = state.current_writer.lock() {
        *writer = None;
    }
    if reset_cancel {
        if let Ok(mut cancel) = state.cancel_requested.lock() {
            *cancel = false;
        }
    }
}

fn reset_cancel(state: &SetupState) {
    if let Ok(mut c) = state.cancel_requested.lock() {
        *c = false;
    }
}

// ── PTY execution ──────────────────────────────────────

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
) -> Result<(), SetupError> {
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
        .map_err(|e| SetupError::failed(e.to_string()))?;
    let mut command = CommandBuilder::new(program);
    command.args(args);
    command.env("TERM", "xterm-256color");
    command.env("HARBOR_APP", "1");
    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| SetupError::failed(e.to_string()))?;
    let writer = pair.master.take_writer().map_err(|e| SetupError::failed(e.to_string()))?;
    let mut child = pair
        .slave
        .spawn_command(command)
        .map_err(|e| SetupError::failed(e.to_string()))?;

    if state
        .cancel_requested
        .lock()
        .map(|c| *c)
        .unwrap_or(false)
    {
        let _ = child.kill();
        let _ = child.wait();
        clear_running_state(state, true);
        return Err(SetupError {
            status: "cancelled".into(),
            message: format!("{stage} cancelled"),
        });
    }

    let pid = child.process_id().unwrap_or(0);
    if let Ok(mut p) = state.current_pid.lock() {
        *p = Some(pid);
    }
    if let Ok(mut k) = state.current_killer.lock() {
        *k = Some(child.clone_killer());
    }
    if let Ok(mut w) = state.current_writer.lock() {
        *w = Some(writer);
    }

    let pls = ProcessLineState {
        marker: Arc::new(Mutex::new(None)),
        current_stage: state.current_stage.clone(),
        last_line: Arc::new(Mutex::new(None)),
    };
    let reader_app = app.clone();
    let reader_stage = stage.to_string();
    let reader_pls = ProcessLineState {
        marker: pls.marker.clone(),
        current_stage: pls.current_stage.clone(),
        last_line: pls.last_line.clone(),
    };
    let reader_thread = std::thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        let mut line_buffer = String::new();
        // Carry-over buffer for incomplete multi-byte UTF-8 sequences
        // split across read boundaries.
        let mut utf8_carry: Vec<u8> = Vec::new();
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(size) => {
                    utf8_carry.extend_from_slice(&buffer[..size]);
                    let valid_end = match std::str::from_utf8(&utf8_carry) {
                        Ok(_) => utf8_carry.len(),
                        Err(e) => {
                            let valid = e.valid_up_to();
                            if let Some(len) = e.error_len() {
                                valid + len
                            } else {
                                valid
                            }
                        }
                    };
                    if valid_end > 0 {
                        let chunk =
                            String::from_utf8_lossy(&utf8_carry[..valid_end]).to_string();
                        emit_process_chunk(
                            &reader_app,
                            &reader_stage,
                            "pty",
                            &chunk,
                            &reader_pls,
                            &mut line_buffer,
                        );
                    }
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
        if !utf8_carry.is_empty() {
            let chunk = String::from_utf8_lossy(&utf8_carry).to_string();
            emit_process_chunk(
                &reader_app,
                &reader_stage,
                "pty",
                &chunk,
                &reader_pls,
                &mut line_buffer,
            );
        }
        if !line_buffer.trim().is_empty() {
            emit_process_line(
                &reader_app,
                &reader_stage,
                "pty",
                &line_buffer,
                &reader_pls,
            );
        }
    });

    let started = Instant::now();
    let wait_result: Result<ExitStatus, SetupError> = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => {
                if timeout
                    .map(|limit| started.elapsed() > limit)
                    .unwrap_or(false)
                {
                    let _ = child.kill();
                    // Reap the child to prevent zombies.  After kill()
                    // (SIGHUP on Unix, TerminateProcess on Windows) the
                    // process should exit quickly.
                    let _ = child.wait();
                    break Err(SetupError::failed(format!("{stage} timed out")));
                }
                std::thread::sleep(Duration::from_millis(250));
            }
            Err(err) => {
                // try_wait failed at the OS level.  Kill and reap so we
                // don't leak a zombie or leave the process running.
                let _ = child.kill();
                let _ = child.wait();
                break Err(SetupError::failed(err.to_string()));
            }
        }
    };

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
        .map(|mut c| {
            let was = *c;
            *c = false;
            was
        })
        .unwrap_or(false);

    // Check success BEFORE cancel: if the process completed successfully
    // before the kill signal arrived, honour the success.  Otherwise a
    // last-instant cancel races with normal completion and the user sees
    // "cancelled" even though the install finished.
    if status.success() {
        Ok(())
    } else if was_cancelled {
        Err(SetupError {
            status: "cancelled".into(),
            message: format!("{stage} cancelled"),
        })
    } else {
        let terminal_marker = pls.marker
            .lock()
            .ok()
            .and_then(|m| m.clone())
            .filter(|m| marker_is_terminal(m));

        if let Some(marker) = terminal_marker {
            let last_output = pls.last_line
                .lock()
                .ok()
                .and_then(|l| l.clone())
                .filter(|l| {
                    !parse_setup_stage_marker(l)
                        .as_deref()
                        .is_some_and(|s| s == marker)
                });

            let detail = last_output
                .map(|l| format!("; {l}"))
                .unwrap_or_default();

            return Err(SetupError {
                status: marker,
                message: format!(
                    "{stage} exited with code {}{detail}",
                    format_pty_exit(&status),
                ),
            });
        }

        Err(SetupError::failed(format!(
            "{stage} exited with code {}",
            format_pty_exit(&status)
        )))
    }
}

fn run_logged_shell(
    app: &AppHandle,
    state: &SetupState,
    stage: &str,
    script: &str,
    timeout: Option<Duration>,
) -> Result<(), SetupError> {
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

// ── Install scripts ────────────────────────────────────

fn install_script() -> String {
    if let Ok(local) = std::env::var("HARBOR_APP_INSTALL_SCRIPT") {
        format!("bash {}", shell_quote(&local))
    } else {
        format!(
            "curl -fsSL --connect-timeout 15 --max-time 60 {} | bash",
            shell_quote(HARBOR_INSTALL_URL)
        )
    }
}

fn windows_install_script(distro: Option<&str>) -> String {
    let distro_prefix = distro
        .map(|d| format!("$env:HARBOR_WSL_DISTRO = {}; ", powershell_quote(d)))
        .unwrap_or_default();

    if let Ok(local) = std::env::var("HARBOR_APP_WINDOWS_INSTALL_SCRIPT") {
        let distro_arg = distro
            .map(|d| format!(" -Distro {}", powershell_quote(d)))
            .unwrap_or_default();
        format!(
            "{}& {}{}",
            distro_prefix,
            powershell_quote(&local),
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

// ── Detection ──────────────────────────────────────────

fn detect_windows_blocker(detail: &mut HarborSetupDetail) -> bool {
    let wsl_status = run_capture_timeout("wsl.exe", &["--status"], DETECT_TIMEOUT);
    if wsl_status.code != Some(0) {
        detail.status = "blocked".into();
        detail.last_error =
            Some("Windows Subsystem for Linux is not available.".into());
        return true;
    }

    let distros = run_capture_timeout(
        "wsl.exe",
        &["--list", "--verbose"],
        DETECT_TIMEOUT,
    );
    if distros.code != Some(0) {
        detail.status = "blocked".into();
        detail.last_error =
            Some("No WSL2 distro is available. Install one with: wsl --install -d Ubuntu".into());
        return true;
    }

    if let Some(distro) = selected_wsl_distro() {
        if !parse_wsl_distro_exists(&distros.stdout, &distro) {
            detail.status = "blocked".into();
            detail.last_error =
                Some(format!("Selected WSL distro '{distro}' is not a WSL2 distro or is not installed."));
            return true;
        }
    } else if preferred_wsl_distro().is_none() {
        detail.status = "blocked".into();
        detail.last_error =
            Some("No supported WSL2 distro found (Ubuntu, Debian, Fedora, openSUSE, Kali, Arch). Install one with: wsl --install -d Ubuntu, or set HARBOR_WSL_DISTRO to use a custom distro.".into());
        return true;
    }

    false
}

/// Run the full detection logic, ignoring whether setup is active.
/// Used internally after a successful install to verify the CLI is available.
fn detect_harbor_status() -> HarborSetupDetail {
    let platform = platform_name();
    let mut detail = HarborSetupDetail {
        status: "checking".into(),
        platform: platform.into(),
        cli_version: None,
        last_error: None,
        running: false,
    };
    detect_harbor_status_core(platform, &mut detail);
    detail
}

fn detect_harbor_setup_inner(state: &SetupState) -> HarborSetupDetail {
    let running = setup_is_active(state)
        || state
            .current_pid
            .lock()
            .map(|pid| pid.is_some())
            .unwrap_or(false);
    let platform = platform_name();

    let mut detail = HarborSetupDetail {
        status: "checking".into(),
        platform: platform.into(),
        cli_version: None,
        last_error: None,
        running,
    };

    if running {
        detail.status = current_setup_stage(state);
        return detail;
    }

    detect_harbor_status_core(platform, &mut detail);
    detail
}

fn detect_harbor_status_core(platform: &str, detail: &mut HarborSetupDetail) {
    match platform {
        "linux" => {
            let check = run_shell_timeout(
                "command -v apt-get >/dev/null || command -v dnf >/dev/null || command -v pacman >/dev/null || command -v apk >/dev/null || command -v zypper >/dev/null",
                DETECT_TIMEOUT,
            );
            if check.code != Some(0) {
                detail.status = "blocked".into();
                detail.last_error = Some(
                    "No supported package manager found (apt, dnf, pacman, apk, or zypper). Harbor needs a package manager to install Docker and other dependencies. Install one of these, or install Docker manually and retry.".into(),
                );
                return;
            }
        }
        "macos" => {
            // On macOS, Docker Desktop must be installed separately (the install
            // script cannot install it non-interactively). Detect early so users
            // get actionable guidance instead of a cryptic install failure.
            let docker_check = run_shell_timeout(
                "command -v docker >/dev/null 2>&1",
                DETECT_TIMEOUT,
            );
            if docker_check.code != Some(0) {
                detail.status = "blocked".into();
                detail.last_error = Some(
                    "Docker is not installed. Please install Docker Desktop for Mac from https://docker.com/products/docker-desktop before setting up Harbor.".into(),
                );
                return;
            }
        }
        "windows" => {}
        _ => {
            detail.status = "blocked".into();
            detail.last_error = Some(format!("Unsupported platform: {platform}. Harbor supports Linux, macOS, and Windows (via WSL2)."));
            return;
        }
    }

    if platform == "windows" && detect_windows_blocker(detail) {
        return;
    }

    let version = if platform == "windows" {
        run_wsl_bash_timeout(
            "command -v harbor >/dev/null && harbor --version",
            DETECT_TIMEOUT,
        )
    } else {
        run_shell_timeout(
            &format!(
                "{}; command -v harbor >/dev/null && harbor --version",
                native_harbor_prelude()
            ),
            DETECT_TIMEOUT,
        )
    };

    if version.code == Some(0) {
        detail.status = "ready".into();
        // `harbor --version` outputs "Harbor CLI version: X.Y.Z".
        // Use the last non-empty line to skip login-shell noise (MOTD,
        // profile banners) that may precede the version output.
        // Strip the "Harbor CLI version: " prefix so the UI (which already
        // displays a "CLI version:" label) doesn't show a doubled prefix.
        let raw = version.stdout.trim().to_string();
        let last_line = raw
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or(&raw)
            .trim();
        let cleaned = last_line
            .strip_prefix("Harbor CLI version: ")
            .or_else(|| last_line.strip_prefix("Harbor CLI version:"))
            .unwrap_or(last_line)
            .trim();
        detail.cli_version = Some(cleaned.to_string());
        return;
    }

    if platform != "windows" {
        let exists = run_shell_timeout(
            "test -e \"$HOME/.local/bin/harbor\" -o -x \"$HOME/.harbor/harbor.sh\"",
            DETECT_TIMEOUT,
        );
        if exists.code == Some(0) {
            detail.status = "refresh-required".into();
            detail.last_error = Some(
                "Harbor is installed but not in PATH. Close and reopen this app, or open a new terminal and run 'harbor doctor' to verify.".into(),
            );
            return;
        }
    }

    detail.status = "not-installed".into();
}

// ── Tauri commands ─────────────────────────────────────

#[tauri::command]
pub fn detect_harbor_setup(state: State<'_, SetupState>) -> HarborSetupDetail {
    clear_wsl_distro_cache();
    detect_harbor_setup_inner(&state)
}

#[tauri::command]
pub fn get_harbor_wsl_distro() -> Option<String> {
    if platform_name() == "windows" {
        preferred_wsl_distro()
    } else {
        None
    }
}

#[tauri::command]
pub fn start_harbor_setup(
    app: AppHandle,
    state: State<'_, SetupState>,
) -> Result<(), String> {
    {
        let mut active = match state.setup_active.lock() {
            Ok(guard) => guard,
            // Recover from a mutex poisoned by a prior thread panic.
            // The cleanup code resets the value, but if the panic
            // occurred before cleanup ran, clear the poison here so
            // the user can retry without restarting the app.
            Err(e) => e.into_inner(),
        };
        if *active {
            return Err("Harbor setup is already in progress.".into());
        }
        *active = true;
    }
    reset_cancel(&state);

    // Set initial stage so that redetect() during thread startup
    // returns a meaningful status instead of stale "checking".
    set_current_stage(&state, "starting");

    std::thread::spawn(move || {
        let state: State<'_, SetupState> = app.state();

        // Wrap the entire body in catch_unwind so that setup_active is
        // always released, even if detect_harbor_status() or emit() panic.
        // Without this, an uncaught panic leaves setup_active=true
        // permanently, making the "Install" button non-functional until
        // the app is restarted.
        let outer = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                if platform_name() == "windows" {
                    let distro = preferred_wsl_distro();
                    run_logged_shell(
                        &app,
                        &state,
                        "installing-cli",
                        &windows_install_script(distro.as_deref()),
                        Some(Duration::from_secs(1800)),
                    )
                } else {
                    run_logged_shell(
                        &app,
                        &state,
                        "installing-cli",
                        &install_script(),
                        Some(Duration::from_secs(1800)),
                    )
                }
            }));

            // Emit the complete event BEFORE releasing setup_active, so that
            // any concurrent redetect() still sees the process as running and
            // doesn't report a stale intermediate state.
            match result {
                Ok(Ok(())) => {
                    // Use detect_harbor_status() which skips the setup_active
                    // check (still true at this point) and runs full detection.
                    let detail = detect_harbor_status();
                    emit_stage(&app, &detail.status);
                    let _ = app.emit(
                        "harbor-setup-complete",
                        SetupCompleteEvent {
                            detail,
                            error: None,
                        },
                    );
                }
                Ok(Err(e)) => {
                    emit_setup_failure(&app, &e.status, &e.message);
                }
                Err(_panic) => {
                    emit_setup_failure(
                        &app,
                        "failed",
                        PANIC_RECOVERY_MESSAGE,
                    );
                }
            }
        }));

        // If the outer catch_unwind caught a panic (from detect_harbor_status
        // or emit calls), try to emit a last-ditch failed event.
        if outer.is_err() {
            emit_setup_failure(
                &app,
                "failed",
                PANIC_RECOVERY_MESSAGE,
            );
        }

        // Release the lock after emitting complete event.
        // The guard must be dropped before `state` (which borrows `app`).
        // This runs unconditionally — even after panics — because the
        // outer catch_unwind prevents unwinding past this point.
        let _ = match state.setup_active.lock() {
            Ok(mut active) => { *active = false; }
            Err(e) => {
                // Mutex was poisoned by a prior panic. Clear the poison
                // and release the lock so setup can be retried.
                let mut active = e.into_inner();
                *active = false;
            }
        };
    });

    Ok(())
}

#[tauri::command]
pub fn cancel_harbor_setup(state: State<'_, SetupState>) -> Result<(), String> {
    // Only set cancel_requested if setup is actually active.
    // Otherwise a stray cancel could poison the next start_harbor_setup call.
    if !setup_is_active(&state) {
        return Ok(());
    }
    if let Ok(mut cancel) = state.cancel_requested.lock() {
        *cancel = true;
    }
    let mut killer = state
        .current_killer
        .lock()
        .map_err(|e| e.to_string())?;
    if let Some(killer) = killer.as_mut() {
        killer.kill().map_err(|e| e.to_string())
    } else {
        Ok(())
    }
}

#[tauri::command]
pub fn write_harbor_setup_input(
    state: State<'_, SetupState>,
    data: String,
) -> Result<(), String> {
    let mut writer = state
        .current_writer
        .lock()
        .map_err(|e| e.to_string())?;
    let Some(writer) = writer.as_mut() else {
        return Err("No active setup process is running. Input can only be sent while installation is in progress.".into());
    };
    writer
        .write_all(data.as_bytes())
        .and_then(|_| writer.flush())
        .map_err(|e| e.to_string())
}
