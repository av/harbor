use std::fs;
use std::path::Path;

/// Verify that `native_harbor_prelude()` in setup.rs and `buildNativeHarborCommand()` in
/// harborCommand.ts produce the same shell prelude. These two functions must stay in sync —
/// if one is updated without the other, the Tauri app's CLI discovery will behave differently
/// between the setup flow (Rust) and regular command execution (TypeScript).
///
/// This check runs at build time so divergence is caught before shipping.
fn verify_prelude_sync() {
    let ts_path = Path::new("../src/harborCommand.ts");
    let rs_path = Path::new("src/setup.rs");

    let ts_content = fs::read_to_string(ts_path)
        .unwrap_or_else(|e| panic!("Cannot read {}: {}", ts_path.display(), e));
    let rs_content = fs::read_to_string(rs_path)
        .unwrap_or_else(|e| panic!("Cannot read {}: {}", rs_path.display(), e));

    // Extract PATH entries from TypeScript: the array inside buildNativeHarborCommand
    let ts_paths = extract_ts_path_entries(&ts_content);
    let ts_harbor_sh = extract_ts_harbor_sh(&ts_content);

    // Extract PATH entries and harbor.sh path from Rust native_harbor_prelude
    let rs_prelude = extract_rs_prelude(&rs_content);
    let rs_paths = extract_rs_path_entries(&rs_prelude);
    let rs_harbor_sh = extract_rs_harbor_sh(&rs_prelude);

    if ts_paths != rs_paths {
        panic!(
            "\n\n\
            ╔══════════════════════════════════════════════════════════════════╗\n\
            ║ PRELUDE SYNC ERROR: PATH entries differ between Rust and TS     ║\n\
            ╠══════════════════════════════════════════════════════════════════╣\n\
            ║ TypeScript (harborCommand.ts): {:?}\n\
            ║ Rust (setup.rs):              {:?}\n\
            ║                                                                  ║\n\
            ║ Update BOTH files to keep them in sync.                           ║\n\
            ╚══════════════════════════════════════════════════════════════════╝\n\n",
            ts_paths, rs_paths
        );
    }

    if ts_harbor_sh != rs_harbor_sh {
        panic!(
            "\n\n\
            ╔══════════════════════════════════════════════════════════════════╗\n\
            ║ PRELUDE SYNC ERROR: harbor.sh path differs between Rust and TS  ║\n\
            ╠══════════════════════════════════════════════════════════════════╣\n\
            ║ TypeScript (harborCommand.ts): {:?}\n\
            ║ Rust (setup.rs):              {:?}\n\
            ║                                                                  ║\n\
            ║ Update BOTH files to keep them in sync.                           ║\n\
            ╚══════════════════════════════════════════════════════════════════╝\n\n",
            ts_harbor_sh, rs_harbor_sh
        );
    }

    // Tell cargo to re-run this check if either file changes
    println!("cargo:rerun-if-changed=../src/harborCommand.ts");
    println!("cargo:rerun-if-changed=src/setup.rs");
}

/// Extract the path entries from the TypeScript pathPrefix array.
/// Looks for the array literal inside buildNativeHarborCommand.
fn extract_ts_path_entries(ts: &str) -> Vec<String> {
    // Find the pathPrefix array: lines between `[` and `].join(":")`
    let mut in_array = false;
    let mut paths = Vec::new();

    for line in ts.lines() {
        let trimmed = line.trim();
        if trimmed.contains("const pathPrefix") && trimmed.contains('[') {
            in_array = true;
            continue;
        }
        if in_array {
            if trimmed.starts_with(']') {
                break;
            }
            // Extract quoted string value
            let cleaned = trimmed.trim_matches(|c: char| c == '"' || c == '\'' || c == ',' || c.is_whitespace());
            if !cleaned.is_empty() {
                paths.push(cleaned.to_string());
            }
        }
    }

    if paths.is_empty() {
        panic!("Could not extract pathPrefix array from harborCommand.ts");
    }
    paths
}

/// Extract the harborSh path from TypeScript.
fn extract_ts_harbor_sh(ts: &str) -> String {
    for line in ts.lines() {
        let trimmed = line.trim();
        if trimmed.contains("const harborSh") {
            // Extract the string between quotes: 'xxx' or "xxx"
            let start = trimmed.find(|c: char| c == '\'' || c == '"');
            let end = trimmed.rfind(|c: char| c == '\'' || c == '"');
            if let (Some(s), Some(e)) = (start, end) {
                if s < e {
                    return trimmed[s + 1..e].to_string();
                }
            }
        }
    }
    panic!("Could not extract harborSh from harborCommand.ts");
}

/// Extract the native_harbor_prelude string from Rust source.
fn extract_rs_prelude(rs: &str) -> String {
    // Find the fn native_harbor_prelude() and extract its string literal
    let marker = "fn native_harbor_prelude()";
    let start_idx = rs.find(marker)
        .unwrap_or_else(|| panic!("Could not find native_harbor_prelude in setup.rs"));

    let after_marker = &rs[start_idx..];
    // Find the opening quote of the string literal (after the first `"`)
    let first_quote = after_marker.find('"')
        .unwrap_or_else(|| panic!("Could not find string literal in native_harbor_prelude"));

    let string_start = start_idx + first_quote + 1;
    // Find the closing quote — accounting for escaped quotes
    let mut i = string_start;
    let bytes = rs.as_bytes();
    loop {
        if i >= bytes.len() {
            panic!("Unterminated string in native_harbor_prelude");
        }
        if bytes[i] == b'\\' {
            i += 2; // skip escaped char
            continue;
        }
        if bytes[i] == b'"' {
            break;
        }
        i += 1;
    }

    // Unescape the Rust string literal
    let raw = &rs[string_start..i];
    raw.replace("\\\"", "\"").replace("\\\\", "\\")
}

/// Extract PATH entries from the prelude string.
/// The prelude looks like: export PATH="entry1:entry2:...:$PATH"; ...
fn extract_rs_path_entries(prelude: &str) -> Vec<String> {
    // Find PATH="..." segment
    let path_start = prelude.find("PATH=\"")
        .unwrap_or_else(|| panic!("Could not find PATH= in prelude: {}", prelude));
    let after_path = &prelude[path_start + 6..]; // skip PATH="
    let path_end = after_path.find('"')
        .unwrap_or_else(|| panic!("Could not find closing quote for PATH in prelude"));
    let path_value = &after_path[..path_end];

    // Split by : and filter out $PATH
    path_value
        .split(':')
        .filter(|s| *s != "$PATH" && !s.is_empty())
        .map(|s| s.to_string())
        .collect()
}

/// Extract harbor.sh path from the prelude string.
/// Looks for the pattern: test -x "path" ... "path" "$@"
fn extract_rs_harbor_sh(prelude: &str) -> String {
    // Find: test -x "${HARBOR_HOME:-...}/harbor.sh"
    let marker = "test -x \"";
    let start = prelude.find(marker)
        .unwrap_or_else(|| panic!("Could not find 'test -x' in prelude: {}", prelude));
    let after = &prelude[start + marker.len()..];
    let end = after.find('"')
        .unwrap_or_else(|| panic!("Could not find closing quote after 'test -x' in prelude"));
    after[..end].to_string()
}

fn main() {
    verify_prelude_sync();
    tauri_build::build()
}
