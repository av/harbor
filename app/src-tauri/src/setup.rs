use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, ExitStatus, PtySize};
use serde::Serialize;
use std::{
    env,
    ffi::OsString,
    fs,
    io::{Read, Write},
    path::PathBuf,
    process::{ChildStdout, Command, Stdio},
    sync::{Arc, Mutex, OnceLock},
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, State};

const HARBOR_INSTALL_URL: &str =
    "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.sh";
const HARBOR_WINDOWS_INSTALL_URL: &str =
    "https://raw.githubusercontent.com/av/harbor/refs/heads/main/install.ps1";
const DETECT_TIMEOUT: Duration = Duration::from_secs(15);
// Cold WSL VM boot after Windows startup can exceed 15s; commands that run
// inside the distro (via wsl bash -c) need a longer ceiling.
const WSL_COMMAND_TIMEOUT: Duration = Duration::from_secs(60);
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
        let pid = self.current_pid.lock().ok().and_then(|g| *g);
        kill_process_tree(pid);
        if let Ok(mut killer) = self.current_killer.lock() {
            if let Some(killer) = killer.as_mut() {
                let _ = killer.kill();
            }
            *killer = None;
        }
    }
}

/// On Windows, kill the process tree rooted at `pid` via `taskkill /T /F`.
/// On other platforms this is a no-op (the PTY SIGHUP propagates to the group).
fn kill_process_tree(pid: Option<u32>) {
    #[cfg(target_os = "windows")]
    if let Some(pid) = pid {
        use std::process::{Command, Stdio};
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(not(target_os = "windows"))]
    let _ = pid;
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

impl HarborSetupDetail {
    fn checking() -> Self {
        Self {
            status: "checking".into(),
            platform: platform_name().into(),
            cli_version: None,
            last_error: None,
            running: false,
        }
    }
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

struct ProcessOutput {
    code: Option<i32>,
    stdout: String,
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
#[derive(Clone)]
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

fn join_reader(reader: Option<std::thread::JoinHandle<String>>) -> String {
    reader.and_then(|r| r.join().ok()).unwrap_or_default()
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
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(mut child) => {
            let stdout_reader = child
                .stdout
                .take()
                .map(|r: ChildStdout| spawn_output_reader(r));
            let started = Instant::now();
            loop {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        return ProcessOutput {
                            code: status.code(),
                            stdout: join_reader(stdout_reader),
                        };
                    }
                    Ok(None) => {
                        if started.elapsed() > timeout {
                            let _ = child.kill();
                            let _ = child.wait();
                            // Don't join the reader: grandchildren can hold
                            // the pipe's write end open after the child is
                            // killed, blocking read_to_end forever.  Stdout
                            // is unused on failure codes anyway.
                            drop(stdout_reader);
                            return ProcessOutput {
                                code: Some(124),
                                stdout: String::new(),
                            };
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                    Err(_) => {
                        // try_wait failed at the OS level.  Kill and reap
                        // the child so we don't leak it; detach the reader
                        // for the same grandchild-pipe reason as above.
                        let _ = child.kill();
                        let _ = child.wait();
                        drop(stdout_reader);
                        return ProcessOutput {
                            code: Some(127),
                            stdout: String::new(),
                        };
                    }
                }
            }
        }
        Err(_) => ProcessOutput {
            code: Some(127),
            stdout: String::new(),
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
        // Need at least one state token between name and version,
        // matching the guard in parse_wsl2_supported_distro.
        if parts.len() <= name_index + 2 {
            return false;
        }
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
                last_error: Some(message.into()),
                ..HarborSetupDetail::checking()
            },
            error: Some(message.into()),
        },
    );
}

/// Strip ANSI escape sequences from `line` so stored error messages are clean.
///
/// Handles:
/// - CSI sequences: `ESC [ <params> <final-byte>` (colors, cursor movement)
/// - OSC sequences: `ESC ] <anything> BEL` or `ESC ] <anything> ESC \`
/// - Two-character ESC sequences: `ESC <any single non-`[`/`]` char>`
/// - Bare control characters (< 0x20, excluding \t) and BEL (\x07)
fn strip_ansi(line: &str) -> String {
    #[derive(PartialEq)]
    enum State {
        Normal,
        Esc,
        Csi,
        Osc,
        OscEsc,
    }

    let mut out = String::with_capacity(line.len());
    let mut state = State::Normal;

    for ch in line.chars() {
        match state {
            State::Normal => {
                if ch == '\x1b' {
                    state = State::Esc;
                } else if ch == '\x07' || (ch < '\x20' && ch != '\t' && ch != '\n' && ch != '\r') {
                    // skip bare control chars (BEL, etc.)
                } else {
                    out.push(ch);
                }
            }
            State::Esc => {
                if ch == '[' {
                    state = State::Csi;
                } else if ch == ']' {
                    state = State::Osc;
                } else {
                    // Two-char ESC sequence — consume the second char and return.
                    state = State::Normal;
                }
            }
            State::Csi => {
                // CSI ends at any byte in 0x40–0x7E.
                if ch >= '@' && ch <= '~' {
                    state = State::Normal;
                }
                // Otherwise consume parameter/intermediate bytes.
            }
            State::Osc => {
                if ch == '\x07' {
                    // BEL terminates OSC.
                    state = State::Normal;
                } else if ch == '\x1b' {
                    // ESC may start the ST terminator (`ESC \`).
                    state = State::OscEsc;
                }
                // Otherwise consume OSC data.
            }
            State::OscEsc => {
                // Expect `\` as the second byte of ST; either way, OSC is done.
                state = State::Normal;
            }
        }
    }

    out
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
    line: &str,
    pls: &ProcessLineState,
) {
    let clean = strip_ansi(line.trim()).trim().to_string();
    if let Ok(mut last) = pls.last_line.lock() {
        *last = Some(clean.clone());
    }
    if let Some(marker) = parse_setup_stage_marker(&clean) {
        emit_stage(app, &marker);
        if let Ok(mut current) = pls.marker.lock() {
            *current = Some(marker.clone());
        }
        if let Ok(mut stage_lock) = pls.current_stage.lock() {
            *stage_lock = Some(marker);
        }
    }
}

fn emit_process_chunk(
    app: &AppHandle,
    chunk: &str,
    pls: &ProcessLineState,
    line_buffer: &mut String,
) {
    emit_terminal_output(app, chunk);
    for ch in chunk.chars() {
        if ch == '\n' || ch == '\r' {
            let line = line_buffer.trim_end_matches('\r');
            if !line.trim().is_empty() {
                emit_process_line(app, line, pls);
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
    timeout: Duration,
) -> Result<(), SetupError> {
    set_current_stage(state, stage);
    emit_stage(app, stage);
    let command_line = format!("$ {} {}", program, args.join(" "));
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
            message: format!("Setup cancelled during '{stage}'"),
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

    // Re-check after registration: a cancel that arrived between the first
    // check and killer registration would have found killer=None and no-op'd.
    // Now that the killer is registered, we can honour it.
    if state
        .cancel_requested
        .lock()
        .map(|c| *c)
        .unwrap_or(false)
    {
        if let Ok(mut k) = state.current_killer.lock() {
            if let Some(k) = k.as_mut() {
                let _ = k.kill();
            }
        }
        let _ = child.wait();
        clear_running_state(state, true);
        return Err(SetupError {
            status: "cancelled".into(),
            message: format!("Setup cancelled during '{stage}'"),
        });
    }

    let pls = ProcessLineState {
        marker: Arc::new(Mutex::new(None)),
        current_stage: state.current_stage.clone(),
        last_line: Arc::new(Mutex::new(None)),
    };
    let reader_app = app.clone();
    let reader_pls = pls.clone();
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
                &chunk,
                &reader_pls,
                &mut line_buffer,
            );
        }
        if !line_buffer.trim().is_empty() {
            emit_process_line(
                &reader_app,
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
                if started.elapsed() > timeout {
                    let _ = child.kill();
                    // Reap the child to prevent zombies.  After kill()
                    // (SIGHUP on Unix, TerminateProcess on Windows) the
                    // process should exit quickly.
                    let _ = child.wait();
                    let active_stage = current_setup_stage(state);
                    break Err(SetupError::failed(format!(
                        "Setup timed out during '{active_stage}'"
                    )));
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
        let active_stage = current_setup_stage(state);
        Err(SetupError {
            status: "cancelled".into(),
            message: format!("Setup cancelled during '{active_stage}'"),
        })
    } else {
        let active_stage = current_setup_stage(state);
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

            let message = match last_output {
                Some(detail) => detail,
                None => format!(
                    "Setup failed during '{}' (exit code {})",
                    active_stage,
                    format_pty_exit(&status),
                ),
            };

            return Err(SetupError {
                status: marker,
                message,
            });
        }

        Err(SetupError::failed(format!(
            "Setup failed during '{}' (exit code {})",
            active_stage,
            format_pty_exit(&status)
        )))
    }
}

fn run_logged_shell(
    app: &AppHandle,
    state: &SetupState,
    stage: &str,
    script: &str,
    timeout: Duration,
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

// Returns true if detection should stop (status already set on `detail`).
fn detect_windows_blocker(detail: &mut HarborSetupDetail) -> bool {
    let wsl_status = run_capture_timeout("wsl.exe", &["--status"], DETECT_TIMEOUT);
    if wsl_status.code != Some(0) {
        // WSL feature isn't enabled yet — the installer handles this via
        // `wsl --install`, so surface as not-installed rather than blocked.
        detail.status = "not-installed".into();
        detail.last_error =
            Some("WSL isn't set up yet — Harbor will install it for you (a Windows restart may be required).".into());
        return true;
    }

    let distros = run_capture_timeout(
        "wsl.exe",
        &["--list", "--verbose"],
        DETECT_TIMEOUT,
    );

    if let Some(distro) = selected_wsl_distro() {
        // An explicitly configured distro that doesn't exist is a user-config
        // error the installer shouldn't paper over — report as blocked.
        let exists = distros.code == Some(0)
            && parse_wsl_distro_exists(&distros.stdout, &distro);
        if !exists {
            detail.status = "blocked".into();
            detail.last_error =
                Some(format!("The selected Linux environment ('{distro}') isn't set up correctly. Try removing it and reinstalling with: wsl --install"));
            return true;
        }
    } else if distros.code != Some(0) || preferred_wsl_distro().is_none() {
        // No distro found — the installer will run `wsl --install -d Ubuntu`.
        detail.status = "not-installed".into();
        detail.last_error =
            Some("Harbor will install Ubuntu (WSL2) for you automatically.".into());
        return true;
    }

    false
}

/// Run the full detection logic, ignoring whether setup is active.
/// Used internally after a successful install to verify the CLI is available.
fn detect_harbor_status() -> HarborSetupDetail {
    // The install may have created a different distro than the one cached
    // before it ran (e.g. fresh Ubuntu install) — re-resolve from scratch.
    clear_wsl_distro_cache();
    let mut detail = HarborSetupDetail::checking();
    detect_harbor_status_core(platform_name(), &mut detail);
    detail
}

fn detect_harbor_setup_inner(state: &SetupState) -> HarborSetupDetail {
    let running = setup_is_active(state)
        || state
            .current_pid
            .lock()
            .map(|pid| pid.is_some())
            .unwrap_or(false);

    let mut detail = HarborSetupDetail::checking();
    detail.running = running;

    if running {
        detail.status = current_setup_stage(state);
        return detail;
    }

    detect_harbor_status_core(platform_name(), &mut detail);
    detail
}

fn detect_harbor_status_core(platform: &str, detail: &mut HarborSetupDetail) {
    if !matches!(platform, "linux" | "macos" | "windows") {
        detail.status = "blocked".into();
        detail.last_error = Some(format!("Unsupported platform: {platform}. Harbor supports Linux, macOS, and Windows (via WSL2)."));
        return;
    }

    let version = if platform == "windows" {
        run_wsl_bash_timeout(
            "command -v harbor >/dev/null && harbor --version",
            WSL_COMMAND_TIMEOUT,
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

        // CLI exists — now verify the environment is actually usable
        // (Docker accessible, Compose installed, etc.) via doctor --check.
        let doctor = if platform == "windows" {
            run_wsl_bash_timeout(
                "harbor doctor --check",
                WSL_COMMAND_TIMEOUT,
            )
        } else {
            run_shell_timeout(
                &format!(
                    "{}; harbor doctor --check",
                    native_harbor_prelude()
                ),
                Duration::from_secs(30),
            )
        };

        if doctor.code == Some(0) {
            detail.status = "ready".into();
        } else {
            detail.status = "refresh-required".into();
            detail.last_error = Some(
                "Harbor is installed but can't connect to Docker yet. Try logging out and back in.".into(),
            );
        }
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
                "Harbor is installed but your system hasn't picked it up yet. Try closing and reopening Harbor.".into(),
            );
            return;
        }
    }

    // The CLI is not installed. Only now check installer prerequisites —
    // they gate installation, not usage, so an existing working install
    // (e.g. on a distro without a supported package manager) must never
    // be reported as blocked by them.
    match platform {
        "linux" => {
            let check = run_shell_timeout(
                "command -v apt-get >/dev/null || command -v dnf >/dev/null || command -v pacman >/dev/null || command -v apk >/dev/null || command -v zypper >/dev/null",
                DETECT_TIMEOUT,
            );
            if check.code != Some(0) {
                detail.status = "blocked".into();
                detail.last_error = Some(
                    "Harbor can't install its dependencies automatically on this system. Please install Docker from docker.com, then click Redetect.".into(),
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
                // Docker Desktop only creates /usr/local/bin/docker on first
                // launch, so distinguish "installed but never opened" from
                // "not installed at all" to give the right guidance.
                let app_check = run_shell_timeout(
                    "test -d /Applications/Docker.app -o -d \"$HOME/Applications/Docker.app\"",
                    DETECT_TIMEOUT,
                );
                detail.status = "blocked".into();
                if app_check.code == Some(0) {
                    detail.last_error = Some(
                        "Docker Desktop is installed but hasn't been launched yet. Open Docker Desktop once to finish its setup, then click Redetect.".into(),
                    );
                } else {
                    detail.last_error = Some(
                        "Docker is needed to run Harbor. Download it from docker.com/products/docker-desktop, install it, then click Redetect.".into(),
                    );
                }
                return;
            }
        }
        "windows" => {
            if detect_windows_blocker(detail) {
                return;
            }
        }
        _ => unreachable!("platform validated above"),
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
        // Reset the cancel flag while still holding the active lock, so a
        // cancel arriving between activation and the reset can't be wiped.
        reset_cancel(&state);
        *active = true;
    }

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
                        "checking-platform",
                        &windows_install_script(distro.as_deref()),
                        // Windows path can include ~600 MB Docker Desktop
                        // download + WSL distro install on slow links.
                        Duration::from_secs(3600),
                    )
                } else {
                    run_logged_shell(
                        &app,
                        &state,
                        "checking-platform",
                        &install_script(),
                        Duration::from_secs(3600),
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
    let pid = state.current_pid.lock().ok().and_then(|g| *g);
    kill_process_tree(pid);
    let mut killer = match state.current_killer.lock() {
        Ok(g) => g,
        // Mutex was poisoned by a prior panic. Recover the inner value so
        // we can still attempt the kill rather than leaving the process alive.
        Err(e) => e.into_inner(),
    };
    if let Some(k) = killer.as_mut() {
        let result = k.kill().map_err(|e| e.to_string());
        *killer = None;
        result
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strip_ansi_plain_csi_color_codes() {
        // Bold red text wrapped in SGR (Select Graphic Rendition) sequences.
        let input = "\x1b[1;31mError: something went wrong\x1b[0m";
        assert_eq!(strip_ansi(input), "Error: something went wrong");
    }

    #[test]
    fn strip_ansi_stage_marker_wrapped_in_color() {
        // A stage marker emitted with surrounding color codes should still parse.
        let input = "\x1b[32mHARBOR_SETUP_STAGE=failed\x1b[0m";
        let clean = strip_ansi(input.trim()).trim().to_string();
        assert_eq!(clean, "HARBOR_SETUP_STAGE=failed");
        assert_eq!(parse_setup_stage_marker(&clean), Some("failed".into()));
    }

    #[test]
    fn strip_ansi_osc_title_sequence() {
        // OSC 0 sets the terminal window/icon title; should be stripped entirely.
        let input = "\x1b]0;My Terminal Title\x07Plain text after";
        assert_eq!(strip_ansi(input), "Plain text after");
    }

    #[test]
    fn parse_wsl_distro_exists_rejects_short_line() {
        // A line with only name + version and no state token must not match.
        let short = "Ubuntu 2\n";
        assert!(!parse_wsl_distro_exists(short, "Ubuntu"));
    }

    #[test]
    fn parse_wsl_distro_exists_accepts_valid_line() {
        let valid = "Ubuntu Running 2\n";
        assert!(parse_wsl_distro_exists(valid, "Ubuntu"));
        assert!(!parse_wsl_distro_exists(valid, "Debian"));
    }

    #[test]
    fn parse_wsl_distro_exists_handles_default_marker() {
        // Lines starting with "*" have the name at index 1.
        let starred = "* Ubuntu Running 2\n";
        assert!(parse_wsl_distro_exists(starred, "Ubuntu"));
        let short_starred = "* Ubuntu 2\n";
        assert!(!parse_wsl_distro_exists(short_starred, "Ubuntu"));
    }
}
