import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { buildXtermTheme, watchTheme } from "./terminalTheme";

interface XTermViewProps {
    /** Backwards-compatible textual output segments. Written with terminal.write(...). */
    lines?: string[];
    /** Raw terminal chunks for accurate xterm replay. Preferred over lines when provided. */
    chunks?: Uint8Array[];
    /** Increment when the underlying buffer is reset, trimmed, or replayed from scratch. */
    bufferVersion?: number;
    /** Optional CSS height for the container. Default "256px" */
    height?: string;
    /** Called when terminal is ready — useful for clearing etc. */
    onReady?: (terminal: Terminal) => void;
}

export const XTermView = ({ lines, chunks, bufferVersion, height = "256px", onReady }: XTermViewProps) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const terminalRef = useRef<Terminal | null>(null);
    const fitAddonRef = useRef<FitAddon | null>(null);
    const openedRef = useRef(false);
    const segmentCountRef = useRef(0);
    const sourceModeRef = useRef<"lines" | "chunks" | null>(null);
    const bufferVersionRef = useRef<number | undefined>(undefined);

    useEffect(() => {
        if (openedRef.current || !containerRef.current) return;
        openedRef.current = true;

        const terminal = new Terminal({
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            fontSize: 12,
            theme: buildXtermTheme(),
            cursorBlink: false,
            convertEol: true,
            disableStdin: true, // read-only
            scrollback: 5000,
        });

        const fitAddon = new FitAddon();
        const webLinksAddon = new WebLinksAddon();
        terminal.loadAddon(fitAddon);
        terminal.loadAddon(webLinksAddon);
        terminal.open(containerRef.current);
        fitAddon.fit();

        terminalRef.current = terminal;
        fitAddonRef.current = fitAddon;

        const stopWatching = watchTheme(() => {
            terminal.options.theme = buildXtermTheme();
        });

        const resizeObserver = new ResizeObserver(() => {
            fitAddon.fit();
        });
        resizeObserver.observe(containerRef.current);

        onReady?.(terminal);

        return () => {
            stopWatching();
            resizeObserver.disconnect();
            terminal.dispose();
            terminalRef.current = null;
            fitAddonRef.current = null;
            openedRef.current = false;
            segmentCountRef.current = 0;
            sourceModeRef.current = null;
            bufferVersionRef.current = undefined;
        };
    }, []);

    // Write only new data when append-only, otherwise reset and replay.
    useEffect(() => {
        const terminal = terminalRef.current;
        if (!terminal) return;

        const nextMode: "lines" | "chunks" = chunks !== undefined ? "chunks" : "lines";
        const nextSegments = nextMode === "chunks" ? (chunks ?? []) : (lines ?? []);

        if (
            sourceModeRef.current !== nextMode
            || bufferVersionRef.current !== bufferVersion
            || nextSegments.length < segmentCountRef.current
        ) {
            terminal.reset();
            segmentCountRef.current = 0;
        }

        const newSegments = nextSegments.slice(segmentCountRef.current);
        for (const segment of newSegments) {
            terminal.write(segment);
        }

        sourceModeRef.current = nextMode;
        bufferVersionRef.current = bufferVersion;
        segmentCountRef.current = nextSegments.length;
    }, [bufferVersion, chunks, lines]);

    return (
        <div
            ref={containerRef}
            style={{ height, width: "100%", minHeight: 0 }}
        />
    );
};
