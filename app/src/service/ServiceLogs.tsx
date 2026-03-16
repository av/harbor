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
    const { chunks, bufferVersion, isStreaming, error, start, stop, clear } = useHarborStream(
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

    const hasOutput = chunks.length > 0;

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
            ) : (
                <div
                    className="relative bg-base-200"
                    style={{ resize: "vertical", overflow: "hidden", minHeight: "150px" }}
                >
                    <XTermView
                        chunks={chunks}
                        bufferVersion={bufferVersion}
                        height="100%"
                        onReady={(t) => { xtermRef.current = t; }}
                    />
                    {!hasOutput && (
                        <div className="absolute inset-0 flex items-center px-3 py-4 pointer-events-none">
                            {isStreaming ? (
                                <div className="flex items-center gap-2 text-base-content/50 text-sm">
                                    <span className="loading loading-spinner loading-xs" />
                                    Connecting to log stream...
                                </div>
                            ) : (
                                <p className="text-base-content/40 text-sm">
                                    No log output yet.
                                </p>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
