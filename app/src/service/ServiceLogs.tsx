import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { HarborService } from "../serviceMetadata";
import { useHarborStream } from "./useHarborStream";
import { IconEraser, IconX } from "../Icons";
import { XTermView } from "../terminal/XTermView";

interface ServiceLogsProps {
    service: HarborService;
    onClose: () => void;
}

export const ServiceLogs = ({ service, onClose }: ServiceLogsProps) => {
    const { lines, isStreaming, error, start, stop, clear } = useHarborStream(
        ["logs", service.handle],
        { raw: true },
    );

    const xtermRef = useRef<Terminal | null>(null);

    useEffect(() => {
        start();
        return () => {
            stop();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleClear = () => {
        clear(); // resets lines array in hook
        xtermRef.current?.reset();
    };

    const handleClose = () => {
        stop();
        onClose();
    };

    return (
        <div className="border border-base-content/10 rounded-box overflow-hidden">
            {/* Header */}
            <div className="flex items-center gap-2 px-3 py-2 bg-base-200 border-b border-base-content/10">
                <span className="text-sm font-medium flex-1">
                    {service.name ?? service.handle} — Logs
                </span>
                {isStreaming && (
                    <span className="loading loading-spinner loading-xs text-base-content/50" />
                )}
                <button
                    type="button"
                    className="btn btn-xs btn-ghost gap-1"
                    title="Clear"
                    onClick={handleClear}
                >
                    <IconEraser className="w-3.5 h-3.5" />
                    Clear
                </button>
                <button
                    type="button"
                    className="btn btn-xs btn-ghost btn-circle"
                    title="Close"
                    onClick={handleClose}
                >
                    <IconX className="w-3.5 h-3.5" />
                </button>
            </div>

            {/* Log output */}
            {error ? (
                <div className="bg-base-200 p-3">
                    <div className="alert alert-error text-sm">
                        <span>{error}</span>
                    </div>
                </div>
            ) : lines.length === 0 && isStreaming ? (
                <div className="bg-base-200 px-3 py-4">
                    <div className="flex items-center gap-2 text-base-content/50 text-sm">
                        <span className="loading loading-spinner loading-xs" />
                        Connecting to log stream...
                    </div>
                </div>
            ) : lines.length === 0 && !isStreaming ? (
                <div className="bg-base-200 px-3 py-4">
                    <p className="text-base-content/40 text-sm">
                        No log output yet.
                    </p>
                </div>
            ) : (
                <div style={{ resize: "vertical", overflow: "hidden", minHeight: "150px" }}>
                    <XTermView
                        lines={lines}
                        height="100%"
                        onReady={(t) => { xtermRef.current = t; }}
                    />
                </div>
            )}
        </div>
    );
};
