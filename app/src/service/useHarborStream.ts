import { useCallback, useEffect, useRef, useState } from "react";
import { Child, Command } from "@tauri-apps/plugin-shell";
import AnsiToHtml from "ansi-to-html";
import { isWindows } from "../utils";

const converter = new AnsiToHtml({ escapeXML: false });
const BUFFER_CAP = 2000;
const BUFFER_TRIM = 200;
const FLUSH_INTERVAL_MS = 100;

export interface UseHarborStreamResult {
    lines: string[];
    isStreaming: boolean;
    error: string | null;
    start: () => void;
    stop: () => void;
    clear: () => void;
}

export function useHarborStream(args: string[]): UseHarborStreamResult {
    const [lines, setLines] = useState<string[]>([]);
    const [isStreaming, setIsStreaming] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const childRef = useRef<Child | null>(null);
    const bufRef = useRef<string[]>([]);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    // Track whether the buffer has been modified since last flush
    const dirtyRef = useRef(false);

    const stopInterval = useCallback(() => {
        if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
    }, []);

    const killChild = useCallback(async () => {
        const child = childRef.current;
        if (child) {
            childRef.current = null;
            try {
                await child.kill();
            } catch {
                // process may have already exited
            }
        }
    }, []);

    const stop = useCallback(() => {
        killChild();
        stopInterval();
        setIsStreaming(false);
    }, [killChild, stopInterval]);

    const clear = useCallback(() => {
        bufRef.current = [];
        dirtyRef.current = true;
        setLines([]);
    }, []);

    const start = useCallback(async () => {
        await killChild();
        stopInterval();

        bufRef.current = [];
        dirtyRef.current = false;
        setLines([]);
        setError(null);
        setIsStreaming(true);

        try {
            const windows = await isWindows();
            const command = windows
                ? Command.create("wsl.exe", ["-e", "bash", "-lic", `harbor ${args.join(" ")}`])
                : Command.create("harbor", args);

            command.stdout.on("data", (line: string) => {
                bufRef.current.push(converter.toHtml(line));
                if (bufRef.current.length > BUFFER_CAP) {
                    bufRef.current = [
                        "(older lines trimmed)",
                        ...bufRef.current.slice(BUFFER_TRIM),
                    ];
                }
                dirtyRef.current = true;
            });

            command.stderr.on("data", (line: string) => {
                bufRef.current.push(converter.toHtml(line));
                if (bufRef.current.length > BUFFER_CAP) {
                    bufRef.current = [
                        "(older lines trimmed)",
                        ...bufRef.current.slice(BUFFER_TRIM),
                    ];
                }
                dirtyRef.current = true;
            });

            command.on("close", (payload: { code: number | null }) => {
                childRef.current = null;
                stopInterval();
                setLines([...bufRef.current]);
                if (payload.code !== null && payload.code !== 0) {
                    setError(`Process exited with code ${payload.code}`);
                } else {
                    bufRef.current.push("Stream ended — service stopped.");
                    setLines([...bufRef.current]);
                }
                setIsStreaming(false);
            });

            command.on("error", (err: string) => {
                childRef.current = null;
                stopInterval();
                setError(err);
                setIsStreaming(false);
            });

            const child = await command.spawn();
            childRef.current = child;

            intervalRef.current = setInterval(() => {
                if (dirtyRef.current) {
                    dirtyRef.current = false;
                    setLines([...bufRef.current]);
                }
            }, FLUSH_INTERVAL_MS);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(msg);
            setIsStreaming(false);
            stopInterval();
        }
    }, [args, killChild, stopInterval]);

    useEffect(() => {
        return () => {
            killChild();
            stopInterval();
        };
    }, [killChild, stopInterval]);

    return { lines, isStreaming, error, start, stop, clear };
}
