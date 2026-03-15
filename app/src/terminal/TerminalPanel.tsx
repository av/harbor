import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { spawn } from "tauri-pty";
import type { IPty } from "tauri-pty";
import { useTerminalPanel } from "./TerminalContext";
import { buildXtermTheme, watchTheme } from "./terminalTheme";
import { isWindows } from "../utils";
import { IconEraser, IconStop, IconX } from "../Icons";
import { IconButton } from "../IconButton";

const DEFAULT_HEIGHT = 400;
const MIN_HEIGHT = 150;

export const TerminalPanel = () => {
    const { isOpen, close, focusRef } = useTerminalPanel();
    const containerRef = useRef<HTMLDivElement>(null);
    const terminalRef = useRef<Terminal | null>(null);
    const fitAddonRef = useRef<FitAddon | null>(null);
    const openedRef = useRef(false);
    const ptyRef = useRef<IPty | null>(null);
    const heightRef = useRef(DEFAULT_HEIGHT);

    const [panelHeight, setPanelHeight] = useState(DEFAULT_HEIGHT);

    const onDragStart = (e: React.MouseEvent) => {
        e.preventDefault();
        const startY = e.clientY;
        const startHeight = heightRef.current;
        const onMove = (moveEvent: MouseEvent) => {
            const delta = startY - moveEvent.clientY;
            const newH = Math.max(MIN_HEIGHT, Math.min(window.innerHeight * 0.8, startHeight + delta));
            heightRef.current = newH;
            setPanelHeight(newH);
        };
        const onUp = () => {
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
            fitAddonRef.current?.fit();
            const terminal = terminalRef.current;
            if (ptyRef.current && terminal) {
                ptyRef.current.resize(terminal.cols, terminal.rows);
            }
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    };

    const cancel = () => {
        ptyRef.current?.write("\x03");
    };

    const handleClear = () => {
        terminalRef.current?.clear();
    };

    // Mount xterm once — guard against React StrictMode double-invoke
    useEffect(() => {
        if (openedRef.current || !containerRef.current) return;
        openedRef.current = true;

        const terminal = new Terminal({
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            fontSize: 13,
            theme: buildXtermTheme(),
            cursorBlink: true,
            convertEol: true,
            allowProposedApi: true,
        });

        const fitAddon = new FitAddon();
        const webLinksAddon = new WebLinksAddon();

        terminal.loadAddon(fitAddon);
        terminal.loadAddon(webLinksAddon);
        terminal.open(containerRef.current);
        fitAddon.fit();

        terminalRef.current = terminal;
        fitAddonRef.current = fitAddon;

        // Register focus function so external code (e.g. Ctrl+`) can focus xterm
        focusRef.current = () => terminal.focus();

        // Allow all key combos (Alt+Left/Right, Ctrl+Left/Right, etc.) to reach onData
        // Ctrl+` is explicitly passed through so the global shortcut handler can receive it
        terminal.attachCustomKeyEventHandler((ev: KeyboardEvent) => {
            if (ev.key === "`" && ev.ctrlKey) return false;
            return true;
        });

        // Forward all input straight to the shell — no manual echo or line editing
        terminal.onData((data: string) => {
            ptyRef.current?.write(data);
        });

        const spawnShell = async () => {
            const windows = await isWindows();
            // If the component was unmounted while we were awaiting, do nothing
            if (!openedRef.current) return;
            const shellCmd = windows ? "wsl.exe" : "bash";
            const args: string[] = [];

            const pty = spawn(shellCmd, args, {
                cols: terminal.cols,
                rows: terminal.rows,
                name: "xterm-256color",
            });

            ptyRef.current = pty;

            pty.onData((data: Uint8Array) => {
                terminal.write(data);
            });

            pty.onExit(() => {
                ptyRef.current = null;
                if (openedRef.current) {
                    setTimeout(spawnShell, 100);
                }
            });
        };

        spawnShell();

        // Update theme when data-theme attribute changes
        const stopWatching = watchTheme(() => {
            terminal.options.theme = buildXtermTheme();
        });

        // Refit on container resize, also resize active PTY
        const resizeObserver = new ResizeObserver(() => {
            fitAddon.fit();
            if (ptyRef.current) {
                ptyRef.current.resize(terminal.cols, terminal.rows);
            }
        });
        resizeObserver.observe(containerRef.current);

        return () => {
            stopWatching();
            resizeObserver.disconnect();
            try { ptyRef.current?.kill(); } catch { /* ignore */ }
            ptyRef.current = null;
            terminal.dispose();
            terminalRef.current = null;
            fitAddonRef.current = null;
            focusRef.current = null;
            openedRef.current = false;
        };
    }, []);

    // Refit when panel opens so dimensions match the now-visible container
    useEffect(() => {
        if (isOpen) {
            requestAnimationFrame(() => {
                fitAddonRef.current?.fit();
                const terminal = terminalRef.current;
                if (ptyRef.current && terminal) {
                    ptyRef.current.resize(terminal.cols, terminal.rows);
                }
            });
            // Focus the terminal itself when the panel becomes visible
            requestAnimationFrame(() => {
                terminalRef.current?.focus();
            });
        }
    }, [isOpen]);

    return (
        <div
            style={{
                height: isOpen ? `${panelHeight}px` : "0px",
                transition: "height 0.2s ease",
                overflow: "hidden",
            }}
            className="border-t border-base-content/10 bg-base-200 flex flex-col"
        >
            {/* Drag handle — dragging up increases height */}
            <div
                className="h-1 cursor-row-resize hover:bg-primary/40 transition-colors shrink-0"
                onMouseDown={onDragStart}
            />
            {/* Header toolbar */}
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-base-content/10 shrink-0">
                <span className="font-mono text-xs text-base-content/50 select-none flex-1">
                    Terminal
                </span>
                {/* Cancel — sends Ctrl+C to interrupt the foreground process */}
                <IconButton
                    icon={<IconStop />}
                    onClick={cancel}
                    title="Send interrupt (Ctrl+C)"
                />
                {/* Clear terminal output */}
                <IconButton
                    icon={<IconEraser />}
                    onClick={handleClear}
                    title="Clear terminal"
                />
                {/* Close panel */}
                <IconButton
                    icon={<IconX />}
                    onClick={close}
                    title="Close terminal"
                />
            </div>

            {/* xterm.js container */}
            <div
                ref={containerRef}
                style={{
                    flex: 1,
                    minHeight: 0,
                    width: "100%",
                    padding: "4px",
                }}
            />
        </div>
    );
};
