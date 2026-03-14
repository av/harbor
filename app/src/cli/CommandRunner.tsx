import { useEffect, useRef, useState } from "react";
import { Child, Command } from "@tauri-apps/plugin-shell";
import AnsiToHtml from "ansi-to-html";

import { Section } from "../Section";
import { IconButton } from "../IconButton";
import { IconEraser, IconPlay, IconStop } from "../Icons";
import { isWindows } from "../utils";

const converter = new AnsiToHtml({ escapeXML: false });

interface CliEntry {
    id: number;
    args: string[];
    stdout: string;
    stderr: string;
    exitCode: number | null;
    running: boolean;
    cancelled?: boolean;
}

export const CommandRunner = () => {
    const [input, setInput] = useState("");
    const [entries, setEntries] = useState<CliEntry[]>([]);
    const [running, setRunning] = useState(false);
    const [history, setHistory] = useState<string[]>([]);
    const [historyIndex, setHistoryIndex] = useState(-1);

    const idCounter = useRef(0);
    const activeChild = useRef<Child | null>(null);
    const stdoutBuf = useRef("");
    const stderrBuf = useRef("");
    const inputRef = useRef<HTMLInputElement>(null);
    const outputRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!running) {
            inputRef.current?.focus();
        }
    }, [running]);

    useEffect(() => {
        if (outputRef.current) {
            outputRef.current.scrollTop = outputRef.current.scrollHeight;
        }
    }, [entries]);

    const runCommand = async () => {
        const trimmed = input.trim();
        if (!trimmed || running) return;

        const args = trimmed.split(/\s+/);
        const id = ++idCounter.current;

        stdoutBuf.current = "";
        stderrBuf.current = "";

        const entry: CliEntry = {
            id,
            args,
            stdout: "",
            stderr: "",
            exitCode: null,
            running: true,
        };

        setEntries((prev) => {
            const next = [...prev, entry];
            return next.length > 100 ? next.slice(next.length - 100) : next;
        });

        setHistory((prev) => {
            const next = [trimmed, ...prev.filter((h) => h !== trimmed)];
            return next.slice(0, 100);
        });
        setHistoryIndex(-1);
        setInput("");
        setRunning(true);

        try {
            const windows = await isWindows();
            const command = windows
                ? Command.create("wsl.exe", ["-e", "bash", "-lic", `harbor ${args.join(" ")}`])
                : Command.create("harbor", args);

            command.stdout.on("data", (line: string) => {
                const html = converter.toHtml(line);
                stdoutBuf.current += (stdoutBuf.current ? "\n" : "") + html;
                setEntries((prev) =>
                    prev.map((e) =>
                        e.id === id ? { ...e, stdout: stdoutBuf.current } : e,
                    ),
                );
            });

            command.stderr.on("data", (line: string) => {
                const html = converter.toHtml(line);
                stderrBuf.current += (stderrBuf.current ? "\n" : "") + html;
                setEntries((prev) =>
                    prev.map((e) =>
                        e.id === id ? { ...e, stderr: stderrBuf.current } : e,
                    ),
                );
            });

            command.on("close", (payload: { code: number | null }) => {
                activeChild.current = null;
                setEntries((prev) =>
                    prev.map((e) =>
                        e.id === id
                            ? {
                                  ...e,
                                  stdout: stdoutBuf.current,
                                  stderr: stderrBuf.current,
                                  exitCode: payload.code,
                                  running: false,
                              }
                            : e,
                    ),
                );
                setRunning(false);
            });

            command.on("error", (err: string) => {
                activeChild.current = null;
                stderrBuf.current += (stderrBuf.current ? "\n" : "") + err;
                setEntries((prev) =>
                    prev.map((e) =>
                        e.id === id
                            ? {
                                  ...e,
                                  stderr: stderrBuf.current,
                                  exitCode: 1,
                                  running: false,
                              }
                            : e,
                    ),
                );
                setRunning(false);
            });

            const child = await command.spawn();
            activeChild.current = child;
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            setEntries((prev) =>
                prev.map((ent) =>
                    ent.id === id
                        ? {
                              ...ent,
                              stderr: msg,
                              exitCode: 1,
                              running: false,
                          }
                        : ent,
                ),
            );
            setRunning(false);
        }
    };

    const cancel = () => {
        const child = activeChild.current;
        if (!child) return;
        child.kill().catch(() => {});
        activeChild.current = null;
        setEntries((prev) =>
            prev.map((e) =>
                e.running
                    ? { ...e, running: false, stderr: (e.stderr ? e.stderr + "\n" : "") + "(cancelled)" }
                    : e,
            ),
        );
        setRunning(false);
        inputRef.current?.focus();
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault();
            runCommand();
            return;
        }

        if (e.key === "ArrowUp") {
            e.preventDefault();
            const next = Math.min(historyIndex + 1, history.length - 1);
            setHistoryIndex(next);
            setInput(history[next] ?? "");
            return;
        }

        if (e.key === "ArrowDown") {
            e.preventDefault();
            const next = historyIndex - 1;
            if (next < 0) {
                setHistoryIndex(-1);
                setInput("");
            } else {
                setHistoryIndex(next);
                setInput(history[next] ?? "");
            }
        }
    };

    return (
        <Section
            className="mt-6"
            header={
                <>
                    <span>Run</span>
                    {entries.length > 0 && (
                        <IconButton
                            icon={<IconEraser />}
                            title="Clear output"
                            onClick={() => setEntries([])}
                        />
                    )}
                </>
            }
        >
            <div className="flex items-center gap-2 mb-3">
                <label className="font-mono text-sm text-base-content/60 select-none">
                    harbor
                </label>
                <input
                    ref={inputRef}
                    className="input input-bordered input-sm flex-1 font-mono"
                    placeholder="ps"
                    value={input}
                    disabled={running}
                    onChange={(e) => {
                        setInput(e.target.value);
                        setHistoryIndex(-1);
                    }}
                    onKeyDown={handleKeyDown}
                />
                {running ? (
                    <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        onClick={cancel}
                    >
                        <IconStop className="mr-1" />
                        Cancel
                    </button>
                ) : (
                    <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        disabled={!input.trim()}
                        onClick={runCommand}
                    >
                        <IconPlay className="mr-1" />
                        Run
                    </button>
                )}
            </div>

            <div
                ref={outputRef}
                className="font-mono text-sm bg-base-200 rounded-box p-3 max-h-96 overflow-y-auto space-y-3"
            >
                {entries.length === 0 ? (
                    <p className="text-base-content/40 text-center py-4">
                        Run a harbor command to see output here.
                    </p>
                ) : (
                    entries.map((entry) => (
                        <div
                            key={entry.id}
                            className={`rounded-box p-2 bg-base-100 ${
                                entry.exitCode !== null && entry.exitCode !== 0
                                    ? "border border-error"
                                    : ""
                            }`}
                        >
                            <div className="flex items-center gap-2 mb-1 text-base-content/60 text-xs">
                                <span>
                                    harbor {entry.args.join(" ")}
                                </span>
                                {entry.running && (
                                    <span className="loading loading-spinner loading-xs" />
                                )}
                                {!entry.running &&
                                    entry.exitCode !== null &&
                                    entry.exitCode !== 0 && (
                                        <span className="badge badge-error badge-xs">
                                            exit {entry.exitCode}
                                        </span>
                                    )}
                            </div>
                            {entry.stdout && (
                                <pre className="whitespace-pre-wrap break-words">
                                    {entry.stdout.split("\n").map((line, i) => (
                                        <span key={i} dangerouslySetInnerHTML={{ __html: line }} />
                                    ))}
                                </pre>
                            )}
                            {entry.stderr && (
                                <pre className="whitespace-pre-wrap break-words text-error">
                                    {entry.stderr.split("\n").map((line, i) => (
                                        <span key={i} dangerouslySetInnerHTML={{ __html: line }} />
                                    ))}
                                </pre>
                            )}
                        </div>
                    ))
                )}
            </div>
        </Section>
    );
};
