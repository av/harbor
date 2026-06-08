import { spawn, type IPty } from "tauri-pty";
import { isWindows } from "../utils";
import { buildNativeHarborArgs, buildWindowsWslHarborArgs } from "../harborCommand";

const DEFAULT_PTY_COLS = 80;
const DEFAULT_PTY_ROWS = 24;

interface HarborPtyOptions {
    cols?: number;
    rows?: number;
    name?: string;
    cwd?: string;
    env?: Record<string, string>;
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
            await buildWindowsWslHarborArgs(args),
            ptyOptions,
        );
    }

    return spawn("bash", buildNativeHarborArgs(args), ptyOptions);
}

export type { IPty };
