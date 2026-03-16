import { useCallback, useEffect, useRef, useState } from "react";
import AnsiToHtml from "ansi-to-html";
import { spawnHarborPty } from "../terminal/harborPty";
import type { IPty } from "../terminal/harborPty";

const converter = new AnsiToHtml({ escapeXML: false });
const BUFFER_CAP = 2000;
const BUFFER_TRIM = 200;
const FLUSH_INTERVAL_MS = 100;
const CANCEL_KILL_DELAY_MS = 250;

export interface UseHarborStreamResult {
    lines: string[];
    chunks: Uint8Array[];
    bufferVersion: number;
    isStreaming: boolean;
    error: string | null;
    completion: HarborStreamCompletion | null;
    start: (nextArgs?: string[]) => void;
    stop: () => void;
    clear: () => void;
}

export type HarborStreamCompletionStatus = "success" | "failure" | "cancelled";

export interface HarborStreamCompletion {
    status: HarborStreamCompletionStatus;
    exitCode: number | null;
    error: string | null;
}

interface UseHarborStreamOptions {
    raw?: boolean;
    appendExitMessage?: boolean;
    onComplete?: (completion: HarborStreamCompletion) => void;
}

export function useHarborStream(args: string[], options?: UseHarborStreamOptions): UseHarborStreamResult {
    const raw = options?.raw ?? false;

    const [lines, setLines] = useState<string[]>([]);
    const [chunks, setChunks] = useState<Uint8Array[]>([]);
    const [bufferVersion, setBufferVersion] = useState(0);
    const [isStreaming, setIsStreaming] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [completion, setCompletion] = useState<HarborStreamCompletion | null>(null);

    const ptyRef = useRef<IPty | null>(null);
    const textBufRef = useRef<string[]>([]);
    const chunkBufRef = useRef<Uint8Array[]>([]);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const dirtyRef = useRef(false);
    const generationRef = useRef(0);
    const bufferVersionRef = useRef(0);
    const decoderRef = useRef(new TextDecoder());
    const cancelTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const stopCancelTimeout = useCallback(() => {
        if (cancelTimeoutRef.current !== null) {
            clearTimeout(cancelTimeoutRef.current);
            cancelTimeoutRef.current = null;
        }
    }, []);

    const bumpBufferVersion = useCallback(() => {
        bufferVersionRef.current += 1;
        setBufferVersion(bufferVersionRef.current);
    }, []);

    const stopInterval = useCallback(() => {
        if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
    }, []);

    const flushBuffers = useCallback(() => {
        setLines([...textBufRef.current]);
        setChunks([...chunkBufRef.current]);
    }, []);

    const emitCompletion = useCallback((nextCompletion: HarborStreamCompletion) => {
        setCompletion(nextCompletion);
        options?.onComplete?.(nextCompletion);
    }, [options]);

    const trimBuffers = useCallback(() => {
        if (chunkBufRef.current.length <= BUFFER_CAP) {
            return;
        }

        chunkBufRef.current = chunkBufRef.current.slice(BUFFER_TRIM);
        textBufRef.current = textBufRef.current.slice(BUFFER_TRIM);
        bumpBufferVersion();
    }, [bumpBufferVersion]);

    const flushDecoderTail = useCallback(() => {
        const remainder = decoderRef.current.decode();

        if (!remainder) {
            return;
        }

        textBufRef.current.push(raw ? remainder : converter.toHtml(remainder));
        trimBuffers();
        dirtyRef.current = true;
    }, [raw, trimBuffers]);

    const killPty = useCallback((pty: IPty | null = ptyRef.current) => {
        if (pty) {
            try {
                pty.kill();
            } catch {
                // process may have already exited
            }
        }
    }, []);

    const stopStream = useCallback(async () => {
        const pty = ptyRef.current;

        if (!pty) {
            const generation = ++generationRef.current;
            stopCancelTimeout();
            stopInterval();
            if (isStreaming && generationRef.current === generation) {
                flushBuffers();
                setError(null);
                emitCompletion({
                    status: "cancelled",
                    exitCode: null,
                    error: null,
                });
            }
            setIsStreaming(false);
            return;
        }

        const generation = ++generationRef.current;
        ptyRef.current = null;
        stopCancelTimeout();
        stopInterval();

        try {
            pty.write("\x03");
        } catch {
            // process may already be exiting
        }

        cancelTimeoutRef.current = setTimeout(() => {
            killPty(pty);
        }, CANCEL_KILL_DELAY_MS);

        if (generationRef.current !== generation) return;

        flushBuffers();
        setError(null);
        emitCompletion({
            status: "cancelled",
            exitCode: null,
            error: null,
        });
        setIsStreaming(false);
    }, [emitCompletion, flushBuffers, isStreaming, killPty, stopCancelTimeout, stopInterval]);

    const stop = useCallback(() => {
        void stopStream();
    }, [stopStream]);

    const clear = useCallback(() => {
        textBufRef.current = [];
        chunkBufRef.current = [];
        decoderRef.current = new TextDecoder();
        dirtyRef.current = true;
        setLines([]);
        setChunks([]);
        setError(null);
        setCompletion(null);
        bumpBufferVersion();
    }, [bumpBufferVersion]);

    const startStream = useCallback(async (nextArgs?: string[]) => {
        const runArgs = nextArgs ?? args;
        const previousPty = ptyRef.current;
        const generation = ++generationRef.current;

        ptyRef.current = null;
        stopCancelTimeout();

        textBufRef.current = [];
        chunkBufRef.current = [];
        decoderRef.current = new TextDecoder();
        dirtyRef.current = false;
        setLines([]);
        setChunks([]);
        setError(null);
        setCompletion(null);
        setIsStreaming(true);
        bumpBufferVersion();

        killPty(previousPty);
        stopInterval();

        if (generationRef.current !== generation) {
            return;
        }

        try {
            const pty = await spawnHarborPty(runArgs);

            if (generationRef.current !== generation) {
                killPty(pty);
                return;
            }

            pty.onData((data: Uint8Array) => {
                if (generationRef.current !== generation) return;

                const chunk = new Uint8Array(data);
                chunkBufRef.current.push(chunk);

                const text = decoderRef.current.decode(chunk, { stream: true });
                if (text) {
                    textBufRef.current.push(raw ? text : converter.toHtml(text));
                }

                trimBuffers();
                dirtyRef.current = true;
            });

            pty.onExit((payload: { exitCode: number | null }) => {
                if (generationRef.current !== generation) return;
                ptyRef.current = null;
                stopCancelTimeout();
                stopInterval();
                flushDecoderTail();

                if (payload.exitCode !== null && payload.exitCode !== 0) {
                    const message = `Process exited with code ${payload.exitCode}`;
                    flushBuffers();
                    setError(message);
                    emitCompletion({
                        status: "failure",
                        exitCode: payload.exitCode,
                        error: message,
                    });
                } else {
                    flushBuffers();
                    setError(null);
                    emitCompletion({
                        status: "success",
                        exitCode: payload.exitCode,
                        error: null,
                    });
                }
                setIsStreaming(false);
            });

            ptyRef.current = pty;

            intervalRef.current = setInterval(() => {
                if (dirtyRef.current) {
                    dirtyRef.current = false;
                    flushBuffers();
                }
            }, FLUSH_INTERVAL_MS);
        } catch (e) {
            if (generationRef.current !== generation) return;
            ptyRef.current = null;
            const msg = e instanceof Error ? e.message : String(e);
            stopCancelTimeout();
            flushBuffers();
            setError(msg);
            emitCompletion({
                status: "failure",
                exitCode: null,
                error: msg,
            });
            setIsStreaming(false);
            stopInterval();
        }
    }, [args, bumpBufferVersion, emitCompletion, flushBuffers, flushDecoderTail, killPty, raw, stopCancelTimeout, stopInterval, trimBuffers]);

    const start = useCallback((nextArgs?: string[]) => {
        void startStream(nextArgs);
    }, [startStream]);

    useEffect(() => {
        return () => {
            const pty = ptyRef.current;
            ptyRef.current = null;
            stopCancelTimeout();
            killPty(pty);
            stopInterval();
        };
    }, [killPty, stopCancelTimeout, stopInterval]);

    return { lines, chunks, bufferVersion, isStreaming, error, completion, start, stop, clear };
}
