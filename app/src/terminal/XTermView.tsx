import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { buildXtermTheme, watchTheme } from "./terminalTheme";

interface XTermViewProps {
    /** Lines of raw output to display. New lines appended to end are written to terminal. */
    lines: string[];
    /** Optional CSS height for the container. Default "256px" */
    height?: string;
    /** Called when terminal is ready — useful for clearing etc. */
    onReady?: (terminal: Terminal) => void;
}

export const XTermView = ({ lines, height = "256px", onReady }: XTermViewProps) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const terminalRef = useRef<Terminal | null>(null);
    const fitAddonRef = useRef<FitAddon | null>(null);
    const openedRef = useRef(false);
    const lineCountRef = useRef(0); // how many lines have been written so far

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
            lineCountRef.current = 0;
        };
    }, []);

    // Write only new lines (append-only, never rewrite)
    useEffect(() => {
        const terminal = terminalRef.current;
        if (!terminal) return;
        const newLines = lines.slice(lineCountRef.current);
        for (const line of newLines) {
            terminal.writeln(line);
        }
        lineCountRef.current = lines.length;
    }, [lines]);

    return (
        <div
            ref={containerRef}
            style={{ height, width: "100%", minHeight: 0 }}
        />
    );
};
