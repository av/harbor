import { useCallback, useEffect, useState } from "react";
import { ChildProcess, Command } from "@tauri-apps/plugin-shell";
import { join } from "@tauri-apps/api/path";

import { isWindows, once, resolveResultLines } from "./utils";
import { PROFILES_DIR } from "./configMetadata";
import { buildNativeHarborArgs, buildWindowsWslArgs, buildWindowsWslHarborArgs } from "./harborCommand";

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

/**
 * Run a harbor command and return the raw result without checking exit code.
 * Use this when you need to inspect stdout/stderr regardless of exit status
 * (e.g., `harbor doctor` which exits non-zero when issues are found).
 */
export async function runHarborRaw(args: string[]) {
    if (await isWindows()) {
        return await Command.create("wsl.exe", await buildWindowsWslHarborArgs(args)).execute();
    } else {
        return await Command.create("bash", buildNativeHarborArgs(args)).execute();
    }
}

/**
 * Run a harbor command. Throws if the command exits with a non-zero code.
 * Use this for commands where failure should surface as an error to the user.
 */
export async function runHarbor(args: string[]) {
    const result = await runHarborRaw(args);

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
}

export const useHarborTrigger = (args: string[], options?: UseHarborOptions) => {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<ChildProcess<string> | null>(null);
    const [error, setError] = useState<Error | null>(null);

    const runCommand = useCallback(
        async () => {
            setLoading(true);
            setError(null);

            try {
                const result = options?.raw
                    ? await runHarborRaw(args)
                    : await runHarbor(args);
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
