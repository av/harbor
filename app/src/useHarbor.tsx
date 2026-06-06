import { useCallback, useEffect, useState } from "react";
import { Child, ChildProcess, Command } from "@tauri-apps/plugin-shell";
import { join } from "@tauri-apps/api/path";

import { isWindows, once, resolveResultLines } from "./utils";
import { PROFILES_DIR } from "./configMetadata";
import { buildNativeHarborArgs, buildWindowsWslArgs, buildWindowsWslHarborArgs } from "./harborCommand";

// Default timeout for most CLI commands (60 seconds)
const DEFAULT_TIMEOUT_MS = 60_000;

// Commands that are expected to take longer get extended timeouts
const LONG_RUNNING_COMMANDS: Record<string, number> = {
    up: 300_000,       // 5 minutes — pulling images can be slow
    build: 600_000,    // 10 minutes — building containers
    pull: 600_000,     // 10 minutes — pulling models
    down: 120_000,     // 2 minutes — stopping containers
    update: 300_000,   // 5 minutes — fetching + checkout + migration
    restart: 300_000,  // 5 minutes — stop + start
};

/**
 * Determine the timeout for a given command based on the first argument.
 */
function resolveTimeout(args: string[], overrideMs?: number): number {
    if (overrideMs !== undefined) return overrideMs;
    const subcommand = args[0]?.toLowerCase();
    if (subcommand && subcommand in LONG_RUNNING_COMMANDS) {
        return LONG_RUNNING_COMMANDS[subcommand];
    }
    return DEFAULT_TIMEOUT_MS;
}

/**
 * Execute a Tauri shell Command with a timeout. Uses spawn() + event listeners
 * so the child process can be killed if the timeout fires.
 */
function executeWithTimeout(command: Command<string>, timeoutMs: number): Promise<ChildProcess<string>> {
    return new Promise((resolve, reject) => {
        let child: Child | null = null;
        let settled = false;
        let stdout = "";
        let stderr = "";

        const timer = setTimeout(() => {
            if (settled) return;
            settled = true;
            if (child) {
                child.kill().catch(() => {});
            }
            reject(new Error(
                `Command timed out after ${Math.round(timeoutMs / 1000)}s. ` +
                `The process was killed. If this command normally takes longer, retry or check if Docker is responsive.`
            ));
        }, timeoutMs);

        command.stdout.on("data", (line: string) => {
            stdout += (stdout ? "\n" : "") + line;
        });

        command.stderr.on("data", (line: string) => {
            stderr += (stderr ? "\n" : "") + line;
        });

        command.on("close", (payload) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve({
                code: payload.code,
                signal: payload.signal,
                stdout,
                stderr,
            });
        });

        command.on("error", (err: string) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            reject(new Error(err));
        });

        command.spawn().then((c) => {
            child = c;
            if (settled) {
                // Timeout already fired before spawn resolved
                c.kill().catch(() => {});
            }
        }).catch((err) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            reject(err instanceof Error ? err : new Error(String(err)));
        });
    });
}

export const resolveHarborHome = once(async function __resolveHarborHome() {
    const result = await runHarbor(["home"]);
    const path = resolveResultLines(result).join('\n');

    if (!path) {
        throw new Error("Harbor CLI returned empty home path. Is Harbor installed correctly?");
    }

    if (await isWindows()) {
        // On windows, we need to resolve the path first via WSL
        const wslResult = await Command.create("wsl.exe", await buildWindowsWslArgs(["wslpath", "-w", path])).execute();
        const winPath = resolveResultLines(wslResult).join('\n');
        if (!winPath) {
            throw new Error(`Failed to convert WSL path '${path}' to Windows path.`);
        }
        return winPath;
    }

    return path;
});

export const resolveProfilesDir = once(async function __resolveProfilesDir() {
    const homeDir = await resolveHarborHome();
    return await join(homeDir, PROFILES_DIR);
});

export interface RunHarborOptions {
    /** Custom timeout in milliseconds. Overrides the default and per-command timeouts. */
    timeoutMs?: number;
    /** If true, disable timeout entirely (use with caution). */
    noTimeout?: boolean;
}

/**
 * Run a harbor command and return the raw result without checking exit code.
 * Use this when you need to inspect stdout/stderr regardless of exit status
 * (e.g., `harbor doctor` which exits non-zero when issues are found).
 *
 * Commands are killed after a timeout (default 60s, longer for up/build/pull).
 */
export async function runHarborRaw(args: string[], options?: RunHarborOptions) {
    const command = await isWindows()
        ? Command.create("wsl.exe", await buildWindowsWslHarborArgs(args))
        : Command.create("bash", buildNativeHarborArgs(args));

    if (options?.noTimeout) {
        return await command.execute();
    }

    const timeoutMs = resolveTimeout(args, options?.timeoutMs);
    return await executeWithTimeout(command, timeoutMs);
}

/**
 * Run a harbor command. Throws if the command exits with a non-zero code.
 * Use this for commands where failure should surface as an error to the user.
 *
 * Commands are killed after a timeout (default 60s, longer for up/build/pull).
 */
export async function runHarbor(args: string[], options?: RunHarborOptions) {
    const result = await runHarborRaw(args, options);

    if (result.code !== 0 && result.code !== null) {
        const stderr = result.stderr?.trim();
        const stdout = result.stdout?.trim();
        const detail = stderr || stdout || `exit code ${result.code}`;
        throw new Error(`harbor ${args.join(" ")} failed: ${detail}`);
    }

    return result;
}

interface UseHarborOptions {
    /** If true, don't throw on non-zero exit codes. Use for commands like
     *  `harbor doctor` that exit non-zero to signal warnings, not failures. */
    raw?: boolean;
    /** Custom timeout in milliseconds. */
    timeoutMs?: number;
    /** Disable timeout entirely. */
    noTimeout?: boolean;
}

export const useHarborTrigger = (args: string[], options?: UseHarborOptions) => {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<ChildProcess<string> | null>(null);
    const [error, setError] = useState<Error | null>(null);

    const runCommand = useCallback(
        async () => {
            setLoading(true);
            setError(null);

            const runOptions: RunHarborOptions = {
                timeoutMs: options?.timeoutMs,
                noTimeout: options?.noTimeout,
            };

            try {
                const result = options?.raw
                    ? await runHarborRaw(args, runOptions)
                    : await runHarbor(args, runOptions);
                setResult(result);
            } catch (e) {
                if (e instanceof Error) {
                    setError(e);
                } else {
                    setError(new Error(`Unexpected error: ${e}`));
                }
            } finally {
                setLoading(false);
            }
        },
        args,
    );

    const run = useCallback(() => {
        runCommand();
    }, [runCommand]);

    return {
        loading,
        error,
        result,
        run,
    };
};

/**
 * Run Harbor Shell command and return the result
 */
export const useHarbor = (args: string[], options?: UseHarborOptions) => {
    const { run, ...rest } = useHarborTrigger(args, options);

    useEffect(() => {
        run();
    }, [run, ...args]);

    return {
        ...rest,
        rerun: run,
    };
};
