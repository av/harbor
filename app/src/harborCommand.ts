import { invoke } from "@tauri-apps/api/core";

let cachedWindowsWslDistro: string | undefined;

export function shellQuote(value: string) {
    return `'${value.replace(/'/g, "'\\''")}'`;
}

function buildHarborShellCommand(args: string[]) {
    return ["harbor", ...args.map(shellQuote)].join(" ");
}

// Keep in sync with native_harbor_prelude in app/src-tauri/src/setup.rs
export function buildNativeHarborCommand(args: string[]) {
    const pathPrefix = [
        "$HOME/.local/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ].join(":");
    // Respect HARBOR_HOME if set; fall back to $HOME/.harbor
    const harborSh = '${HARBOR_HOME:-$HOME/.harbor}/harbor.sh';
    return [
        `export PATH="${pathPrefix}:$PATH"`,
        `if ! command -v harbor >/dev/null 2>&1 && test -x "${harborSh}"; then function harbor() { "${harborSh}" "$@"; }; fi`,
        buildHarborShellCommand(args),
    ].join("; ");
}

export function buildNativeHarborArgs(args: string[]) {
    return ["-lc", buildNativeHarborCommand(args)];
}

export async function getHarborWslDistro() {
    if (cachedWindowsWslDistro) {
        return cachedWindowsWslDistro;
    }

    try {
        const distro = await invoke<string | null>("get_harbor_wsl_distro");
        if (distro) {
            cachedWindowsWslDistro = distro;
        }
        return distro;
    } catch {
        return null;
    }
}

export async function buildWindowsWslArgs(commandArgs: string[]) {
    const args: string[] = [];
    const distro = await getHarborWslDistro();
    if (distro) {
        args.push("-d", distro);
    }
    args.push("-e", ...commandArgs);
    return args;
}

export async function buildWindowsWslHarborArgs(args: string[]) {
    return buildWindowsWslArgs(["bash", "-lic", buildHarborShellCommand(args)]);
}
