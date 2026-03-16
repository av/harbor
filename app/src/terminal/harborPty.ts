import { spawn } from "tauri-pty";
import type { IPty } from "tauri-pty";
import { isWindows } from "../utils";

const DEFAULT_PTY_COLS = 80;
const DEFAULT_PTY_ROWS = 24;

interface HarborPtyOptions {
    cols?: number;
    rows?: number;
    name?: string;
    cwd?: string;
    env?: Record<string, string>;
}

function shellQuote(value: string) {
    return `'${value.replace(/'/g, `'\\''`)}'`;
}

function buildWindowsHarborCommand(args: string[]) {
    if (args.length === 0) {
        return "harbor";
    }

    return `harbor ${args.map(shellQuote).join(" ")}`;
}

export async function spawnHarborPty(args: string[], options: HarborPtyOptions = {}): Promise<IPty> {
    const ptyOptions = {
        cols: options.cols ?? DEFAULT_PTY_COLS,
        rows: options.rows ?? DEFAULT_PTY_ROWS,
        name: options.name ?? "xterm-256color",
        cwd: options.cwd,
        env: options.env,
    };

    if (await isWindows()) {
        return spawn(
            "wsl.exe",
            ["-e", "bash", "-lic", buildWindowsHarborCommand(args)],
            ptyOptions,
        );
    }

    return spawn("harbor", args, ptyOptions);
}

export type { IPty };
